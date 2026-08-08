"""MediaPipe Gesture Recognizer + landmark heuristics for directional intents."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Optional

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

from src.core.logging_utils import get_logger

logger = get_logger()

# MediaPipe hand connections for overlay drawing (21 landmarks).
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]


@dataclass
class DetectionResult:
    """Single-frame recognition output for the filter and UI."""

    label: str = "None"
    confidence: float = 0.0
    heuristic_intent: Optional[str] = None
    hand_count: int = 0
    landmarks: list[list[tuple[float, float, float]]] = field(default_factory=list)
    two_hands_open: bool = False


class GestureDetector:
    """
    Runs MediaPipe GestureRecognizer in VIDEO mode.

    Built-in classes: Closed_Fist, Open_Palm, Pointing_Up, Thumb_Down,
    Thumb_Up, Victory, ILoveYou, None.
    Directional left/right/down use landmark heuristics.
    """

    def __init__(
        self,
        model_path: Path,
        *,
        num_hands: int = 2,
        min_hand_detection_confidence: float = 0.5,
        min_hand_presence_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        swipe_threshold: float = 0.12,
        swipe_min_frames: int = 4,
        gesture_mappings: Optional[dict[str, str]] = None,
    ) -> None:
        if not model_path.exists():
            raise FileNotFoundError(
                f"Gesture model not found at {model_path}. "
                "Run: python scripts/download-model.py"
            )

        self.gesture_mappings = gesture_mappings or {}
        self.swipe_threshold = swipe_threshold
        self.swipe_min_frames = swipe_min_frames
        self._palm_x_history: Deque[float] = deque(maxlen=max(swipe_min_frames, 4))
        self._timestamp_ms = 0

        base_options = mp_python.BaseOptions(model_asset_path=str(model_path))
        options = mp_vision.GestureRecognizerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=min_hand_detection_confidence,
            min_hand_presence_confidence=min_hand_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._recognizer = mp_vision.GestureRecognizer.create_from_options(options)
        logger.info("GestureRecognizer loaded from %s", model_path)

    def close(self) -> None:
        """Release MediaPipe resources."""
        self._recognizer.close()

    def detect(self, frame_bgr: np.ndarray) -> DetectionResult:
        """Recognize gestures on one BGR frame and return structured output."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        self._timestamp_ms += 33
        result = self._recognizer.recognize_for_video(mp_image, self._timestamp_ms)

        landmarks = self._extract_landmarks(result)
        hand_count = len(landmarks)
        label, confidence = self._top_gesture(result)
        heuristic = self._infer_heuristic(label, landmarks, result)
        two_hands_open = self._is_two_hands_open(result, landmarks)

        return DetectionResult(
            label=label,
            confidence=confidence,
            heuristic_intent=heuristic,
            hand_count=hand_count,
            landmarks=landmarks,
            two_hands_open=two_hands_open,
        )

    def resolve_intent(self, detection: DetectionResult) -> str:
        """Map detection label / heuristics to a flight intent string."""
        if detection.two_hands_open:
            return "emergency_stop"
        if detection.heuristic_intent:
            return detection.heuristic_intent
        return self.gesture_mappings.get(detection.label, "none")

    def annotate(self, frame_bgr: np.ndarray, detection: DetectionResult) -> np.ndarray:
        """Draw hand skeleton and gesture label onto a copy of the frame."""
        annotated = frame_bgr.copy()
        height, width = annotated.shape[:2]

        for hand in detection.landmarks:
            points = []
            for x_norm, y_norm, _z in hand:
                x_px = int(x_norm * width)
                y_px = int(y_norm * height)
                points.append((x_px, y_px))
                cv2.circle(annotated, (x_px, y_px), 3, (0, 220, 180), -1)
            for start, end in HAND_CONNECTIONS:
                if start < len(points) and end < len(points):
                    cv2.line(annotated, points[start], points[end], (40, 160, 255), 2)

        text = f"{detection.label} ({detection.confidence:.0%})"
        cv2.putText(
            annotated,
            text,
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (20, 20, 20),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            annotated,
            text,
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (240, 240, 240),
            1,
            cv2.LINE_AA,
        )
        return annotated

    def _extract_landmarks(self, result: Any) -> list[list[tuple[float, float, float]]]:
        """Convert MediaPipe hand landmarks into plain tuples."""
        hands: list[list[tuple[float, float, float]]] = []
        if not result.hand_landmarks:
            return hands
        for hand in result.hand_landmarks:
            hands.append([(lm.x, lm.y, lm.z) for lm in hand])
        return hands

    def _top_gesture(self, result: Any) -> tuple[str, float]:
        """Return the highest-scoring gesture label for the first hand."""
        if not result.gestures:
            return "None", 0.0
        categories = result.gestures[0]
        if not categories:
            return "None", 0.0
        top = categories[0]
        return str(top.category_name), float(top.score)

    def _is_two_hands_open(self, result: Any, landmarks: list[Any]) -> bool:
        """True when two open palms are detected (E-stop gesture)."""
        if len(landmarks) < 2 or not result.gestures or len(result.gestures) < 2:
            return False
        open_count = 0
        for hand_gestures in result.gestures[:2]:
            if hand_gestures and hand_gestures[0].category_name == "Open_Palm":
                open_count += 1
        return open_count >= 2

    def _infer_heuristic(
        self,
        label: str,
        landmarks: list[list[tuple[float, float, float]]],
        result: Any,
    ) -> Optional[str]:
        """Derive directional intents from landmarks and swipe history."""
        if not landmarks:
            self._palm_x_history.clear()
            return None

        primary = landmarks[0]
        if len(primary) < 21:
            return None

        # Pointing down: MediaPipe has Pointing_Up but not down — use tip vs PIP.
        if label in {"None", "Pointing_Up"}:
            index_tip = primary[8]
            index_pip = primary[6]
            wrist = primary[0]
            if index_tip[1] > index_pip[1] + 0.05 and index_tip[1] > wrist[1]:
                # Finger tip below PIP and below wrist → pointing down
                return "down"

        # Palm swipe left / right using wrist x history.
        wrist_x = primary[0][0]
        self._palm_x_history.append(wrist_x)
        if len(self._palm_x_history) >= self.swipe_min_frames:
            delta = self._palm_x_history[-1] - self._palm_x_history[0]
            if delta <= -self.swipe_threshold:
                self._palm_x_history.clear()
                return "left"
            if delta >= self.swipe_threshold:
                self._palm_x_history.clear()
                return "right"

        return None


def encode_jpeg(frame_bgr: np.ndarray, quality: int = 80) -> bytes:
    """Encode a BGR frame as JPEG bytes for Streamlit."""
    ok, buffer = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("Failed to encode camera frame as JPEG")
    return buffer.tobytes()
