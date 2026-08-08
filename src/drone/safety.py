"""Safety gates for height, obstacle distance, and command policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.command_bus import CommandType
from src.core.state import SensorSnapshot


@dataclass
class SafetyLimits:
    """Configurable hard limits for pulse flight commands."""

    min_height_cm: float = 20.0
    max_height_cm: float = 150.0
    min_front_range_cm: float = 40.0


@dataclass
class SafetyDecision:
    """Result of evaluating whether a command may execute."""

    allowed: bool
    reason: str = ""


class SafetyGuard:
    """Evaluate whether a flight command is safe given current sensors."""

    def __init__(self, limits: SafetyLimits) -> None:
        self.limits = limits

    def evaluate(
        self,
        command_type: CommandType,
        sensors: SensorSnapshot,
        *,
        is_flying: bool,
    ) -> SafetyDecision:
        """
        Return whether the command may proceed.

        Emergency stop and disconnect are always allowed.
        """
        if command_type in {
            CommandType.EMERGENCY_STOP,
            CommandType.DISCONNECT,
            CommandType.CONNECT,
            CommandType.RESET_AXES,
        }:
            return SafetyDecision(True)

        if command_type == CommandType.TAKEOFF and is_flying:
            return SafetyDecision(False, "Already airborne; takeoff ignored")

        if command_type in {
            CommandType.LAND,
            CommandType.HOVER,
            CommandType.FORWARD,
            CommandType.BACKWARD,
            CommandType.LEFT,
            CommandType.RIGHT,
            CommandType.UP,
            CommandType.DOWN,
        } and not is_flying:
            if command_type == CommandType.LAND:
                return SafetyDecision(True, "Land while idle is a no-op")
            return SafetyDecision(False, f"{command_type.value} requires airborne state")

        if command_type == CommandType.FORWARD:
            front = sensors.front_range_cm
            if front is not None and front < self.limits.min_front_range_cm:
                return SafetyDecision(
                    False,
                    f"Front range {front:.0f} cm < {self.limits.min_front_range_cm:.0f} cm",
                )

        if command_type == CommandType.DOWN:
            height = sensors.height_cm
            if height is not None and height < self.limits.min_height_cm:
                return SafetyDecision(
                    False,
                    f"Height {height:.0f} cm < min {self.limits.min_height_cm:.0f} cm",
                )

        if command_type == CommandType.UP:
            height = sensors.height_cm
            if height is not None and height > self.limits.max_height_cm:
                return SafetyDecision(
                    False,
                    f"Height {height:.0f} cm > max {self.limits.max_height_cm:.0f} cm",
                )

        return SafetyDecision(True)

    def should_block_forward(self, front_range_cm: Optional[float]) -> bool:
        """True when forward motion is forbidden by obstacle distance."""
        return (
            front_range_cm is not None
            and front_range_cm < self.limits.min_front_range_cm
        )
