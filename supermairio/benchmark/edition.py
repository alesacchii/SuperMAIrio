"""Collect a versioned benchmark edition, with the session logs as its journal."""

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tomllib
from zipfile import BadZipFile

from supermairio.config import ENVIRONMENT_ID, PACKAGE_ROOT, PROJECT_ROOT, TRACKS, environment, validate_endpoint
from supermairio.agent.client import DecisionError
from supermairio.runtime.session import session_config

BLOCKS = ((10, 13), (20, 26), (30, 40))
# Session keys stay "predictive" and "paused": they name the recorded sessions of every edition.
MODES = {
    "predictive": replace(TRACKS["realtime"], headless=True),
    "paused": replace(TRACKS["turn-based"], headless=True),
}
OUTCOMES = {"completed", "death", "frame_limit", "wall_limit"}


@dataclass(frozen=True)
class Participant:
    name: str
    model: str
    endpoint: str
    key: str | None = field(repr=False, compare=False)

    def public(self):
        return {"name": self.name, "model": self.model, "endpoint": self.endpoint}


def read_participants(path, env):
    rows = tomllib.loads(path.read_text(encoding="utf-8")).get("participants")
    if not isinstance(rows, list) or not rows:
        raise ValueError("The TOML file must list at least one participant")
    participants = []
    names = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) not in ({"name", "model"}, {"name", "env_prefix"})
                or not all(isinstance(value, str) and value.strip() for value in row.values())):
            raise ValueError("Each participant needs name and one of model or env_prefix")
        name = row["name"].strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name.casefold() in names:
            raise ValueError("Participant names must be unique and use ASCII letters, digits, dot, hyphen or underscore")
        names.add(name.casefold())
        if "env_prefix" in row:
            prefix = row["env_prefix"]
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", prefix):
                raise ValueError(f"Invalid environment prefix for {name}")
            model = env.get(f"{prefix}_MODEL", "").strip()
            if not model:
                raise ValueError(f"Set {prefix}_MODEL for {name}")
        else:
            model = row["model"].strip()
            prefix = "SUPERMAIRIO"
        url = env.get(f"{prefix}_ENDPOINT", "").strip()
        if not url:
            raise ValueError(f"Set {prefix}_ENDPOINT for {name}")
        endpoint = validate_endpoint(url)
        key = env.get(f"{prefix}_API_KEY", "").strip() or None
        participants.append(Participant(name, model, endpoint, key))
    return participants


def schedule(size):
    order = list(range(size))
    for block, (target, cap) in enumerate(BLOCKS, 1):
        if block % 2:
            indices, modes = order[block // 2:] + order[:block // 2], MODES
        else:
            indices, modes = order[::-1], reversed(MODES)
        modes = tuple(modes)
        for index in indices:
            for mode in modes:
                yield block, index, mode, target, cap


def edition_metadata(participants):
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
        text=True, check=True).stdout.strip()
    sources = sorted([*PACKAGE_ROOT.rglob("*.py"), PROJECT_ROOT / "pyproject.toml", PROJECT_ROOT / "uv.lock",
        PROJECT_ROOT / ".python-version"])
    digest = sha256()
    for path in sources:
        digest.update(path.relative_to(PROJECT_ROOT).as_posix().encode() + b"\0" + sha256(path.read_bytes()).digest())
    return {"version": 1, "commit": commit, "source_sha256": digest.hexdigest(),
        "uv_lock_sha256": sha256((PROJECT_ROOT / "uv.lock").read_bytes()).hexdigest(),
        "environment_id": ENVIRONMENT_ID, "python": platform.python_version(), "os": platform.platform(),
        "cpu": os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor() or platform.machine(),
        "logical_cpus": os.cpu_count(), "modes": {name: session_config(config) for name, config in MODES.items()},
        "participants": [participant.public() for participant in participants],
        "schedule": list(map(list, schedule(len(participants))))}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_log(path, *, recover=False):
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if recover and not line.endswith("\n"):
                    break  # A process killed during a write can leave an incomplete final record.
                yield json.loads(line)


@contextmanager
def edition_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+b") as lock:
        try:
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("This edition is already in use") from exc
        yield  # Closing the file releases the lock, including after a crash.


def session_progress(path):
    started, ended = set(), {}
    for event in read_log(path / "events.jsonl", recover=True):
        if event["event"] == "episode_started":
            started.add(event["episode"])
        elif event["event"] == "episode_end":
            ended[event["episode"]] = event
    return started | ended.keys(), ended


