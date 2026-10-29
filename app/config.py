"""CLI configuration, validated before opening the emulator."""

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

from app.models import get_model_class
from app.models.gpt_luna import MODEL_ID as DEFAULT_MODEL

ENVIRONMENT_ID = "SuperMarioBros-1-1-v0"
DISPLAY_FPS = 60
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def positive_seconds(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("serve un numero positivo di secondi") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("serve un numero positivo di secondi")
    return number


def openrouter_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ValueError("OPENROUTER_API_KEY mancante: configurarla nell'ambiente o nel file .env")
    return key


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("serve un numero intero positivo") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("serve un numero intero positivo")
    return number


@dataclass(frozen=True)
class Config:
    mode: str = "model"
    headless: bool = False
    seed: int = 123
    episodes: int = 1
    max_frames: int = 3600
    model: str = DEFAULT_MODEL
    request_timeout: float = 10.0
    execution_mode: str = "realtime"
    max_decision_frames: int = 120
    max_episode_seconds: float = 60.0
    save_screenshots: bool = False
    game_fps: int = DISPLAY_FPS
    scene: bool = True
    image: bool = True
    control_mode: str = "buttons"


def parse_config(argv: list[str] | None = None) -> Config:
    # Read the model without importing private credentials into the environment.
    file_model = dotenv_values(PROJECT_ROOT / ".env").get("OPENROUTER_MODEL")
    model = os.environ.get("OPENROUTER_MODEL", file_model or DEFAULT_MODEL).strip()
    parser = argparse.ArgumentParser(description="SuperMAIrio: modello, demo e tastiera nel livello 1-1")
    parser.add_argument("--mode", choices=("model", "demo", "manual"), default="model")
    parser.add_argument("--headless", action="store_true", help="modello o demo senza finestra")
    parser.add_argument("--control-mode", choices=("moves", "buttons", "timed"), default=Config.control_mode,
        help="modello: mosse calibrate, pulsanti mantenuti fino alla prossima scelta oppure pulsanti con durata scelta dal modello")
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--episodes", type=positive_int, default=1, help="numero di tentativi del modello o della demo")
    parser.add_argument("--max-frames", type=positive_int, default=3600, help="limite per episodio")
    parser.add_argument("--model", default=model, help="nome del modulo o identificativo OpenRouter; precedenza: CLI, OPENROUTER_MODEL (ambiente/.env), GPT Luna")
    parser.add_argument("--request-timeout", type=positive_seconds, default=10.0, help="budget totale della richiesta in secondi")
    parser.add_argument("--execution-mode", choices=("realtime", "paused"), default="realtime", help="gioco continuo durante le richieste oppure fermo a ogni richiesta, a turni (solo modello)")
    parser.add_argument("--max-decision-frames", type=positive_int, default=120, help="età massima dell'osservazione alla ricezione della risposta, in frame di gioco (realtime, default: 120, 2 s a 60 FPS)")
    parser.add_argument("--max-episode-seconds", type=positive_seconds, default=60.0, help="limite reale per tentativo (realtime)")
    parser.add_argument("--save-screenshots", action="store_true", help="conserva le immagini inviate al modello")
    parser.add_argument("--game-fps", type=positive_int, default=DISPLAY_FPS, help=f"realtime: velocità del gioco in frame al secondo (massimo {DISPLAY_FPS})")
    parser.add_argument("--scene", action=argparse.BooleanOptionalAction, default=True, help="inviare al modello la scena letta dalla RAM (nemici, ostacoli, buche, blocchi) oltre allo screenshot")
    parser.add_argument("--image", action=argparse.BooleanOptionalAction, default=True, help="inviare lo screenshot al modello; --no-image lascia solo la scena dalla RAM e riduce il carico della richiesta")
    args = parser.parse_args(argv)
    if not args.image and not args.scene:
        parser.error("--no-image richiede la scena: senza entrambe il modello non riceve osservazioni")
    if args.game_fps > DISPLAY_FPS:
        parser.error(f"--game-fps non può superare {DISPLAY_FPS}")
    if args.mode == "manual" and args.headless:
        parser.error("la modalità manuale richiede una finestra")
    if not args.model.strip():
        parser.error("--model non può essere vuoto")
    if args.mode == "model":
        try:
            get_model_class(args.model)
        except ValueError as exc:
            parser.error(str(exc))
    return Config(**vars(args))
