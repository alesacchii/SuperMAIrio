"""Trace model sessions without persisting authentication headers."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from app.config import DISPLAY_FPS, PROJECT_ROOT
from app.moves import MOVES
from app.control import (BUTTON_MOVES, DIRECT_PROMPT_REVISION, PREDICTIVE_MOVES, PREDICTIVE_PROMPT_REVISION,
    TIMED_MOVES, TIMED_PROMPT_REVISION)

RESULTS_VERSION = 6


class SessionLog:
    def __init__(self, config, *, root=None):
        root = Path(root) if root is not None else PROJECT_ROOT / "runs"
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:12]
        self.path = root / name
        self.path.mkdir(parents=True)
        self.save_screenshots = config.save_screenshots
        if self.save_screenshots:
            (self.path / "screenshots").mkdir()
        direct, timed = config.control_mode == "buttons", config.control_mode == "timed"
        predictive = config.execution_mode == "predictive"
        self._write("config.json", {**asdict(config), "results_version": RESULTS_VERSION,
            "prompt_revision": PREDICTIVE_PROMPT_REVISION if direct and predictive else DIRECT_PROMPT_REVISION if direct else TIMED_PROMPT_REVISION if timed else 5,
            "protocol": "choice-buttons-predictive-v1" if direct and predictive else "choice-buttons-v1" if direct else "choice-timed-buttons-v1" if timed else "openrouter-choice-scene-v5",
            "game_paused_during_request": config.execution_mode == "paused",
            "fps_target": config.game_fps if config.execution_mode in ("realtime", "predictive") else DISPLAY_FPS,
            "clock": "perf_counter", "percentile_method": "nearest-rank",
            "moves": ({name: move.summary() for name, move in PREDICTIVE_MOVES.items()} if direct and predictive else
                {name: {"action": name, "duration": "one_frame" if config.execution_mode == "paused"
                else "until_next_choice"} for name in BUTTON_MOVES} if direct else
                {name: move.summary() for name, move in (TIMED_MOVES if timed else MOVES).items()})})
        self._events = (self.path / "events.jsonl").open("a", encoding="utf-8")

        self._frames = (self.path / "frames.jsonl").open("a", encoding="utf-8")

    def _write(self, name, data):
        (self.path / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def event(self, kind, **data):
        self._events.write(json.dumps({"event": kind, **data}, ensure_ascii=False) + "\n")
        self._events.flush()

    def frame(self, **data):
        self._frames.write(json.dumps({"event": "frame", **data}, ensure_ascii=False) + "\n")
        self._frames.flush()

    def screenshot(self, index, png):
        if not self.save_screenshots or png is None:
            return None
        relative = f"screenshots/{index:06d}.png"
        (self.path / relative).write_bytes(png)
        return relative

    def finish(self, **summary):
        self._write("summary.json", {"results_version": RESULTS_VERSION, **summary})

    def close(self):
        self._events.close()
        self._frames.close()
