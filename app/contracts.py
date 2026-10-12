"""Actions and observations shared by every controller."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
from numpy.typing import NDArray


class Action(StrEnum):
    NOOP = "noop"
    JUMP = "jump"
    LEFT = "left"
    LEFT_JUMP = "left_jump"
    LEFT_RUN = "left_run"
    LEFT_RUN_JUMP = "left_run_jump"
    RIGHT = "right"
    RIGHT_JUMP = "right_jump"
    RIGHT_RUN = "right_run"
    RIGHT_RUN_JUMP = "right_run_jump"


BUTTONS = {
    Action.NOOP: ("NOOP",),
    Action.JUMP: ("A",),
    Action.LEFT: ("left",),
    Action.LEFT_JUMP: ("left", "A"),
    Action.LEFT_RUN: ("left", "B"),
    Action.LEFT_RUN_JUMP: ("left", "A", "B"),
    Action.RIGHT: ("right",),
    Action.RIGHT_JUMP: ("right", "A"),
    Action.RIGHT_RUN: ("right", "B"),
    Action.RIGHT_RUN_JUMP: ("right", "A", "B"),
}


def has_jump(action: Action) -> bool:
    return "A" in BUTTONS[action]


def without_jump(action: Action) -> Action:
    """Same direction and run buttons with A released."""
    return Action(action.value.removesuffix("_jump")) if action != Action.JUMP else Action.NOOP


def keyboard_action(left: bool, right: bool, jump: bool, run: bool) -> Action:
    """Opposite directions cancel; running needs a direction."""
    direction = "left" if left and not right else "right" if right and not left else ""
    if not direction:
        return Action.JUMP if jump else Action.NOOP
    return Action(direction + ("_run" if run else "") + ("_jump" if jump else ""))


@dataclass(frozen=True)
class Observation:
    rgb: NDArray[np.uint8]
    info: dict[str, Any]


@dataclass(frozen=True)
class Decision:
    move: str  # a move name from app.moves, or "continue"
    model: str
    request_id: str | None = None
    provider: str | None = None
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class DecisionRequest:
    """Adapter-specific wire payload and log metadata, without credentials."""

    payload: dict[str, Any]
    trace: dict[str, Any]


@dataclass(frozen=True)
class StepResult:
    observation: Observation
    reward: float
    frames_executed: int
    terminated: bool
    truncated: bool

    @property
    def done(self) -> bool:
        return self.terminated or self.truncated
