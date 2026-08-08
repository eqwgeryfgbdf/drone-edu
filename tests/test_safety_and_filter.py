"""Unit tests for safety and gesture confirmation (no hardware required)."""

from __future__ import annotations

import time

from src.core.command_bus import CommandBus, CommandType
from src.core.state import SensorSnapshot
from src.drone.safety import SafetyGuard, SafetyLimits
from src.vision.gesture_detector import DetectionResult
from src.vision.gesture_filter import GestureFilter


def test_safety_blocks_forward_when_obstacle_near() -> None:
    """Forward must be blocked under the front-range limit."""
    guard = SafetyGuard(SafetyLimits(min_front_range_cm=40))
    sensors = SensorSnapshot(front_range_cm=25, height_cm=80)
    decision = guard.evaluate(CommandType.FORWARD, sensors, is_flying=True)
    assert decision.allowed is False
    assert "Front range" in decision.reason


def test_safety_blocks_down_near_ground() -> None:
    """Downward pulse must be blocked under min height."""
    guard = SafetyGuard(SafetyLimits(min_height_cm=20))
    sensors = SensorSnapshot(height_cm=15, front_range_cm=100)
    decision = guard.evaluate(CommandType.DOWN, sensors, is_flying=True)
    assert decision.allowed is False


def test_safety_allows_emergency_always() -> None:
    """Emergency stop is never blocked by sensor gates."""
    guard = SafetyGuard(SafetyLimits())
    decision = guard.evaluate(
        CommandType.EMERGENCY_STOP,
        SensorSnapshot(front_range_cm=5, height_cm=5),
        is_flying=True,
    )
    assert decision.allowed is True


def test_gesture_filter_requires_confirmation() -> None:
    """A single Thumb_Up frame must not enqueue takeoff."""
    bus = CommandBus()
    filt = GestureFilter(
        bus,
        enabled_intents={"takeoff", "hover", "land", "emergency_stop"},
        display_names={"takeoff": "起飛"},
        confirm_duration_sec=0.8,
        confirm_frames_needed=8,
        confirm_frames_window=10,
        cooldown_sec=1.0,
        no_hand_timeout_sec=0.5,
    )
    detection = DetectionResult(label="Thumb_Up", confidence=0.9, hand_count=1)
    output = filt.process(detection, "takeoff")
    assert output.accepted is False
    assert bus.qsize() == 0


def test_gesture_filter_accepts_after_duration() -> None:
    """Holding takeoff intent past confirm_duration enqueues the command."""
    bus = CommandBus()
    filt = GestureFilter(
        bus,
        enabled_intents={"takeoff", "hover", "land", "emergency_stop"},
        display_names={"takeoff": "起飛"},
        confirm_duration_sec=0.2,
        confirm_frames_needed=20,
        confirm_frames_window=20,
        cooldown_sec=0.0,
        no_hand_timeout_sec=0.5,
    )
    detection = DetectionResult(label="Thumb_Up", confidence=0.95, hand_count=1)
    accepted = False
    deadline = time.time() + 1.0
    while time.time() < deadline:
        output = filt.process(detection, "takeoff")
        if output.accepted:
            accepted = True
            break
        time.sleep(0.05)
    assert accepted is True
    command = bus.get(timeout=0.2)
    assert command is not None
    assert command.command_type == CommandType.TAKEOFF
