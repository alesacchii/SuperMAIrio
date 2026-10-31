"""Shared multimodal Choice adapter for System One models."""

import base64
from io import BytesIO
import json

from PIL import Image, ImageOps

from app.contracts import Action, Decision, DecisionRequest, has_jump
from app.control import BUTTON_EFFECTS, BUTTON_MOVES, CONTINUE_DESCRIPTION, TIMED_MOVES
from app.moves import CONTINUE, HIGH_HOLD, MOVES, SHORT_HOLD, jump_reach
from app.openrouter import OpenRouterClient, parse_decision

GOAL = (
    "Goal: reach the flagpole at the end of Super Mario Bros level 1-1 (progress.percent). "
    "Priorities: stay alive, then move right, then grab a mushroom; coins only give points. "
)
DIRECT_GUIDE = (
    "You control Mario. Select the NEXT button input that best keeps him alive and advances toward the flag. "
    "Choose what to DO next, not a description of his present movement. "
    "The screenshot and JSON describe the same instant. dx is object left minus Mario left; Mario is 16 pixels wide. "
    "dy is object bottom above Mario feet. Speed is pixels per game frame. "
    "Enemies hurt on side contact; landing on top stomps them. "
    "Pits have no floor: falling in is fatal. Pipes and blocks are solid. Hitting a block overhead stops ascent. "
    "A starts a jump only on the ground after being released; holding A sustains height. A in midair cannot "
    "start another jump. Holding A across landing does not repeat a jump. B with a direction runs. "
    f"Calibrated A hold: about {SHORT_HOLD} game frames for a short jump, {HIGH_HOLD} for full height; "
    "these are game frames, not decisions. A ceiling can stop ascent earlier. "
    "{holding}"
    "input.buttons and held_frames describe actual button presses, including repeated choices. "
    "On the ground, jump_reach_px estimates the reach of a NEW short/full jump on flat ground. "
    "While airborne, jump_observation reports the actual initial A press, its speed, elapsed frames and held frames. "
    "Its flat_ground_reach_at_press is the WHOLE calibrated jump reach at that initial speed, not remaining travel. "
    "Obstacles, steering, release time and different landing heights change the trajectory. "
    "Only visible geometry is known. A pit's width is incomplete when width_is_lower_bound is true. "
    "nearby.surfaces lists visible solid top faces: dx is the left edge, width_px the visible width, "
    "top_dy the top above Mario's feet (positive is higher). These describe ground, steps and platforms; "
    "they are not chosen landing targets. Clipped edges and full widths remain unknown. "
    "Consider hazards, momentum, and where Mario will land. "
    "Only you select buttons; the program never jumps, brakes or releases them for you. "
)
HOLD_UNTIL_NEXT = "Input stays held until your next choice; repeating a choice does not release A. "
HOLD_PREDICTED = ("Input stays held until your next choice, about {frames} game frames later (move.hold_frames). "
    "Choosing an input with A while Mario is on the ground starts a jump, even if A was already held: "
    "the choice then begins with one frame without A, so the NES sees a new press. In the air, an input "
    "with A keeps A held. While rising, choosing an input without A ends the height gain: keep A for a "
    "high jump. Choices ending in _hop, when offered, are short jumps: A for a few frames, then every button "
    "released until your next choice; right_run_then_jump runs a few frames before pressing A. "
    "contact_in_frames, when present, estimates the frames until Mario's edge horizontally meets that enemy, "
    "wall or pit at the current speeds (heights and acceleration ignored); compare it with move.hold_frames. ")
PREVIEW = ("Each option ends with its emulated preview: the result of holding only that choice for "
    "{frames} game frames from the shown instant, extended while Mario is still in the air until he lands or "
    "dies. It ignores your later choices, which can change what happens; it is information, not advice. ")


def preview_text(result):
    """One option's emulated preview, in words: outcome, travel and height change."""
    if result["outcome"] == "dies":
        return f" Preview: Mario dies after {result['frames']} frames."
    if result["outcome"] == "flag":
        return f" Preview: Mario reaches the flag after {result['frames']} frames."
    moved = (f", {abs(result['dx'])} px {'right' if result['dx'] >= 0 else 'left'}" if "dx" in result else "")
    height = (f", {abs(result['dy'])} px {'higher' if result['dy'] > 0 else 'lower'}"
        if result.get("dy") else "")
    where = "on the ground" if result.get("on_ground") else "in the air"
    return f" Preview: alive after {result['frames']} frames{moved}{height}, {where}."