def collect(directory, participants, metadata, *, through_block=len(BLOCKS), run_session=None):
    with edition_lock(directory):
        manifest = directory / "edition.json"
        if manifest.exists():
            previous = read_json(manifest)
            if {key: value for key, value in previous.items() if key != "created_at"} != metadata:
                raise ValueError("Schedule, code or environment changed: use a new edition directory")
        else:
            temporary = manifest.with_suffix(".tmp")
            temporary.write_text(json.dumps({**metadata, "created_at": utc_now()}, indent=2), encoding="utf-8")
            temporary.replace(manifest)
        runner = run_session or play_session
        for block, index, mode, target, cap in metadata["schedule"]:
            if block > through_block:
                break
            participant = participants[index]
            base = directory / "sessions" / f"{index:03d}-{mode}"
            paths = sorted(base.glob("[1-3]-*"))
            progress = [session_progress(path) for path in paths if int(path.name[0]) <= block]
            started = sum(len(attempts) for attempts, _ in progress)
            finished = sum(episode["reason"] in OUTCOMES for _, episodes in progress for episode in episodes.values())
            sequence = 1 + max((int(path.name.split("-")[1]) for path in paths if int(path.name[0]) == block), default=0)
            if finished > target or started > cap:
                raise ValueError(f"Log beyond the limit for {participant.name}, {mode}")
            while (episodes := min(target - finished, cap - started)) > 0:
                path = base / f"{block}-{sequence:03d}"
                config = replace(MODES[mode], model=participant.model, endpoint=participant.endpoint, episodes=episodes)
                try:
                    runner(config, participant, path)
                except DecisionError:
                    # Keep the interrupted episode and continue with the next slot.
                    if not session_progress(path)[0]:
                        raise
                attempts, results = session_progress(path)
                if not attempts:
                    raise ValueError(f"Session without attempts for {participant.name}, {mode}")
                started += len(attempts)
                finished += sum(episode["reason"] in OUTCOMES for episode in results.values())
                sequence += 1


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def play_session(config, participant, path):
    from supermairio.game.emulator import MarioGame
    from supermairio.runtime.loop import run_model
    from supermairio.runtime.predictive import SLOW_EMULATION_FPS, run_predictive
    from supermairio.runtime.session import SessionLog

    options = {"game_factory": MarioGame, "key_provider": lambda: participant.key,
        "log_factory": lambda settings: SessionLog(settings, path=path)}
    if config.execution_mode == "predictive":
        run_predictive(config, minimum_throughput=SLOW_EMULATION_FPS, **options)
    else:
        run_model(config, **options)


def add_arguments(parser):
    commands = parser.add_subparsers(dest="bench_command", required=True, metavar="COMMAND")
    run = commands.add_parser("run", help="print the schedule, or collect an edition with --live",
        description="Print the schedule. With --live, play it and record every session; rerun to resume.")
    run.add_argument("--participants", type=Path, default=PROJECT_ROOT / "benchmark.toml",
        help="participants file (default: benchmark.toml)")
    run.add_argument("--edition", type=Path, default=PROJECT_ROOT / "runs" / "benchmark-v1",
        help="edition directory (default: runs/benchmark-v1)")
    run.add_argument("--through-block", type=int, choices=range(1, len(BLOCKS) + 1), default=len(BLOCKS),
        help="stop after this block")
    run.add_argument("--live", action="store_true", help="send requests to the endpoints; may incur costs")
    report = commands.add_parser("report", help="write the leaderboard, CSV, charts and archive",
        description="Write README.md, attempts.csv, SVG charts and edition.zip for an edition.")
    report.add_argument("edition", type=Path)
    report.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="replay the recorded inputs of an edition or its ZIP archive",
        description="Replay every recorded attempt offline and check position, reward and outcome.")
    verify.add_argument("edition", type=Path)


def run(args):
    try:
        if args.bench_command == "run":
            participants = read_participants(args.participants, environment())
            for block, index, mode, target, cap in schedule(len(participants)):
                if block > args.through_block:
                    break
                entry = participants[index]
                print(f"Block {block} | {mode} | {entry.name} | {entry.model} @ {entry.endpoint} | "
                    f"{target} finished games, at most {cap} starts")
            if args.live:
                collect(args.edition, participants, edition_metadata(participants), through_block=args.through_block)
            else:
                print("Dry run: no request sent. Add --live to collect the edition.")
        else:
            from supermairio.benchmark.report import make_report, verify_edition

            if args.bench_command == "report":
                make_report(args.edition, args.output)
            else:
                print(f"Verified attempts: {verify_edition(args.edition)}")
    except KeyboardInterrupt:
        print("Collection interrupted. Run the same command again to resume.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, BadZipFile, subprocess.CalledProcessError) as exc:
        print(f"Benchmark: {exc}", file=sys.stderr)
        return 1
    return 0
