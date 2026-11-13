"""Session configuration, validated before the emulator opens."""

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ENVIRONMENT_ID = "SuperMarioBros-1-1-v0"
DISPLAY_FPS = 60
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
# Defaults of `play`: the best configuration measured so far, identical to the real-time track.
BEST_EXECUTION_MODE = "predictive"
BEST_CHOICE_PREVIEW = 30
BEST_PARALLEL_REQUESTS = 2


def positive_seconds(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive number of seconds") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("expected a positive number of seconds")
    return number


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def environment() -> dict[str, str]:
    """`.env` values, overridden by the process environment."""
    return {**{name: value for name, value in dotenv_values(PROJECT_ROOT / ".env").items()
        if value is not None}, **os.environ}


def validate_endpoint(endpoint: str) -> str:
    try:
        parts = urlsplit(endpoint)
        port = parts.port
        if (parts.scheme in ("http", "https") and parts.hostname and parts.username is None
                and (port is None or port > 0) and not any(char.isspace() or ord(char) < 32 for char in endpoint)
                and not any(char in endpoint for char in "?#\\")):
            return endpoint
    except ValueError:
        pass
    raise ValueError("Invalid Decisions endpoint: use an absolute HTTP(S) URL without credentials, query or fragment")


def decisions_key(endpoint: str | None) -> str | None:
    env = environment()
    if endpoint and env.get("SUPERMAIRIO_ENDPOINT", "").strip() == endpoint:
        return env.get("SUPERMAIRIO_API_KEY", "").strip() or None
    return None


def validate_model_connection(model: str | None, endpoint: str | None) -> str:
    if not model or not model.strip():
        raise ValueError("Set SUPERMAIRIO_MODEL or pass --model")
    if not endpoint:
        raise ValueError("Set SUPERMAIRIO_ENDPOINT to the full Decisions API URL")
    return validate_endpoint(endpoint)


@dataclass(frozen=True)
class Config:
    mode: str = "model"
    headless: bool = False
    seed: int = 123
    episodes: int = 1
    max_frames: int = 3600
    model: str | None = None
    request_timeout: float = 10.0
    execution_mode: str = "realtime"
    max_decision_frames: int = 120
    max_episode_seconds: float = 60.0
    save_screenshots: bool = False
    game_fps: int = DISPLAY_FPS
    scene: bool = True
    image: bool = True
    control_mode: str = "buttons"
    decision_frames: int = 0
    parallel_requests: int = 1
    speculative_width: int = 0
    choice_preview: int = 0
    endpoint: str | None = None


# The two benchmark tracks. The benchmark and `play --track` share these definitions.
TRACKS = {
    "realtime": Config(image=False, execution_mode="predictive", choice_preview=BEST_CHOICE_PREVIEW,
        parallel_requests=BEST_PARALLEL_REQUESTS),
    "turn-based": Config(image=False, execution_mode="paused", control_mode="timed"),
}
# Options that change what a track measures; `--track` rejects them.
PROTOCOL_OPTIONS = ("seed", "max_frames", "request_timeout", "execution_mode", "max_decision_frames",
    "max_episode_seconds", "save_screenshots", "game_fps", "scene", "image", "control_mode", "decision_frames",
    "parallel_requests", "speculative_width", "choice_preview")


def add_play_arguments(parser: argparse.ArgumentParser, env: dict[str, str]) -> None:
    model = env.get("SUPERMAIRIO_MODEL", "").strip() or None
    general = parser.add_argument_group("session")
    general.add_argument("--mode", choices=("model", "demo", "manual"), default="model",
        help="model: the configured model plays (default); demo: a fixed move sequence; manual: keyboard")
    general.add_argument("--headless", action="store_true", help="no window (model and demo)")
    general.add_argument("--episodes", type=positive_int, default=1, help="number of attempts (model and demo)")
    general.add_argument("--seed", type=int, default=123, help="environment reset seed (default: 123)")
    general.add_argument("--max-frames", type=positive_int, default=3600, help="frame limit per attempt (default: 3600)")
    general.add_argument("--max-episode-seconds", type=positive_seconds, default=60.0,
        help="wall-clock limit per attempt in realtime and predictive (default: 60)")
    general.add_argument("--save-screenshots", action="store_true",
        help="keep the images sent to the model in runs/<session>/screenshots/")

    request = parser.add_argument_group("model and requests")
    request.add_argument("--track", choices=tuple(TRACKS),
        help="play exactly as in one benchmark track; rejects options that change seed, limits, timeout, protocol or observation")
    request.add_argument("--model", default=model, help="Decisions model ID (default: SUPERMAIRIO_MODEL)")
    request.add_argument("--request-timeout", type=positive_seconds, default=10.0,
        help="budget for a whole decision request in seconds (default: 10)")
    request.add_argument("--execution-mode", choices=("predictive", "paused", "realtime"),
        help="predictive: the game never stops and the model sees the state where its choice applies (default); "
        "paused: turn-based; realtime: the game keeps running with no prediction (experimental). "
        "Default: predictive with buttons, realtime otherwise")
    request.add_argument("--control-mode", choices=("buttons", "timed", "moves"), default=Config.control_mode,
        help="buttons: held until the next choice (default); timed: buttons and duration; moves: calibrated "
        "move scripts (experimental)")

    observation = parser.add_argument_group("observation")
    observation.add_argument("--scene", action=argparse.BooleanOptionalAction, default=True,
        help="send the scene read from the NES RAM: enemies, obstacles, pits, blocks (default: on)")
    observation.add_argument("--image", action=argparse.BooleanOptionalAction,
        help="send the screenshot (default: off in predictive, on otherwise)")

    predictive = parser.add_argument_group("predictive mode")
    predictive.add_argument("--choice-preview", type=int, metavar="FRAMES",
        help=f"emulated outcome of holding each option for FRAMES frames, appended to its description; "
        f"0 disables (default: {BEST_CHOICE_PREVIEW})")
    predictive.add_argument("--parallel-requests", type=positive_int,
        help=f"identical copies of each request sent in parallel; the first answer wins, cost scales with N "
        f"(default: {BEST_PARALLEL_REQUESTS})")
    predictive.add_argument("--decision-frames", type=int, default=0,
        help="minimum frames between two choices, extended when the measured latency requires it (0: minimum 8)")
    predictive.add_argument("--speculative-width", type=int, default=0, choices=range(0, 11), metavar="0-10",
        help="experimental: requests sent in advance for the next choice, one per likely answer in flight")

    realtime = parser.add_argument_group("realtime mode (experimental)")
    realtime.add_argument("--game-fps", type=positive_int, default=DISPLAY_FPS,
        help=f"game speed in realtime and predictive (max {DISPLAY_FPS})")
    realtime.add_argument("--max-decision-frames", type=positive_int, default=120,
        help="maximum observation age, in game frames, when an answer arrives (default: 120)")


def play_config(parser: argparse.ArgumentParser, args: argparse.Namespace, env: dict[str, str]) -> Config:
    """Resolve defaults that depend on other options, then reject incompatible combinations."""
    options = vars(args).copy()
    track = options.pop("track", None)
    for name in ("command", "handler"):
        options.pop(name, None)
    if track is not None:
        changed = [name for name in PROTOCOL_OPTIONS if options[name] != parser.get_default(name)]
        if changed:
            flags = ", ".join("--" + name.replace("_", "-") for name in changed)
            parser.error(f"--track {track} fixes the protocol: remove {flags}")
        selected = TRACKS[track]
        options.update({name: getattr(selected, name) for name in PROTOCOL_OPTIONS})
    args = argparse.Namespace(**options)
    if args.image is False and not args.scene:
        parser.error("--no-image requires the scene: without both the model receives no observation")
    if args.execution_mode is None:
        args.execution_mode = BEST_EXECUTION_MODE if args.control_mode == "buttons" else Config.execution_mode
    # Options left unset follow the execution mode: only predictive uses the best values.
    predictive = args.execution_mode == "predictive"
    if args.choice_preview is None:
        args.choice_preview = BEST_CHOICE_PREVIEW if predictive else Config.choice_preview
    if args.parallel_requests is None:
        args.parallel_requests = BEST_PARALLEL_REQUESTS if predictive else Config.parallel_requests
    if args.image is None:
        # Without the RAM scene the screenshot is the only observation; saving screenshots needs one.
        args.image = not predictive or not args.scene or args.save_screenshots
    if args.execution_mode == "predictive" and args.control_mode != "buttons":
        parser.error("--execution-mode predictive requires --control-mode buttons")
    if args.speculative_width and args.execution_mode != "predictive":
        parser.error("--speculative-width requires --execution-mode predictive")
    if args.parallel_requests > 1 and args.execution_mode != "predictive":
        parser.error("--parallel-requests requires --execution-mode predictive")
    if args.choice_preview and args.execution_mode != "predictive":
        parser.error("--choice-preview requires --execution-mode predictive")
    if args.choice_preview < 0:
        parser.error("--choice-preview cannot be negative")
    if args.decision_frames < 0:
        parser.error("--decision-frames cannot be negative")
    if args.game_fps > DISPLAY_FPS:
        parser.error(f"--game-fps cannot exceed {DISPLAY_FPS}")
    if args.mode == "manual" and args.headless:
        parser.error("manual mode needs a window")
    args.endpoint = None
    if args.mode == "model":
        try:
            args.endpoint = validate_model_connection(args.model, env.get("SUPERMAIRIO_ENDPOINT", "").strip())
        except ValueError as exc:
            parser.error(str(exc))
    return Config(**vars(args))


def play_parser(env: dict[str, str], parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(prog="supermairio play")
    parser.description = ("Play level 1-1 with the configured model, the demo or the keyboard. "
        "Defaults match the real-time benchmark track.")
    add_play_arguments(parser, env)
    return parser


def parse_config(argv: list[str] | None = None) -> Config:
    env = environment()
    parser = play_parser(env)
    return play_config(parser, parser.parse_args(argv), env)