RUN_UP = ("A standing jump covers little distance: before a wide pit, move close to its edge or back up for a "
    "running start. ")
PREDICTED_TIMING = ("The game runs at {fps} FPS and does not wait for you. The screenshot and state are not the "
    "past: they show the instant your choice takes effect, predicted by emulating the game with the inputs "
    "already chosen. They are exact unless your answer arrives late. Your next choice will likewise see the "
    "instant it takes effect. ")
HOLD_TIMED = ("You choose the buttons and how many game frames to hold them: right_run_jump for 28 frames holds "
    "right+B+A for 28 frames. A new choice replaces the current input at once; repeating A does not release it, "
    "so a new jump needs a choice without A first. {after}"
    "While rising, choosing an input without A ends the height gain: keep A for a high jump. "
    "Short durations give precise timing; long ones cover distance with fewer choices. "
    "You cannot react until a choice ends. contact_in_frames, when present, estimates the frames until Mario's "
    "edge horizontally meets that enemy, wall or pit at the current speeds (heights and acceleration ignored); "
    "compare it with the duration you choose. ")
TIMED_AFTER = {"realtime": "If no new choice arrives within the stated frames, all buttons are then released. ",
    "paused": "Then the game pauses again; your next choice follows with no frame in between. "}
GUIDE = (
    "Harmful enemy contact kills small Mario and damages powered-up Mario; big Mario shrinks. "
    "Goomba (brown, walks): landing on top defeats it; touching its side is dangerous. You can also jump over it. "
    "Koopa (turtle): jump on it to make a shell; avoid a sliding shell. "
    "Pits: falling in kills. Plan a takeoff and a landing beyond the far bank; compare the distance to the pit "
    "plus its known width with approximate jump reach. A partially visible pit may extend farther. "
    "Pipes and stairs are solid walls: jump over them, tall ones need a running high jump. "
    "{stairs}"
    "Question blocks: hit them from below (jump under) for a coin or a mushroom; the mushroom slides right, "
    "touch it to grow. Bricks are solid for small Mario. "
    # About 128 px are visible ahead of Mario; a goomba closes in at 0.62 px/frame. Measured in 1-1.
    "Only about 8 tiles ahead are on screen. Running, an enemy appearing at the right edge reaches Mario in "
    "about 35 frames. Walking leaves about 55 frames. These are approximate examples, not fixed numbers of decisions. "
    "Walking or releasing buttons does not stop Mario immediately. Account for his current momentum and the "
    "time until another decision can take effect. "
    "Steering opposite the current horizontal motion can brake or change the "
    "landing position; it does not reverse velocity instantly. A new jump cannot rescue a fall already in progress: "
    "pressing A in midair does not cause a new takeoff. Plan where Mario will land and where enemies will be then, including enemies below him. "
    "Choose a move that remains viable through the response delay. Consider the nearest "
    "enemy, wall or pit before prioritizing forward speed. "
)
STAIRS = ("Staircases rise one tile per step: climb them step by step. A pit between two staircases is crossed "
    "by jumping from the top step of the first one. ")
LEGEND = ("Distances in pixels, 16 px = 1 tile: dx = object left edge minus Mario's left edge (positive = right, "
    "Mario is 16 px wide); dy = height of the object's bottom above Mario's feet (positive = higher). "
    "mario.jump_reach_px: approximate forward reach at the current speed under calibrated conditions; "
    "reversing direction, landing at a different height or hitting an obstacle can change it. "
    "pit_ahead includes a gap horizontally under Mario (under_mario), even while he is jumping above it. "
    "Its dx and width_px describe the visible portion; near_edge_visible/far_edge_visible say which banks are "
    "visible. If width_is_lower_bound is true, the complete width is unknown. ")
LANDING = ("move.landing estimates the frames until Mario lands back at his take-off height (in_frames) and his "
    "horizontal travel until then at the current speed (travel_px, positive = right); a higher or lower surface, "
    "a ceiling, a pit or a collision changes it, and it is absent when unknown. ")
# Jev requires sides >=256 and area >=78,400 pixels (280 squared): https://docs.typesafe.ai/images#limits
# Every model receives the same padded screenshot and note, so the context never differs between models.
MIN_IMAGE_SIDE = 280
STALL_FRAMES = 90  # about 1.5 s at 60 FPS
# Enemies worth an attention warning: close now or at response receipt, on Mario's level.
# A jump clears the first goomba when started 18-90 px before it (measured), so the warning comes slightly earlier.
CLOSE_AHEAD = (-16, 96)
# Measured in 1-1: with A held 28 frames the rise lasts 27-29 frames (87 px forward at full run)
# and reaches 64-86 px (standing to full run).
RISE_FRAMES = 28
JUMP_HEIGHT = 80
A_HELD_ON_GROUND = 4  # frames: a jump leaves the ground within a few frames of the press
SAME_LEVEL = 32


