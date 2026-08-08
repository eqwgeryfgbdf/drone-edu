"""OpenCV camera capture helper."""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from src.core.logging_utils import get_logger

logger = get_logger()


class CameraCapture:
    """Thin wrapper around cv2.VideoCapture with configured resolution."""

    def __init__(
        self,
        device_index: int = 0,
        width: int = 640,
        height: int = 480,
        target_fps: int = 20,
        mirror: bool = True,
    ) -> None:
        self.device_index = device_index
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.mirror = mirror
        self._cap: Optional[cv2.VideoCapture] = None

    def open(self) -> None:
        """Open the camera device and apply capture properties."""
        self._cap = cv2.VideoCapture(self.device_index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Unable to open camera index {self.device_index}. "
                "Check permissions and device availability."
            )
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.target_fps)
        logger.info(
            "Camera opened index=%s size=%sx%s",
            self.device_index,
            self.width,
            self.height,
        )

    def read(self) -> Optional[np.ndarray]:
        """Return a BGR frame, or None if capture failed."""
        if self._cap is None:
            raise RuntimeError("Camera is not open")
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        if self.mirror:
            frame = cv2.flip(frame, 1)
        return frame

    def release(self) -> None:
        """Release the underlying VideoCapture."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("Camera released")
