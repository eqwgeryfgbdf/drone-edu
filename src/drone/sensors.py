"""Sensor polling helpers for CoDrone EDU telemetry."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from src.core.logging_utils import get_logger
from src.core.state import SensorSnapshot

logger = get_logger()


def _safe_call(fn: Callable[[], Any], label: str) -> Optional[Any]:
    """Call an SDK method and return None on failure without raising."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — SDK errors vary widely
        logger.debug("Sensor %s read failed: %s", label, exc)
        return None


def _as_float(value: Any) -> Optional[float]:
    """Best-effort conversion of SDK return values to float."""
    if value is None:
        return None
    try:
        if isinstance(value, (list, tuple)) and value:
            return float(value[0])
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_angles(value: Any) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Parse roll/pitch/yaw from get_angle-style returns."""
    if value is None:
        return None, None, None
    try:
        if isinstance(value, dict):
            return (
                _as_float(value.get("roll")),
                _as_float(value.get("pitch")),
                _as_float(value.get("yaw")),
            )
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return float(value[0]), float(value[1]), float(value[2])
        if isinstance(value, (int, float)):
            return None, None, float(value)
    except (TypeError, ValueError):
        return None, None, None
    return None, None, None


class SensorReader:
    """Read CoDrone EDU sensors with graceful method-name fallbacks."""

    def __init__(self, drone: Any) -> None:
        self._drone = drone

    def read(self) -> SensorSnapshot:
        """Poll the current sensor suite once."""
        drone = self._drone
        battery = _safe_call(lambda: getattr(drone, "get_battery")(), "battery")
        height = _safe_call(lambda: getattr(drone, "get_height")(), "height")
        if height is None and hasattr(drone, "get_bottom_range"):
            height = _safe_call(lambda: drone.get_bottom_range(), "bottom_range")

        front = None
        if hasattr(drone, "get_front_range"):
            front = _safe_call(lambda: drone.get_front_range(), "front_range")

        temperature = None
        if hasattr(drone, "get_drone_temperature"):
            temperature = _safe_call(lambda: drone.get_drone_temperature(), "temperature")
        elif hasattr(drone, "get_temperature"):
            temperature = _safe_call(lambda: drone.get_temperature(), "temperature")

        roll = pitch = yaw = None
        if hasattr(drone, "get_angle"):
            angles = _safe_call(lambda: drone.get_angle(), "angle")
            roll, pitch, yaw = _parse_angles(angles)
        elif hasattr(drone, "get_heading"):
            yaw = _as_float(_safe_call(lambda: drone.get_heading(), "heading"))

        return SensorSnapshot(
            timestamp=time.time(),
            battery_pct=_as_float(battery),
            height_cm=_as_float(height),
            front_range_cm=_as_float(front),
            roll_deg=roll,
            pitch_deg=pitch,
            yaw_deg=yaw,
            temperature_c=_as_float(temperature),
        )


class SimulatedSensorReader:
    """Produce plausible telemetry while simulation_mode is on."""

    def __init__(self) -> None:
        self._t0 = time.time()
        self.height_cm = 0.0
        self.front_range_cm = 120.0
        self.is_flying = False

    def set_flying(self, flying: bool) -> None:
        """Update simulated airborne state."""
        self.is_flying = flying
        if flying and self.height_cm < 80:
            self.height_cm = 100.0
        if not flying:
            self.height_cm = 0.0

    def nudge(self, command: str) -> None:
        """Apply a short pulse effect to simulated sensors."""
        if command == "up":
            self.height_cm = min(160.0, self.height_cm + 25.0)
        elif command == "down":
            self.height_cm = max(0.0, self.height_cm - 25.0)
        elif command == "forward":
            self.front_range_cm = max(10.0, self.front_range_cm - 15.0)
        elif command in {"left", "right", "hover"}:
            pass

    def read(self) -> SensorSnapshot:
        """Return simulated sensor values with gentle noise."""
        elapsed = time.time() - self._t0
        wobble = 1.5 if self.is_flying else 0.0
        return SensorSnapshot(
            timestamp=time.time(),
            battery_pct=92.0 - (elapsed / 120.0),
            height_cm=self.height_cm,
            front_range_cm=self.front_range_cm,
            roll_deg=wobble * ((elapsed * 0.7) % 2 - 1),
            pitch_deg=wobble * ((elapsed * 0.5) % 2 - 1),
            yaw_deg=(elapsed * 3.0) % 360.0 if self.is_flying else 0.0,
            temperature_c=34.0 + (0.2 if self.is_flying else 0.0),
        )