def phase(control):
    if control.get("current_move") is None:
        return "none"
    return "ended" if control.get("move_finished") else "running"


def move_state(control, response_in, speed=None):
    move = {"current": control.get("current_move"), "phase": phase(control)}
    if move["current"] is not None:
        move["frames_executed"] = control.get("move_frames", 0)
        move["starting"] = not control.get("move_finished") and move["frames_executed"] == 0
        remaining = control.get("move_remaining_frames")
        move["ends"] = ("ended" if control.get("move_finished") else
            "at next choice" if control.get("control_mode") == "buttons" and remaining is None else "at landing" if remaining is None
            else f"in {remaining} frames")
        move["then"] = ("buttons chosen by model" if control.get("control_mode") == "buttons" else
            ("no buttons" if control.get("execution_mode") == "realtime" else "game pauses for your next choice")
            if control.get("control_mode") == "timed" else "no buttons")
    landing = control.get("landing_in_frames")
    if landing is not None:
        # Calibrated on flat ground: when a jump chosen now could start, and where Mario comes down.
        move["landing"] = {"in_frames": landing}
        if speed is not None:
            move["landing"]["travel_px"] = round(speed * landing)
    move["response_in_frames"] = response_in
    return move


def predicted(item, mario_speed, frames):
    """Estimated dx at response receipt, at constant speeds; not at move start."""
    if item is None or frames is None:
        return item
    return {**item, "dx_at_response": round(item["dx"] + (item.get("speed", 0) - mario_speed) * frames)}


def contact_in(item, mario_speed, enemy=False):
    """Frames until Mario's edge meets the object horizontally at constant speeds; None if not closing.
    Information for the timed protocol, never a chosen action."""
    if item is None:
        return item
    speed = item.get("speed", 0) if enemy else 0
    ahead = item["dx"] >= 0
    gap = max((item["dx"] if ahead else -item["dx"]) - 16, 0)
    closing = (mario_speed - speed) if ahead else (speed - mario_speed)
    if (not enemy and (not ahead or item.get("under_mario"))) or closing <= 0.05:
        return item
    return {**item, "contact_in_frames": round(gap / closing)}


def ceiling_warnings(blocks, speed):
    """Blocks over the path of the rise of a jump started now: geometry only, no action is suggested."""
    reach = abs(speed) * RISE_FRAMES
    low, high = (-16, 16 + reach) if speed >= 0 else (-16 - reach, 16)
    return [f"Ceiling: {block['type']} bottom {block['dy']} px above Mario's feet at dx {block['dx']}; "
        "a jump started now rises under it and its ascent stops on contact."
        for block in blocks if block["dy"] <= JUMP_HEIGHT and low < block["dx"] < high][:2]


def close_enemies(enemies):
    """Neutral attention warnings: they say where the danger is, never which move to choose."""
    close = sorted((abs(dx), enemy["type"], dx, "estimated at response receipt" if "dx_at_response" in enemy
        else "currently") for enemy in enemies
        for dx in [enemy.get("dx_at_response", enemy["dx"])]
        if CLOSE_AHEAD[0] <= dx <= CLOSE_AHEAD[1] and abs(enemy["dy"]) <= SAME_LEVEL)
    return [f"Attention: {kind} close, dx {dx} px {when}." for _, kind, dx, when in close[:2]]


