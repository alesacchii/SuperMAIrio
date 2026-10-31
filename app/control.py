"""Model-independent control protocols; only model decisions change buttons."""

from app.contracts import Action, BUTTONS, has_jump, without_jump
from app.moves import CONTINUE, MOVES, SHORT_HOLD, Move, MoveExecutor, Segment

CONTINUE_DESCRIPTION = ("Keep the current move without restarting it. If it ends before your answer arrives, "
    "continue has no effect: buttons remain released and you will be asked again. Never repeats a move.")
DIRECT_PROMPT_REVISION = 13
TIMED_PROMPT_REVISION = 1
PREDICTIVE_PROMPT_REVISION = 1
# Durations the model can choose, in game frames. 8 and 28 are the calibrated short and full A holds.
# Long holds only set a jump's height: without A they would leave Mario without reactions.
TIMED_FRAMES = (2, 4, 8, 16, 28)
UNJUMPED_FRAMES = (2, 4, 8)


def timed_frames(action):
    return TIMED_FRAMES if has_jump(action) else UNJUMPED_FRAMES


def offered_choices(catalog, *, scripted, active):
    choices = {name: move.description for name, move in catalog.items()}
    if scripted and active:
        choices[CONTINUE] = CONTINUE_DESCRIPTION
    return choices


BUTTON_EFFECTS = {
    Action.NOOP: "Release all buttons; momentum can continue.",
    Action.JUMP: "Jump vertically (A); existing horizontal momentum remains.",
    Action.LEFT: "Steer left (left); brake first if moving right.",
    Action.LEFT_RUN: "Run left (left+B); brake first if moving right.",
    Action.LEFT_JUMP: "Jump while steering left (left+A).",
    Action.LEFT_RUN_JUMP: "Run and jump left (left+B+A).",
    Action.RIGHT: "Steer right (right); brake first if moving left.",
    Action.RIGHT_RUN: "Run right (right+B); brake first if moving left.",
    Action.RIGHT_JUMP: "Jump while steering right (right+A).",
    Action.RIGHT_RUN_JUMP: "Run and jump right (right+B+A).",
}
BUTTON_MOVES = {
    action.value: Move(action.value,
        BUTTON_EFFECTS[action] + " Hold this exact input until your next choice.",
        (Segment(action, 1),))
    for action in Action
}

TIMED_MOVES = {
    f"{action.value}_{frames}": Move(f"{action.value}_{frames}",
        f"{BUTTON_EFFECTS[action]} Hold exactly this input for {frames} game frames.",
        (Segment(action, frames),))
    for action in Action for frames in timed_frames(action)
}


# Predictive control: held inputs plus short jumps, each one a model choice. A short jump holds its
# buttons with A for the calibrated short hold, then releases every button until the next choice.
HOP_FRAMES = SHORT_HOLD
HOP_ACTIONS = {"right_hop": Action.RIGHT_JUMP, "right_run_hop": Action.RIGHT_RUN_JUMP}
HOP_MOVES = {
    name: Move(name, f"Short jump: hold {'+'.join(BUTTONS[action])} for {HOP_FRAMES} game frames, then release "
        "all buttons until your next choice.", (Segment(action, HOP_FRAMES), Segment(Action.NOOP, 1)))
    for name, action in HOP_ACTIONS.items()
}
# A jump with a short run-up: from a standstill a jump covers little distance (measured in 1-1:
# from the top step before the last pit, a standing jump falls in, 4 frames of running first clear it).
RUN_UP_FRAMES = 4
RUN_UP_MOVES = {"right_run_then_jump": Move("right_run_then_jump",
    f"Jump with a run-up: hold right+B for {RUN_UP_FRAMES} game frames, then right+B+A until your next choice.",
    (Segment(Action.RIGHT_RUN, RUN_UP_FRAMES), Segment(Action.RIGHT_RUN_JUMP, 1)))}
# Each offered choice costs one emulated preview per request: jumps to the left and straight up are left out.
PREDICTIVE_MOVES = {**{name: move for name, move in BUTTON_MOVES.items()
    if name not in ("jump", "left_jump", "left_run_jump")}, **HOP_MOVES, **RUN_UP_MOVES}


def choice_frames(name, held, on_ground):
    """First frames of a predictive choice and the input then held until the next choice.

    Choosing A on the ground while A is held starts a new jump: the choice begins with one frame
    without A, the press edge the NES needs. In the air A stays held."""
    if name in RUN_UP_MOVES:
        return [Action.RIGHT_RUN] * RUN_UP_FRAMES, Action.RIGHT_RUN_JUMP
    action = HOP_ACTIONS.get(name) or Action(name)
    prefix = [without_jump(action)] if has_jump(action) and has_jump(held) and on_ground is True else []
    if name in HOP_MOVES:
        return prefix + [action] * HOP_FRAMES, Action.NOOP
    return prefix, action


class ButtonExecutor:
    """Hold the exact selected buttons, with no automatic A edges or landing logic.

    Paused debugging advances one frame per decision. Realtime holds until another
    choice, including across slow/failed requests; episode teardown drops the state.
    """

    def __init__(self, *, paused=False):
        self.paused = paused
        self.move = None
        self.frames = 0
        self.held_frames = {}

    @property
    def finished(self):
        return self.move is None or self.paused and self.frames >= 1

    @property
    def remaining(self):
        return 0 if self.finished else 1 if self.paused else None

    @property
    def jump_hold_left(self):
        # There is no planned release time from which to estimate jump airtime.
        return 0

    def start(self, move):
        self.move = move
        self.frames = 0

    def settle(self, on_ground):
        pass

    def current(self):
        return ((Action.NOOP, "waiting") if self.finished else
            (self.move.segments[0].action, "move"))

    def advance(self, frames):
        action, _ = self.current()
        self.held_frames = {button: self.held_frames.get(button, 0) + frames
            for button in BUTTONS[action] if button != "NOOP"}
        self.frames += frames

    def input_context(self):
        return {"buttons": list(self.held_frames), "held_frames": self.held_frames.copy()}


class TimedExecutor(ButtonExecutor):
    """Hold the selected buttons for the frames the model chose, then release them all.

    A new choice replaces the current one at once; repeating A does not create
    a release edge. Paused mode asks again only after the chosen frames.
    """

    @property
    def duration(self):
        return self.move.segments[0].frames

    @property
    def finished(self):
        return self.move is None or self.frames >= self.duration

    @property
    def remaining(self):
        return 0 if self.finished else self.duration - self.frames


def direct_control(mode):
    """Buttons and timed buttons: every input comes from a model choice, no scripts."""
    return mode in ("buttons", "timed")


def control_protocol(mode, *, paused=False):
    if mode == "buttons":
        return BUTTON_MOVES, ButtonExecutor(paused=paused)
    if mode == "timed":
        return TIMED_MOVES, TimedExecutor(paused=paused)
    if mode == "moves":
        return MOVES, MoveExecutor()
    raise ValueError(f"Protocollo di controllo sconosciuto: {mode}")
