"""Trace model sessions without persisting authentication headers."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from app.config import PROJECT_ROOT
from app.moves import MOVES

RESULTS_VERSION = 4


class SessionLog:
    def __init__(self, config, *, root=None):
        root = Path(root) if root is not None else PROJECT_ROOT / "runs"
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:12]
        self.path = root / name
        self.path.mkdir(parents=True)
        self.save_screenshots = config.save_screenshots
        if self.save_screenshots:
            (self.path / "screenshots").mkdir()
        self._write("config.json", {**asdict(config), "results_version": RESULTS_VERSION,
            "protocol": "openrouter-choice-scene-v4", "game_paused_during_request": config.execution_mode == "paused",
            "fps_target": 60, "clock": "perf_counter", "percentile_method": "nearest-rank",
            "moves": {name: move.summary() for name, move in MOVES.items()}})
        self._events = (self.path / "events.jsonl").open("a", encoding="utf-8")

    def _write(self, name, data):
        (self.path / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def event(self, kind, **data):
        self._events.write(json.dumps({"event": kind, **data}, ensure_ascii=False) + "\n")
        self._events.flush()

    def screenshot(self, index, png):
        if not self.save_screenshots:
            return None
        relative = f"screenshots/{index:06d}.png"
        (self.path / relative).write_bytes(png)
        return relative

    def finish(self, **summary):
        self._write("summary.json", {"results_version": RESULTS_VERSION, **summary})

    def close(self):
        self._events.close()
