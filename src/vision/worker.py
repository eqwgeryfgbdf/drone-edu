"""Camera + gesture worker thread."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Optional, Set

from src.core.command_bus import CommandBus
from src.core.logging_utils import get_logger
from src.core.state import AppState, GestureSnapshot
from src.vision.camera import CameraCapture
from src.vision.gesture_detector import GestureDetector, encode_jpeg
from src.vision.gesture_filter import GestureFilter

logger = get_logger()


class VisionWorker:
    """Captures frames, runs gesture recognition, updates shared AppState."""

    def __init__(
        self,
        state: AppState,
        command_bus: CommandBus,
        *,
        camera_settings: dict[str, Any],
        gesture_settings: dict[str, Any],
        model_path: Path,
        gesture_mappings: dict[str, str],
        enabled_intents: Set[str],
        display_names: dict[str, str],
    ) -> None:
        self.state = state
        self.command_bus = command_bus
        self.camera_settings = camera_settings
        self.gesture_settings = gesture_settings
        self.model_path = model_path
        self.gesture_mappings = gesture_mappings
        self.enabled_intents = enabled_intents
        self.display_names = display_names

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._camera: Optional[CameraCapture] = None
        self._detector: Optional[GestureDetector] = None
        self._filter: Optional[GestureFilter] = None

    def start(self) -> None:
        """Start the vision worker thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="vision-worker", daemon=True)
        self._thread.start()
        self.state.add_event("Vision worker started", source="vision")

    def stop(self) -> None:
        """Stop capture and release resources."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._cleanup()

    def _run(self) -> None:
        """Main loop: read → detect → filter → annotate → publish frame."""
        try:
            self._camera = CameraCapture(
                device_index=int(self.camera_settings.get("device_index", 0)),
                width=int(self.camera_settings.get("width", 640)),
                height=int(self.camera_settings.get("height", 480)),
                target_fps=int(self.camera_settings.get("target_fps", 20)),
                mirror=bool(self.camera_settings.get("mirror", True)),
            )
            self._camera.open()
            self._detector = GestureDetector(
                self.model_path,
                num_hands=int(self.gesture_settings.get("num_hands", 2)),
                min_hand_detection_confidence=float(
                    self.gesture_settings.get("min_hand_detection_confidence", 0.5)
                ),
                min_hand_presence_confidence=float(
                    self.gesture_settings.get("min_hand_presence_confidence", 0.5)
                ),
                min_tracking_confidence=float(
                    self.gesture_settings.get("min_tracking_confidence", 0.5)
                ),
                swipe_threshold=float(self.gesture_settings.get("swipe_threshold", 0.12)),
                swipe_min_frames=int(self.gesture_settings.get("swipe_min_frames", 4)),
                gesture_mappings=self.gesture_mappings,
            )
            self._filter = GestureFilter(
                self.command_bus,
                enabled_intents=self.enabled_intents,
                display_names=self.display_names,
                confirm_duration_sec=float(
                    self.gesture_settings.get("confirm_duration_sec", 0.8)
                ),
                confirm_frames_needed=int(
                    self.gesture_settings.get("confirm_frames_needed", 8)
                ),
                confirm_frames_window=int(
                    self.gesture_settings.get("confirm_frames_window", 10)
                ),
                cooldown_sec=float(self.gesture_settings.get("cooldown_sec", 1.0)),
                no_hand_timeout_sec=float(
                    self.gesture_settings.get("no_hand_timeout_sec", 0.5)
                ),
            )
        except Exception as exc:
            logger.exception("Vision worker failed to start: %s", exc)
            self.state.add_event(f"Vision start failed: {exc}", level="ERROR", source="vision")
            self._cleanup()
            return

        frame_times: list[float] = []
        gesture_times: list[float] = []
        target_fps = max(int(self.camera_settings.get("target_fps", 20)), 1)
        min_interval = 1.0 / target_fps

        assert self._camera is not None
        assert self._detector is not None
        assert self._filter is not None

        while not self._stop_event.is_set():
            loop_start = time.time()
            frame = self._camera.read()
            if frame is None:
                time.sleep(0.01)
                continue

            detect_start = time.time()
            detection = self._detector.detect(frame)
            intent = self._detector.resolve_intent(detection)
            filtered = self._filter.process(detection, intent)
            gesture_times.append(time.time() - detect_start)

            annotated = self._detector.annotate(frame, detection)
            try:
                jpeg = encode_jpeg(annotated)
            except RuntimeError as exc:
                self.state.add_event(str(exc), level="ERROR", source="vision")
                continue

            now = time.time()
            frame_times.append(now)
            frame_times = [t for t in frame_times if now - t < 1.0]
            gesture_times = gesture_times[-30:]
            camera_fps = float(len(frame_times))
            gesture_fps = (
                1.0 / (sum(gesture_times) / len(gesture_times)) if gesture_times else 0.0
            )

            self.state.update_frame(jpeg, camera_fps, gesture_fps)
            self.state.update_gesture(
                GestureSnapshot(
                    timestamp=now,
                    label=filtered.label,
                    confidence=filtered.confidence,
                    intent=filtered.intent,
                    confirm_progress=filtered.confirm_progress,
                    hand_count=detection.hand_count,
                    landmarks=detection.landmarks,
                    pending_action=filtered.pending_action,
                )
            )

            elapsed = time.time() - loop_start
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)

        self._cleanup()

    def _cleanup(self) -> None:
        """Release camera and recognizer."""
        if self._detector is not None:
            try:
                self._detector.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Detector close failed: %s", exc)
            self._detector = None
        if self._camera is not None:
            self._camera.release()
            self._camera = None
