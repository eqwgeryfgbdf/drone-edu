"""Gesture confirmation filter — blocks single-frame false positives."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Set

from src.core.command_bus import INTENT_TO_COMMAND, CommandBus, CommandType
from src.core.logging_utils import get_logger
from src.vision.gesture_detector import DetectionResult

logger = get_logger()


@dataclass
class FilterOutput:
    """Filtered gesture status for UI progress display."""

    intent: str
    label: str
    confidence: float
    confirm_progress: float
    pending_action: str
    accepted: bool = False
    no_hand: bool = False


class GestureFilter:
    """
    Stabilize gesture intents before publishing flight commands.

    Rules:
    - Same intent must hold for confirm_duration_sec OR pass N/M frames.
    - Movement commands respect cooldown_sec.
    - No-hand longer than no_hand_timeout_sec → RESET_AXES / hover.
    """

    def __init__(
        self,
        command_bus: CommandBus,
        *,
        enabled_intents: Set[str],
        display_names: dict[str, str],
        confirm_duration_sec: float = 0.8,
        confirm_frames_needed: int = 8,
        confirm_frames_window: int = 10,
        cooldown_sec: float = 1.0,
        no_hand_timeout_sec: float = 0.5,
    ) -> None:
        self.command_bus = command_bus
        self.enabled_intents = enabled_intents
        self.display_names = display_names
        self.confirm_duration_sec = confirm_duration_sec
        self.confirm_frames_needed = confirm_frames_needed
        self.confirm_frames_window = confirm_frames_window
        self.cooldown_sec = cooldown_sec
        self.no_hand_timeout_sec = no_hand_timeout_sec

        self._history: Deque[str] = deque(maxlen=confirm_frames_window)
        self._candidate: Optional[str] = None
        self._candidate_since: float = 0.0
        self._last_accepted_at: float = 0.0
        self._last_accepted_intent: Optional[str] = None
        self._last_hand_seen_at: float = time.time()
        self._no_hand_triggered = False

    def process(self, detection: DetectionResult, intent: str) -> FilterOutput:
        """Update confirmation state and optionally publish a command."""
        now = time.time()
        label = detection.label
        confidence = detection.confidence

        if detection.hand_count <= 0:
            return self._handle_no_hand(now, label)

        self._last_hand_seen_at = now
        self._no_hand_triggered = False

        if intent not in self.enabled_intents or intent == "none":
            self._reset_candidate()
            self._history.append("none")
            return FilterOutput(
                intent="none",
                label=label,
                confidence=confidence,
                confirm_progress=0.0,
                pending_action=self.display_names.get("none", "—"),
            )

        self._history.append(intent)
        progress = self._compute_progress(intent, now)

        accepted = False
        if progress >= 1.0 and self._cooldown_allows(intent, now):
            accepted = self._accept(intent, now)

        return FilterOutput(
            intent=intent,
            label=label,
            confidence=confidence,
            confirm_progress=min(progress, 1.0),
            pending_action=self.display_names.get(intent, intent),
            accepted=accepted,
        )

    def _handle_no_hand(self, now: float, label: str) -> FilterOutput:
        """Clear candidate and trigger auto-hover after timeout."""
        self._reset_candidate()
        self._history.append("none")
        elapsed = now - self._last_hand_seen_at
        if elapsed >= self.no_hand_timeout_sec and not self._no_hand_triggered:
            self._no_hand_triggered = True
            self.command_bus.publish_type(CommandType.RESET_AXES, source="gesture-no-hand")
            self.command_bus.publish_type(CommandType.HOVER, source="gesture-no-hand")
            logger.info("No hand for %.2fs → reset axes / hover", elapsed)

        return FilterOutput(
            intent="none",
            label=label or "None",
            confidence=0.0,
            confirm_progress=0.0,
            pending_action="無手 → 懸停",
            no_hand=True,
        )

    def _compute_progress(self, intent: str, now: float) -> float:
        """Combine duration-based and frame-window confirmation."""
        if self._candidate != intent:
            self._candidate = intent
            self._candidate_since = now

        duration_progress = (now - self._candidate_since) / max(self.confirm_duration_sec, 1e-3)
        matches = sum(1 for item in self._history if item == intent)
        frame_progress = matches / max(self.confirm_frames_needed, 1)
        return max(duration_progress, frame_progress)

    def _cooldown_allows(self, intent: str, now: float) -> bool:
        """Emergency / land / hover bypass cooldown; moves respect it."""
        if intent in {"emergency_stop", "land", "hover"}:
            return True
        if self._last_accepted_intent == intent and (now - self._last_accepted_at) < self.cooldown_sec:
            return False
        if (now - self._last_accepted_at) < self.cooldown_sec and intent not in {
            "emergency_stop",
            "land",
            "hover",
        }:
            return False
        return True

    def _accept(self, intent: str, now: float) -> bool:
        """Publish the confirmed intent to the command bus."""
        command_type = INTENT_TO_COMMAND.get(intent)
        if command_type is None:
            return False
        published = self.command_bus.publish_type(command_type, source="gesture")
        if not published:
            logger.warning("Command queue full; dropped intent=%s", intent)
            return False
        self._last_accepted_at = now
        self._last_accepted_intent = intent
        self._reset_candidate()
        self._history.clear()
        logger.info("Accepted gesture intent=%s", intent)
        return True

    def _reset_candidate(self) -> None:
        """Clear the in-progress confirmation candidate."""
        self._candidate = None
        self._candidate_since = 0.0
