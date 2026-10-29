"""Moves: scripted button sequences that a controller chooses with one decision."""

from dataclasses import dataclass

from app.contracts import Action, has_jump, without_jump

CONTINUE = "continue"
LANDING_CAP = 60  # frames: longest wait for a landing before the script moves on


@dataclass(frozen=True)
class Segment:
    action: Action
    frames: int
    # Ends as soon as Mario is on the ground; frames is then only an upper bound.
    until_landed: bool = False


@dataclass(frozen=True)
class Move:
    name: str
    description: str
    segments: tuple[Segment, ...]

    @property
    def jump(self) -> bool:
        return has_jump(self.segments[0].action)

    def summary(self):
        return [{"action": s.action.value, "frames": s.frames,
            "until_landed": s.until_landed} for s in self.segments]


def _jump(action, hold, then):
    return (Segment(action, hold), Segment(then, LANDING_CAP, until_landed=True))


# Calibrated in 1-1: holding A about 25 frames reaches the full jump height (64 px from standing,
# 86 px at full run). Horizontal reach of a high jump: 53 px standing, 84 walking, 150 at full run.
SHORT_HOLD = 8
HIGH_HOLD = 28

# Frames from the A press to the landing at the take-off height, measured in 1-1. The game picks the
# jump physics from the speed at the press: up to 1 px/frame, up to 1.75 (walking), faster (running).
JUMP_AIRTIME = ((1.0, 27, 44), (1.75, 30, 48), (float("inf"), 29, 50))  # (max speed, short_jump, high_jump)


def _airborne(column):
    frames = [row[column] for row in JUMP_AIRTIME]
    return f"Airborne about {min(frames)}-{max(frames)} frames on flat ground; pressing A in the air does not start a new jump."


MOVES = {move.name: move for move in (
    Move("wait", "Release all buttons for 10 frames; current momentum does not stop immediately.", (Segment(Action.NOOP, 10),)),
    Move("walk_right", "Walk right for 16 frames: slower, more time to react to what appears ahead.",
        (Segment(Action.RIGHT, 16),)),
    Move("run_right", "Run right (right+B) for 16 frames: fast, little time to react to what appears ahead.",
        (Segment(Action.RIGHT_RUN, 16),)),
    Move("walk_left", "Press left for 16 frames; if moving right, first brake before moving left.", (Segment(Action.LEFT, 16),)),
    Move("run_left", "Run left (left+B) for 16 frames.", (Segment(Action.LEFT_RUN, 16),)),
    Move("short_jump_right", f"Low jump to the right: A for {SHORT_HOLD} frames, then right+B until landing. About 3 tiles high; "
        f"covers about 1.5 tiles from standing, 5 tiles at full run. {_airborne(1)} Stomping enemies, low walls.",
        _jump(Action.RIGHT_RUN_JUMP, SHORT_HOLD, Action.RIGHT_RUN)),
    Move("high_jump_right", f"Full-height jump to the right: A for {HIGH_HOLD} frames, then right+B until landing. About 4 tiles "
        f"high (5 at full run); covers about 3 tiles from standing, 5 walking, 9 at full run. {_airborne(2)} "
        "Tall pipes, stairs and pits.",
        _jump(Action.RIGHT_RUN_JUMP, HIGH_HOLD, Action.RIGHT_RUN)),
    Move("double_jump_right", "Two full-height jumps to the right: jump, land, release A, jump again, land. "
        "Interruptible at any point by another move. "
        f"{_airborne(2)} Consecutive obstacles, stairs.",
        (Segment(Action.RIGHT_RUN_JUMP, HIGH_HOLD),
         Segment(Action.RIGHT_RUN, LANDING_CAP, until_landed=True),
         *_jump(Action.RIGHT_RUN_JUMP, HIGH_HOLD, Action.RIGHT_RUN))),
    Move("short_jump_left", f"Low jump to the left: A for {SHORT_HOLD} frames, then left+B until landing. {_airborne(1)}",
        _jump(Action.LEFT_RUN_JUMP, SHORT_HOLD, Action.LEFT_RUN)),
    Move("high_jump_left", f"Full-height jump to the left: A for {HIGH_HOLD} frames, then left+B until landing. {_airborne(2)}",
        _jump(Action.LEFT_RUN_JUMP, HIGH_HOLD, Action.LEFT_RUN)),
    Move("high_jump_up", f"Jump straight up: A for {HIGH_HOLD} frames, then no buttons until landing. About 4 tiles high; "
        f"keeps the current momentum. {_airborne(2)} Hits blocks above Mario.",
        _jump(Action.JUMP, HIGH_HOLD, Action.NOOP)),
)}
CHOICES = (*MOVES, CONTINUE)

# Horizontal reach in px measured in 1-1 at speed 0, walking (1.75 px/frame) and full run (3.0).
JUMP_REACH = ((0.0, 23, 53), (1.75, 52, 84), (3.0, 87, 150))  # (speed, short_jump, high_jump)


