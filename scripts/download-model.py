#!/usr/bin/env python3
"""Download the official MediaPipe Gesture Recognizer .task model."""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "models" / "gesture_recognizer.task"


def main() -> int:
    """Fetch the model into models/gesture_recognizer.task."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT_PATH.exists() and OUTPUT_PATH.stat().st_size > 0:
        print(f"Model already present: {OUTPUT_PATH}")
        return 0

    print(f"Downloading Gesture Recognizer model…\n  {MODEL_URL}")
    try:
        urllib.request.urlretrieve(MODEL_URL, OUTPUT_PATH)
    except urllib.error.URLError as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    size_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024)
    print(f"Saved {OUTPUT_PATH} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
