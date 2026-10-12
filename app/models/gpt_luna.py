"""GPT Luna multimodal Choice controller, served by OpenRouter Decisions."""

import base64
import json

from app.contracts import Action, BUTTONS, DecisionRequest
from app.moves import CONTINUE, MOVES, jump_reach
from app.openrouter import OpenRouterClient

MODEL_ID = "openai/gpt-6-luna-decisions"
GUIDE = (
    "Goal: reach the flagpole at the end of Super Mario Bros level 1-1 (progress.percent). "
    "Priorities: stay alive, then move right, then grab a mushroom; coins only give points. "
    "Small Mario dies on any enemy contact; big Mario shrinks instead. "
    "Goomba (brown, walks): jump on top to defeat it, or jump over it; touching its side kills. "
    "Koopa (turtle): jump on it to make a shell; avoid a sliding shell. "
    "Pits: falling in kills; clear them with a running high jump started close to the edge. "
    "Pipes and stairs are solid walls: jump over them, tall ones need a running high jump. "
    "Question blocks: hit them from below (jump under) for a coin or a mushroom; the mushroom slides right, "
    "touch it to grow. Bricks are solid for small Mario. "
    # About 128 px are visible ahead of Mario; a goomba closes in at 0.62 px/frame. Measured in 1-1.
    "Only about 8 tiles ahead are on screen. Running, an enemy appearing at the right edge reaches Mario in "
    "about 35 frames: about one decision. Walking leaves about 55 frames: about three decisions. "
)
LEGEND = ("Distances in pixels, 16 px = 1 tile: dx = object left edge minus Mario's left edge (positive = right, "
    "Mario is 16 px wide); dy = height of the object's bottom above Mario's feet (positive = higher). "
    "mario.jump_reach_px: forward distance each jump covers at the current speed. ")
# Enemies worth an attention warning: ahead at most this far when the move starts, on Mario's level.
# A jump clears the first goomba when started 18-90 px before it (measured), so the warning comes slightly earlier.
CLOSE_AHEAD = (-16, 96)
SAME_LEVEL = 32


def phase(control):
    if control.get("current_move") is None:
        return "none"
    if control.get("move_committed"):
        return "committed"
    return "ended" if control.get("move_finished") else "running"


def move_state(control, starts_in):
    move = {"current": control.get("current_move"), "phase": phase(control)}
    if move["current"] is not None:
        remaining = control.get("move_remaining_frames")
        move["ends"] = ("ended" if control.get("move_finished") else "at landing" if remaining is None
            else f"in {remaining} frames")
        buttons = BUTTONS[Action(control.get("tail_action", "noop"))]
        # What Mario does if no new move is chosen: the reason to plan the next one now.
        move["then"] = "no buttons" if buttons == ("NOOP",) else "holds " + "+".join(buttons)
    move["your_move_starts_in_frames"] = starts_in
    return move


def predicted(item, mario_speed, frames):
    """dx when the chosen move starts, at constant speeds; walls and pits do not move."""
    if item is None or frames is None:
        return item
    return {**item, "dx_at_move_start": round(item["dx"] + (item.get("speed", 0) - mario_speed) * frames)}


def close_enemies(enemies):
    """Neutral attention warnings: they say where the danger is, never which move to choose."""
    close = sorted((abs(dx), enemy["type"], dx) for enemy in enemies
        for dx in [enemy.get("dx_at_move_start", enemy["dx"])]
        if CLOSE_AHEAD[0] <= dx <= CLOSE_AHEAD[1] and abs(enemy["dy"]) <= SAME_LEVEL)
    return [f"Attention: {kind} close, dx {dx} px when your move starts." for _, kind, dx in close[:2]]


