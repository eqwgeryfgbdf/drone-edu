"""Decoupled flight command queue between vision and drone workers."""

from __future__ import annotations

import queue
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class CommandType(str, Enum):
    """Supported flight intents enqueued by UI or gesture filter."""

    CONNECT = "connect"
    DISCONNECT = "disconnect"
    TAKEOFF = "takeoff"
    LAND = "land"
    HOVER = "hover"
    FORWARD = "forward"
    BACKWARD = "backward"
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"
    EMERGENCY_STOP = "emergency_stop"
    RESET_AXES = "reset_axes"


# Gestures that must never be blocked by cooldown.
PRIORITY_COMMANDS = frozenset(
    {
        CommandType.EMERGENCY_STOP,
        CommandType.LAND,
        CommandType.HOVER,
        CommandType.RESET_AXES,
        CommandType.DISCONNECT,
    }
)


@dataclass(order=True)
class FlightCommand:
    """Prioritized command wrapper for the drone worker queue."""

    priority: int
    created_at: float = field(compare=False)
    command_type: CommandType = field(compare=False)
    source: str = field(default="gesture", compare=False)
    payload: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def create(
        cls,
        command_type: CommandType,
        source: str = "gesture",
        payload: Optional[dict[str, Any]] = None,
        priority: Optional[int] = None,
    ) -> "FlightCommand":
        """Factory with sensible defaults (lower number = higher priority)."""
        if priority is None:
            priority = 0 if command_type in PRIORITY_COMMANDS else 10
        return cls(
            priority=priority,
            created_at=time.time(),
            command_type=command_type,
            source=source,
            payload=payload or {},
        )


class CommandBus:
    """Thread-safe priority queue for flight commands."""

    def __init__(self, maxsize: int = 32) -> None:
        self._queue: queue.PriorityQueue[FlightCommand] = queue.PriorityQueue(maxsize=maxsize)

    def publish(self, command: FlightCommand) -> bool:
        """
        Enqueue a command.

        Returns False if the queue is full (except emergency, which drops oldest).
        """
        try:
            self._queue.put_nowait(command)
            return True
        except queue.Full:
            if command.command_type == CommandType.EMERGENCY_STOP:
                self._drain()
                try:
                    self._queue.put_nowait(command)
                    return True
                except queue.Full:
                    return False
            return False

    def publish_type(
        self,
        command_type: CommandType,
        source: str = "ui",
        payload: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Convenience publisher for simple command types."""
        return self.publish(FlightCommand.create(command_type, source=source, payload=payload))

    def get(self, timeout: float = 0.1) -> Optional[FlightCommand]:
        """Block briefly for the next command, or return None."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _drain(self) -> None:
        """Remove all pending commands (used before emergency stop)."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def clear(self) -> None:
        """Public drain for disconnect / shutdown."""
        self._drain()

    def qsize(self) -> int:
        """Approximate pending command count."""
        return self._queue.qsize()


INTENT_TO_COMMAND: dict[str, CommandType] = {
    "takeoff": CommandType.TAKEOFF,
    "land": CommandType.LAND,
    "hover": CommandType.HOVER,
    "forward": CommandType.FORWARD,
    "backward": CommandType.BACKWARD,
    "left": CommandType.LEFT,
    "right": CommandType.RIGHT,
    "up": CommandType.UP,
    "down": CommandType.DOWN,
    "emergency_stop": CommandType.EMERGENCY_STOP,
}
