"""Shared application state for vision, drone, and dashboard threads."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Optional


class ConnectionStatus(str, Enum):
    """Drone link status shown on the dashboard."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    SIMULATION = "simulation"


class FlightPhase(str, Enum):
    """High-level flight phase for UI and safety checks."""

    IDLE = "idle"
    TAKING_OFF = "taking_off"
    HOVERING = "hovering"
    MOVING = "moving"
    LANDING = "landing"
    EMERGENCY = "emergency"
    ERROR = "error"


@dataclass
class SensorSnapshot:
    """Latest telemetry reading from the drone or simulator."""

    timestamp: float = 0.0
    battery_pct: Optional[float] = None
    height_cm: Optional[float] = None
    front_range_cm: Optional[float] = None
    roll_deg: Optional[float] = None
    pitch_deg: Optional[float] = None
    yaw_deg: Optional[float] = None
    temperature_c: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for charting and logging."""
        return {
            "timestamp": self.timestamp,
            "battery_pct": self.battery_pct,
            "height_cm": self.height_cm,
            "front_range_cm": self.front_range_cm,
            "roll_deg": self.roll_deg,
            "pitch_deg": self.pitch_deg,
            "yaw_deg": self.yaw_deg,
            "temperature_c": self.temperature_c,
        }


@dataclass
class GestureSnapshot:
    """Latest gesture recognition outcome for the UI."""

    timestamp: float = 0.0
    label: str = "None"
    confidence: float = 0.0
    intent: str = "none"
    confirm_progress: float = 0.0
    hand_count: int = 0
    landmarks: list[list[tuple[float, float, float]]] = field(default_factory=list)
    pending_action: str = "—"


@dataclass
class LogEvent:
    """Single command or error event for the dashboard log."""

    timestamp: float
    level: str
    message: str
    source: str = "system"


@dataclass
class AppState:
    """Thread-safe shared state container."""

    lock: threading.RLock = field(default_factory=threading.RLock)
    simulation_mode: bool = True
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    flight_phase: FlightPhase = FlightPhase.IDLE
    last_error: str = ""
    gesture: GestureSnapshot = field(default_factory=GestureSnapshot)
    sensors: SensorSnapshot = field(default_factory=SensorSnapshot)
    sensor_history: Deque[SensorSnapshot] = field(
        default_factory=lambda: deque(maxlen=60)
    )
    events: Deque[LogEvent] = field(default_factory=lambda: deque(maxlen=200))
    camera_fps: float = 0.0
    gesture_fps: float = 0.0
    frame_jpeg: Optional[bytes] = None
    frame_timestamp: float = 0.0
    workers_running: bool = False
    emergency_latched: bool = False

    def update_gesture(self, snapshot: GestureSnapshot) -> None:
        """Replace the latest gesture snapshot."""
        with self.lock:
            self.gesture = snapshot

    def update_sensors(self, snapshot: SensorSnapshot) -> None:
        """Replace sensors and append history."""
        with self.lock:
            self.sensors = snapshot
            self.sensor_history.append(snapshot)

    def update_frame(self, jpeg_bytes: bytes, camera_fps: float, gesture_fps: float) -> None:
        """Store the latest annotated JPEG frame for Streamlit."""
        with self.lock:
            self.frame_jpeg = jpeg_bytes
            self.frame_timestamp = time.time()
            self.camera_fps = camera_fps
            self.gesture_fps = gesture_fps

    def set_connection(self, status: ConnectionStatus, error: str = "") -> None:
        """Update connection status and optional error text."""
        with self.lock:
            self.connection_status = status
            if error:
                self.last_error = error

    def set_flight_phase(self, phase: FlightPhase) -> None:
        """Update flight phase."""
        with self.lock:
            self.flight_phase = phase

    def add_event(self, message: str, level: str = "INFO", source: str = "system") -> None:
        """Append a UI/CSV event."""
        with self.lock:
            self.events.appendleft(
                LogEvent(timestamp=time.time(), level=level, message=message, source=source)
            )

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy suitable for Streamlit rendering."""
        with self.lock:
            return {
                "simulation_mode": self.simulation_mode,
                "connection_status": self.connection_status.value,
                "flight_phase": self.flight_phase.value,
                "last_error": self.last_error,
                "gesture": self.gesture,
                "sensors": self.sensors,
                "sensor_history": list(self.sensor_history),
                "events": list(self.events),
                "camera_fps": self.camera_fps,
                "gesture_fps": self.gesture_fps,
                "frame_jpeg": self.frame_jpeg,
                "frame_timestamp": self.frame_timestamp,
                "workers_running": self.workers_running,
                "emergency_latched": self.emergency_latched,
            }