def jump_reach(speed) -> dict:
    """Forward distance covered by each jump at the current speed, interpolated between the measures."""
    speed = min(abs(speed), JUMP_REACH[-1][0])
    for (low, *low_reach), (high, *high_reach) in zip(JUMP_REACH, JUMP_REACH[1:]):
        if speed <= high:
            share = (speed - low) / (high - low)
            short, tall = (round(a + (b - a) * share) for a, b in zip(low_reach, high_reach))
            return {"short_jump": short, "high_jump": tall}



def jump_airtime(speed, hold) -> int:
    """Flat-ground airtime for A held `hold` frames, between the two calibrated holds."""
    short, high = next((short, high) for limit, short, high in JUMP_AIRTIME if abs(speed) <= limit)
    share = min(max((hold - SHORT_HOLD) / (HIGH_HOLD - SHORT_HOLD), 0), 1)
    return round(short + (high - short) * share)


class Flight:
    """Frames until a jump lands back at its take-off height; walls, platforms and pits change it."""

    def __init__(self):
        self.frames = None  # since the A press; None without a jump in progress
        self.last_action = Action.NOOP
        self._speed = self._hold = 0
        self._holding = self._airborne = False
        self._invalid = False

    def invalidate(self):
        self._invalid = True

    def step(self, action, was_on_ground, on_ground, speed):
        """Call once per frame with its buttons, the ground before and after it and the speed before it."""
        pressed = has_jump(action) and not has_jump(self.last_action)
        self.last_action = action
        if pressed and was_on_ground is True:
            self._invalid = False
            self.frames = None
        if on_ground is None:
            self.frames = None
        elif self.frames is None:
            if pressed and was_on_ground is True and speed is not None:
                self.frames, self._speed, self._hold = 1, speed, 1
                self._holding, self._airborne = True, on_ground is False
        else:
            self.frames += 1
            self._holding = self._holding and has_jump(action)
            self._hold += self._holding
            if on_ground is False:
                self._airborne = True
            elif self._airborne or self.frames > 3:  # landed, or A never left the ground
                self.frames = None

    def landing_in(self, speed, on_ground, hold_left=0):
        """Estimated frames to the landing; a jump not pressed yet counts from now.
        None when unknown, or once Mario falls below the take-off height."""
        if self._invalid:
            return None
        if self.frames is not None:
            left = jump_airtime(self._speed, self._hold + (hold_left if self._holding else 0)) - self.frames
            return left if left > 0 else None
        if hold_left and on_ground is True and speed is not None and not has_jump(self.last_action):
            return jump_airtime(speed, hold_left)
        return None

    def observed(self):
        """Observed initial input and elapsed frames, not a landing prediction.

        A later replacement invalidates the landing estimate, but does not change
        the historical speed at the initial A press or its actual hold duration.
        """
        if self.frames is None:
            return None
        return {"frames_since_A_press": self.frames, "speed_at_A_press": self._speed,
            "initial_A_hold_frames": self._hold, "initial_A_still_held": self._holding,
            "left_ground": self._airborne,
            "flat_ground_reach_at_press": jump_reach(self._speed)}


class MoveExecutor:
    """Interruptible button scripts; completion releases every button."""

    def __init__(self):
        self.move = None
        self.frames = 0
        self.last_action = Action.NOOP
        self._segment = self._segment_frames = 0
        self._release = self._airborne = False

    @property
    def finished(self) -> bool:
        return self.move is None or self._segment >= len(self.move.segments)

    @property
    def jump_hold_left(self) -> int:
        if self.finished or self._release:
            return 0
        segment = self.move.segments[self._segment]
        return segment.frames - self._segment_frames if has_jump(segment.action) else 0

    @property
    def remaining(self):
        if self.finished:
            return 0
        segments = self.move.segments[self._segment:]
        if any(segment.until_landed for segment in segments):
            return None
        return int(self._release) + sum(segment.frames for segment in segments) - self._segment_frames

    def start(self, move):
        self.move = move
        self.frames = self._segment = self._segment_frames = 0
        self._airborne = False
        # NES needs a new A edge; this release is part of the new script.
        self._release = move.jump and has_jump(self.last_action)

    def settle(self, on_ground):
        if self.finished or self._release:
            return
        segment = self.move.segments[self._segment]
        if has_jump(segment.action):
            if on_ground is False:
                self._airborne = True
            elif on_ground is True and self._airborne:
                self._next_segment()
                if not self.finished and self.move.segments[self._segment].until_landed:
                    self._next_segment()
                if not self.finished and has_jump(self.move.segments[self._segment].action):
                    self._release = has_jump(self.last_action)
                return
        while (not self.finished and on_ground is True
                and self.move.segments[self._segment].until_landed and self._segment_frames > 0):
            self._next_segment()

    def current(self) -> tuple[Action, str]:
        if self.finished:
            return Action.NOOP, "waiting"
        if self._release:
            return without_jump(self.move.segments[self._segment].action), "release"
        return self.move.segments[self._segment].action, "move"

    def advance(self, frames):
        action, source = self.current()
        self.last_action = action
        if source == "release":
            self._release = False
            self.frames += frames
        elif source == "move":
            self.frames += frames
            self._segment_frames += frames
            if self._segment_frames >= self.move.segments[self._segment].frames:
                self._next_segment()

    def _next_segment(self):
        self._segment += 1
        self._segment_frames = 0
        self._airborne = False
