"""Moves: scripted button sequences that a controller chooses with one decision."""

from dataclasses import dataclass

from app.contracts import Action, has_jump, without_jump

CONTINUE = "continue"
LANDING_CAP = 60  # frames: longest wait for a landing before the script moves on


@dataclass(frozen=True)
class Segment:
    action: Action
    frames: int
    # Committed frames cannot be cut by a new decision; jumps keep A for their full height.
    committed: bool = False
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
        return [{"action": s.action.value, "frames": s.frames, "committed": s.committed,
            "until_landed": s.until_landed} for s in self.segments]


def _jump(action, hold, then):
    return (Segment(action, hold, committed=True), Segment(then, LANDING_CAP, until_landed=True))


# Calibrated in 1-1: holding A about 25 frames reaches the full jump height (64 px from standing,
# 86 px at full run). Horizontal reach of a high jump: 53 px standing, 84 walking, 150 at full run.
SHORT_HOLD = 8
HIGH_HOLD = 28

MOVES = {move.name: move for move in (
    Move("wait", "Release all buttons for 10 frames.", (Segment(Action.NOOP, 10),)),
    Move("walk_right", "Walk right for 16 frames: slower, more time to react to what appears ahead.",
        (Segment(Action.RIGHT, 16),)),
    Move("run_right", "Run right (right+B) for 16 frames: fast, little time to react to what appears ahead.",
        (Segment(Action.RIGHT_RUN, 16),)),
    Move("walk_left", "Walk left for 16 frames.", (Segment(Action.LEFT, 16),)),
    Move("run_left", "Run left (left+B) for 16 frames.", (Segment(Action.LEFT_RUN, 16),)),
    Move("short_jump_right", f"Low jump to the right: A for {SHORT_HOLD} frames, then right+B until landing. About 3 tiles high; "
        "covers about 1.5 tiles from standing, 5 tiles at full run. Stomping enemies, low walls.",
        _jump(Action.RIGHT_RUN_JUMP, SHORT_HOLD, Action.RIGHT_RUN)),
    Move("high_jump_right", f"Full-height jump to the right: A for {HIGH_HOLD} frames, then right+B until landing. About 4 tiles "
        "high (5 at full run); covers about 3 tiles from standing, 5 walking, 9 at full run. Tall pipes, stairs and pits.",
        _jump(Action.RIGHT_RUN_JUMP, HIGH_HOLD, Action.RIGHT_RUN)),
    Move("double_jump_right", "Two full-height jumps to the right: jump, land, release A, jump again, land. "
        "Consecutive obstacles, stairs.",
        (Segment(Action.RIGHT_RUN_JUMP, HIGH_HOLD, committed=True),
         Segment(Action.RIGHT_RUN, LANDING_CAP, committed=True, until_landed=True),
         *_jump(Action.RIGHT_RUN_JUMP, HIGH_HOLD, Action.RIGHT_RUN))),
    Move("short_jump_left", f"Low jump to the left: A for {SHORT_HOLD} frames, then left+B until landing.",
        _jump(Action.LEFT_RUN_JUMP, SHORT_HOLD, Action.LEFT_RUN)),
    Move("high_jump_left", f"Full-height jump to the left: A for {HIGH_HOLD} frames, then left+B until landing.",
        _jump(Action.LEFT_RUN_JUMP, HIGH_HOLD, Action.LEFT_RUN)),
    Move("high_jump_up", f"Jump straight up: A for {HIGH_HOLD} frames, then no buttons until landing. About 4 tiles high; "
        "keeps the current momentum. Hits blocks above Mario.",
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


class MoveExecutor:
    """Plays one move frame by frame; after the script its direction stays held, without A."""

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
    def committed(self) -> bool:
        return not self.finished and self.move.segments[self._segment].committed

    @property
    def remaining(self):
        """Frames left in the script, or None while a landing segment is still ahead."""
        if self.finished:
            return 0
        segments = self.move.segments[self._segment:]
        if any(segment.until_landed for segment in segments):
            return None
        return int(self._release) + sum(segment.frames for segment in segments) - self._segment_frames

    @property
    def tail_action(self) -> Action:
        """Buttons held once the script ends, until the next move."""
        return Action.NOOP if self.move is None else without_jump(self.move.segments[-1].action)

    def can_start(self, move, on_ground) -> bool:
        """A new move waits for committed frames; a jump also waits for the landing."""
        return not self.committed and not (move.jump and on_ground is False)

    def start(self, move):
        self.move = move
        self.frames = self._segment = self._segment_frames = 0
        self._airborne = False
        # A held through landing does not jump again: release it for one frame first.
        self._release = move.jump and has_jump(self.last_action)

    def settle(self, on_ground):
        """Skip what the ground has already ended; call once per frame, before current()."""
        if self.finished or self._release:
            return
        segment = self.move.segments[self._segment]
        if segment.committed and has_jump(segment.action):
            if on_ground is False:
                self._airborne = True
            elif on_ground is True and self._airborne:
                # A ceiling or a higher platform ended the jump early: A held on the ground
                # would block the next jump and every other move.
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
        if self.move is None:
            return Action.NOOP, "waiting"
        if self._release:
            return without_jump(self.move.segments[self._segment].action), "release"
        if self.finished:
            return self.tail_action, "tail"
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