def build_payload(model, observation, png, *, frames, previous_move=None, previous_position=None, control_context=None):
    """frames, previous_move and previous_position are accepted for adapter compatibility;
    the recent moves in control_context already carry them."""
    info = observation.info
    control = control_context or {"execution_mode": "paused"}
    realtime = control["execution_mode"] == "realtime"
    fps = control.get("game_fps", 60)
    scene = info.get("scene")
    latency = control.get("recent_latency_seconds")
    starts_in = (round(latency * fps) if latency is not None else None) if realtime else 0
    state = {
        "mario": {**scene["mario"], "jump_reach_px": jump_reach(scene["mario"]["speed"])} if scene else {
            "size": info.get("status", "unknown"),
            "on_ground": info.get("on_ground", "unknown")},
        "progress": scene["progress"] if scene else {"x": info.get("x_pos", "unknown")},
    }
    if scene:
        speed = scene["mario"]["speed"]
        horizon = starts_in if realtime else None  # paused: the game waits, dx is already exact
        state["nearby"] = {
            "enemies": [predicted(enemy, speed, horizon) for enemy in scene["enemies"]],
            "obstacle_ahead": predicted(scene["obstacle_ahead"], speed, horizon),
            "pit_ahead": predicted(scene["pit_ahead"], speed, horizon),
            "blocks": scene["blocks"],
            "items": [predicted(item, speed, horizon) for item in scene["items"]],
        }
    state["move"] = move_state(control, starts_in)
    state["recent_moves"] = [{"move": item["move"], "delta_x": item["delta_x"]}
        for item in control.get("recent_moves", [])[-3:]]
    warnings = close_enemies(state["nearby"]["enemies"]) if scene else []
    if control.get("stuck") is True:
        warnings.append("No horizontal progress despite moving: change strategy, e.g. a running high jump over the wall.")
    time = info.get("time")
    if isinstance(time, int) and time < 100:
        warnings.append(f"Only {time} time units left: hurry right.")
    if warnings:
        state["warnings"] = warnings

    if realtime:
        timing = (f"The game runs at {fps} FPS while you decide: your move starts move.your_move_starts_in_frames "
            "frames after this screenshot. dx_at_move_start predicts each distance at that moment (constant "
            "speeds): decide on it, not on dx. "
            "You are asked again as soon as your move starts. Jumps are never cut short: a move chosen during a "
            "committed jump starts when it ends, and a new jump starts at the landing. "
            f"{CONTINUE} plans nothing: when the current move ends (move.ends) Mario keeps doing move.then until "
            "your next move. To act right after the current move, e.g. jump a pit at the landing, choose that "
            "move now: it starts at the landing. ")
    else:
        timing = ("The game is paused while you decide. Your move then plays to its end and you are asked again. "
            f"{CONTINUE} repeats the previous move. ")
    perception = (LEGEND + "nearby lists what is on screen: enemies, the first wall ahead (obstacle_ahead, "
        "height in tiles above Mario's ground), the first pit ahead, blocks within reach and items. "
        if scene else "Read enemies, walls, pits and blocks from the screenshot. ")
    criteria = {name: move.description for name, move in MOVES.items()}
    criteria[CONTINUE] = ("Plan nothing new: the current move goes on (an ended one is repeated); "
        "afterwards Mario keeps doing move.then.")
    return {
        "model": model,
        "state": [
            {"type": "text", "text": json.dumps(state, separators=(",", ":"))},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}},
        ],
        "questions": {"next_action": {
            "type": "choice",
            "instructions": "Choose Mario's next move from the screenshot and the state. Each option is a complete "
                "move that may press several buttons over time. " + GUIDE + perception + timing,
            "criteria": criteria,
        }},
    }


class Model(OpenRouterClient):
    """Model adapter discovered from this module; inherits shared HTTP handling."""

    model_id = MODEL_ID

    def build_request(self, observation, png, *, frames, previous_move=None, previous_position=None, control_context=None):
        payload = build_payload(
            self.model_id, observation, png, frames=frames,
            previous_move=previous_move, previous_position=previous_position, control_context=control_context,
        )
        return DecisionRequest(payload, {
            "context": json.loads(payload["state"][0]["text"]),
            "questions": payload["questions"],
        })