def build_payload(model, observation, png, *, frames, previous_move=None, previous_position=None, control_context=None):
    """frames, previous_move and previous_position are accepted for adapter compatibility;
    the recent moves in control_context already carry them."""
    info = observation.info
    control = control_context or {"execution_mode": "paused"}
    realtime = control["execution_mode"] == "realtime"
    # Predictive: the state is emulated at the instant the choice applies, so nothing is projected here.
    predictive = control["execution_mode"] == "predictive"
    timed = control.get("control_mode") == "timed"
    planned = timed or predictive
    direct = timed or control.get("control_mode") == "buttons"
    fps = control.get("game_fps", 60)
    scene = info.get("scene")
    recent_frames = control.get("recent_response_frames")
    response_in = (round(recent_frames) if recent_frames is not None else None) if realtime else 0
    state = {
        "mario": {**scene["mario"]} if scene else {
            "size": info.get("status", "unknown"),
            "on_ground": info.get("on_ground", "unknown")},
        "progress": scene["progress"] if scene else {"x": info.get("x_pos", "unknown")},
    }
    if scene and (not direct or scene["mario"].get("on_ground") is True):
        state["mario"]["jump_reach_px"] = jump_reach(scene["mario"]["speed"])
    if direct and control.get("jump_observation") is not None:
        state["jump_observation"] = control["jump_observation"]
    if scene:
        speed = scene["mario"]["speed"]
        horizon = response_in if realtime else None  # paused: the game waits, dx is already exact
        state["nearby"] = {
            "enemies": [predicted(enemy, speed, horizon) for enemy in scene["enemies"]],
            "obstacle_ahead": predicted(scene["obstacle_ahead"], speed, horizon),
            "pit_ahead": predicted(scene["pit_ahead"], speed, horizon),
            "blocks": [predicted(block, speed, horizon) for block in scene["blocks"]] if direct else scene["blocks"],
            "items": [predicted(item, speed, horizon) for item in scene["items"]],
        }
        if planned:
            nearby = state["nearby"]
            nearby["enemies"] = [contact_in(enemy, speed, enemy=True) for enemy in nearby["enemies"]]
            nearby["obstacle_ahead"] = contact_in(nearby["obstacle_ahead"], speed)
            nearby["pit_ahead"] = contact_in(nearby["pit_ahead"], speed)
        if direct:
            state["nearby"]["surfaces"] = [predicted(surface, speed, horizon)
                for surface in scene.get("surfaces", [])]
    state["move"] = move_state(control, response_in, scene["mario"]["speed"] if scene else None)
    if predictive:
        state["move"]["hold_frames"] = control["decision_frames"]

    if direct and "input" in control:
        state["input"] = control["input"]
    if not direct:
        state["recent_moves"] = [{"move": item["move"], "delta_x": item["delta_x"]}
            for item in control.get("recent_moves", [])[-3:]]
    wall = state["nearby"]["obstacle_ahead"] if scene else None
    warnings = close_enemies([enemy for enemy in state["nearby"]["enemies"]
        if not (planned and wall and enemy["dx"] > wall["dx"])]) if scene else []
    stalled = control.get("frames_without_progress") or 0
    if stalled >= STALL_FRAMES:
        warnings.append(f"No forward progress for {stalled} frames: Mario is not getting closer to the flag.")
    if control.get("stuck") is True:
        warnings.append("No horizontal progress despite directional input.")
    if planned and scene and scene["mario"].get("on_ground") is True:
        warnings += ceiling_warnings(scene["blocks"], scene["mario"]["speed"])
    held_a = (control.get("input") or {}).get("held_frames", {}).get("A", 0)
    if timed and info.get("on_ground") is True and held_a >= A_HELD_ON_GROUND:
        warnings.append(f"A has been held for {held_a} frames and Mario is on the ground: "
            "choosing A again cannot start a jump until an input without A is chosen.")
    time = info.get("time")
    if isinstance(time, int) and time < 100:
        warnings.append(f"Only {time} time units left.")
    if warnings:
        state["warnings"] = warnings

    if realtime:
        timing = (f"The game runs at up to {fps} FPS while you decide. After each choice is applied, one frame "
            "is executed before the next screenshot and request. The current move continues while you decide. "
            "Every new move replaces the current script at the next game tick, including during either jump of "
            "a double jump. Releasing A can shorten a jump. A new jump script starts immediately even in midair, "
            "where it cannot cause a new takeoff; it is not queued for landing. If A was held, a new jump starts "
            "with one frame releasing A. After a move ends, all buttons are released. "
            "move.response_in_frames estimates the response delay; null means no estimate yet. dx_at_response "
            "projects constant speeds; acceleration, collisions and released buttons can change it. "
            "Also consider current dx. " + LANDING)
    else:
        timing = ("The game is paused while you decide. Your move then plays to its end and you are asked again. "
            "After a move ends all buttons are released. " + LANDING)
    perception = (LEGEND + "nearby lists what is on screen: enemies, the first wall ahead (obstacle_ahead, "
        "height in tiles above Mario's ground), the first pit under or ahead of Mario, blocks within reach and items. "
        if scene else "Read enemies, walls, pits and blocks from the screenshot. ")
    criteria = control.get("choices", {name: move.description for name, move in
        (TIMED_MOVES if timed else BUTTON_MOVES if direct else MOVES).items()}).copy()
    if control.get("preview"):
        criteria = {name: text + preview_text(control["preview"][name]) for name, text in criteria.items()}
    if direct and not timed and not realtime and not predictive:
        criteria = {name: move.description.replace(" until your next choice", " for one frame")
            for name, move in BUTTON_MOVES.items()}
    if not direct and control.get("current_move") is not None and not control.get("move_finished", True):
        criteria[CONTINUE] = CONTINUE_DESCRIPTION
    instructions = ("Choose Mario's next move from the screenshot and the state. Each option is a complete "
        "move that may press several buttons over time. ") + GOAL + timing + perception + GUIDE.replace("{stairs}", "")
    if direct and predictive:
        instructions = (DIRECT_GUIDE.replace("{holding}", HOLD_PREDICTED.replace("{frames}", str(control["decision_frames"])))
            + PREDICTED_TIMING.replace("{fps}", str(fps)) + GOAL
            + GUIDE.replace("{stairs}", STAIRS).replace("through the response delay", "until your next choice")
            + RUN_UP)
        if control.get("preview"):
            instructions += PREVIEW.replace("{frames}", str(control["preview_frames"]))
        if not scene:
            instructions += "Read all geometry and enemies from the screenshot; no RAM scene is supplied. "
    elif direct:
        instructions = DIRECT_GUIDE.replace("{holding}", HOLD_TIMED.replace("{after}", TIMED_AFTER[control["execution_mode"]])
            if timed else HOLD_UNTIL_NEXT) + (
            f"The game runs at up to {fps} FPS while you decide. response_in_frames estimates the delay and "
            "dx_at_response projects distance at receipt assuming constant speeds. Consider both present and "
            "projected hazards. The next screenshot is taken after one frame of your choice. " if realtime else
            "The game is paused while you decide: the screenshot and state show exactly the instant your choice starts. "
            "Your choice then plays for its stated frames and you are asked again. " if timed else
            "The game is paused while you decide. Each choice advances exactly one frame before the next screenshot. ")
        if timed:
            instructions += GOAL + GUIDE.replace("{stairs}", STAIRS)
        if not scene:
            instructions += "Read all geometry and enemies from the screenshot; no RAM scene is supplied. "
    if png is None:
        instructions += ("No screenshot is supplied: the JSON state, read from the game memory, is the whole "
            "observation; wherever these instructions mention the screenshot, use the state. ")
    if timed and not realtime:
        questions = timed_questions(instructions, criteria)
    elif timed:
        # Realtime: one call, since a second one would double the delay before the choice applies.
        questions = {"next_action": {"type": "choice", "instructions": instructions, "criteria": {
            name: timed_effect(name) for name in criteria}}}
    else:
        questions = {"next_action": {"type": "choice", "instructions": instructions, "criteria": criteria}}
    return {
        "model": model,
        "state": [
            {"type": "text", "text": json.dumps(state, separators=(",", ":"))},
            *([] if png is None else [{"type": "image_url",
                "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}}]),
        ],
        "questions": questions,
    }


# Measured in 1-1 from standing to full run: peak height of the feet and horizontal travel.
FRAME_EFFECTS = {
    True: {2: "a hop 27-34 px high (about 2 tiles).", 4: "a hop 33-42 px high.",
        8: "a short jump 44-56 px high (about 3 tiles).", 16: "a jump 58-75 px high (about 4 tiles).",
        28: "a full-height jump 64-86 px high (4-5 tiles) with the longest reach."},
    False: {2: "a tiny correction; you choose again almost at once.", 4: "about 12 px at full run.",
        8: "about 24 px at full run."},
}


def timed_effect(name):
    action, count = name.rsplit("_", 1)
    effect = FRAME_EFFECTS[has_jump(Action(action))][int(count)]
    # Realtime: the next choice arrives only after the response delay.
    effect = effect.replace("; you choose again almost at once", "")
    return f"{BUTTON_EFFECTS[Action(action)]} Hold {count} game frames: {effect}"


def timed_questions(instructions, choices):
    """The buttons, then how long to hold them; the adapter joins the answers into one offered choice.

    frames.options lists, per buttons, the durations offered with them; only those are asked."""
    pairs = [name.rsplit("_", 1) for name in choices]
    buttons = {action: BUTTON_EFFECTS[Action(action)] for action in dict.fromkeys(action for action, _ in pairs)}
    # Wording of timed revision 1, which completed 1-1. Luna's provider can answer HTTP 502 after "noop";
    # rewording did not remove it and changed the other models' outcomes.
    options = {action: {count: f"Hold {action} for {count} game frames: "
            + FRAME_EFFECTS[has_jump(Action(action))].get(int(count), "")
        for name, count in pairs if name == action} for action in buttons}
    return {
        "buttons": {"type": "choice", "criteria": buttons, "instructions": instructions +
            "This question selects WHICH buttons to hold; a second question then selects for how long."},
        "frames": {"type": "choice", "options": options, "instructions": instructions +
            "You already selected the buttons: state.chosen_buttons. This question selects for HOW MANY game frames to "
            "hold them. With A, the duration sets the jump height: compare it with the wall, pipe or step to "
            "clear (height_tiles x 16 px) and with the pit to cross. Without A, a shorter duration lets you "
            "react sooner."},
    }


def usage_sum(*usages):
    """Add the numeric usage fields of chained calls; unknown when any call lacks usage."""
    if any(usage is None for usage in usages):
        return None
    total = {}
    for usage in usages:
        for key, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total[key] = total.get(key, 0) + value
    return total


def join_timed(buttons, frames):
    """One offered choice from the two answers; probabilities are the frames answer given the buttons."""
    move = f"{buttons.move}_{frames.move}"
    joint = ({f"{buttons.move}_{count}": round(buttons.probabilities.get(buttons.move, 0) * value, 6)
        for count, value in frames.probabilities.items()}
        if buttons.probabilities is not None and frames.probabilities is not None else None)
    confidence = (buttons.confidence * frames.confidence
        if buttons.confidence is not None and frames.confidence is not None else None)
    return Decision(move, buttons.model, buttons.request_id, buttons.provider, confidence, joint,
        usage_sum(buttons.usage, frames.usage))


class ChoiceModel(OpenRouterClient):
    """Model adapter discovered from this module; inherits shared HTTP handling."""

    model_id: str

    def build_request(self, observation, png, *, frames, previous_move=None, previous_position=None, control_context=None):
        padding = None
        if png is not None:
            with Image.open(BytesIO(png)) as image:
                source_size = image.size
                right = max(0, MIN_IMAGE_SIDE - image.width)
                bottom = max(0, MIN_IMAGE_SIDE - image.height)
                if right or bottom:
                    output = BytesIO()
                    ImageOps.expand(image, border=(0, 0, right, bottom), fill=0).save(output, format="PNG")
                    png = output.getvalue()
            padding = {"source_size": list(source_size), "sent_size": [source_size[0] + right, source_size[1] + bottom],
                "padding_right": right, "padding_bottom": bottom}
        payload = build_payload(
            self.model_id, observation, png, frames=frames,
            previous_move=previous_move, previous_position=previous_position, control_context=control_context,
        )
        if padding is not None and (padding["padding_right"] or padding["padding_bottom"]):
            for question in payload["questions"].values():
                question["instructions"] += (f" The screenshot has {padding['padding_right']} black padding columns "
                    f"on the right and {padding['padding_bottom']} black padding rows at the bottom. Ignore this "
                    "padding; game pixels and coordinates are unchanged.")
        trace = {"context": json.loads(payload["state"][0]["text"]), "questions": payload["questions"]}
        if padding is not None:
            trace["image_preprocessing"] = padding
        return DecisionRequest(payload, trace)

    async def exchange(self, payload):
        questions = payload["questions"]
        if "buttons" not in questions:
            return await super().exchange(payload)
        # Two model choices in sequence: the duration is chosen knowing the chosen buttons.
        first = {**payload, "questions": {"buttons": questions["buttons"]}}
        buttons = parse_decision(await self.post(first), questions["buttons"]["criteria"], question="buttons")
        # The chosen buttons travel in the state: inside the instructions, "noop" made Luna's provider
        # answer HTTP 502 in several reproduced states.
        state = json.loads(payload["state"][0]["text"])
        state["chosen_buttons"] = buttons.move
        template = questions["frames"]
        frames_question = {"type": "choice", "instructions": template["instructions"],
            "criteria": template["options"][buttons.move]}
        second = {**payload, "questions": {"frames": frames_question},
            "state": [{"type": "text", "text": json.dumps(state, separators=(",", ":"))}, *payload["state"][1:]]}
        frames = parse_decision(await self.post(second), frames_question["criteria"], question="frames")
        return join_timed(buttons, frames)
