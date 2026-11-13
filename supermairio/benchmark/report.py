"""Generate the public report and verify its recorded emulator inputs offline."""

from contextlib import contextmanager
import csv
from dataclasses import dataclass
from html import escape
from math import ceil, floor, log10, sqrt
from pathlib import Path, PurePosixPath
import re
from statistics import median
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from supermairio.benchmark.edition import BLOCKS, MODES, OUTCOMES, read_json, read_log
from supermairio.runtime.metrics import distribution, numeric

TITLES = {"predictive": "Real-time track (60 FPS)", "paused": "Turn-based track"}
TARGET = BLOCKS[-1][0]
FILES = ("config.json", "summary.json", "events.jsonl", "frames.jsonl")
CSV_FIELDS = ("participant", "mode", "model", "endpoint", "provider", "date", "block", "session",
    "episode", "outcome", "reason", "frames", "max_x_pos", "latency_median_s", "latency_p95_s",
    "known_cost_usd", "cost_known_responses", "received_responses", "effective_fps", "choices", "late_choices")


@dataclass
class Attempt:
    row: dict
    latencies: list
    summary: dict | None


def session_paths(edition, metadata):
    for index, participant in enumerate(metadata["participants"]):
        for mode in MODES:
            for path in sorted((edition / "sessions" / f"{index:03d}-{mode}").glob("[1-3]-*")):
                if (path / "config.json").is_file():
                    yield participant, mode, path


def attempts_in_session(edition, participant, mode, path, settings):
    config = read_json(path / "config.json")
    expected = {**settings, "model": participant["model"], "endpoint": participant["endpoint"]}
    if any(config.get(key) != value for key, value in expected.items() if key != "episodes"):
        raise ValueError(f"Configuration does not match the schedule in {path}")
    events = list(read_log(path / "events.jsonl", recover=True))
    if (path / "summary.json").exists():
        saved = read_json(path / "summary.json")["episodes"]
        ended = [{key: value for key, value in event.items() if key not in ("event", "at")}
            for event in events if event["event"] == "episode_end"]
        if saved != ended:
            raise ValueError(f"Summary and log disagree in {path}")
    ids = sorted({event["episode"] for event in events if event["event"] in ("episode_started", "episode_end")})
    if ids != list(range(1, len(ids) + 1)) or len(ids) > config["episodes"]:
        raise ValueError(f"Inconsistent attempt numbering in {path}")
    for episode in ids:
        trace = [event for event in events if event.get("episode") == episode]
        summary = next((event for event in trace if event["event"] == "episode_end"), None)
        decisions = [event for event in trace if event["event"] == "decision"]
        costs = [(event.get("usage") or {}).get("cost") for event in decisions]
        known = [cost for cost in costs if numeric(cost) and cost >= 0]
        latencies = [event["request_seconds"] for event in decisions if numeric(event.get("request_seconds"))]
        latency = distribution(latencies)
        providers = sorted({event["provider"] for event in decisions if event.get("provider")})
        reason = summary["reason"] if summary else "process_interrupted"
        if reason in OUTCOMES:
            outcome = "win" if reason == "completed" else "loss"
        elif any(event.get("provider_error") for event in trace):
            outcome = "provider_interruption"
        else:
            outcome = "local_interruption"
        metrics = summary or {}
        row = {"participant": participant["name"], "mode": mode, "model": participant["model"],
            "endpoint": participant["endpoint"], "provider": ", ".join(providers),
            "date": config["session_started_utc"], "block": int(path.name[0]),
            "session": path.relative_to(edition).as_posix(), "episode": episode, "reason": reason, "outcome": outcome,
            "frames": metrics.get("frames"), "max_x_pos": metrics.get("max_x_pos"),
            "latency_median_s": latency["median"], "latency_p95_s": latency["p95"],
            "known_cost_usd": metrics.get("known_cost", sum(known) if known else None),
            "cost_known_responses": metrics.get("cost_known_requests", len(known)),
            "received_responses": metrics.get("cost_received_responses", len(decisions)),
            "effective_fps": metrics.get("effective_fps") if mode == "predictive" else None,
            "choices": metrics.get("moves"), "late_choices": metrics.get("late_choices") if mode == "predictive" else None}
        yield Attempt(row, latencies, summary)


def wilson(wins, count):
    p = wins / count
    z = 1.959963984540054
    denominator = 1 + z * z / count
    midpoint = (p + z * z / (2 * count)) / denominator
    radius = z * sqrt((p * (1 - p) + z * z / (4 * count)) / count) / denominator
    return max(0.0, midpoint - radius), min(1.0, midpoint + radius)


def summarize(participant, attempts):
    rows = [attempt.row for attempt in attempts]
    wins = [row for row in rows if row["outcome"] == "win"]
    finished = [row for row in rows if row["outcome"] in ("win", "loss")]
    latencies = distribution([latency for attempt in attempts for latency in attempt.latencies])
    costs = [row["known_cost_usd"] for row in rows if row["known_cost_usd"] is not None]
    fps = [row["effective_fps"] for row in finished if row["effective_fps"] is not None]
    return {**participant, "wins": len(wins), "finished": len(finished), "started": len(rows),
        "provider_interruptions": sum(row["outcome"] == "provider_interruption" for row in rows),
        "positions": [row["max_x_pos"] for row in finished if numeric(row["max_x_pos"])],
        "winning_frames": median(row["frames"] for row in wins) if wins else None,
        "fastest_win": min(row["frames"] for row in wins) if wins else None,
        "latency": latencies, "cost": sum(costs) / len(rows) if costs else None,
        "cost_known": sum(row["cost_known_responses"] for row in rows),
        "cost_received": sum(row["received_responses"] for row in rows),
        "fps": median(fps) if fps else None,
        "choices": sum(row["choices"] or 0 for row in rows),
        "late_choices": sum(row["late_choices"] or 0 for row in rows)}


def metric(value, digits=0):
    return f"{value:.{digits}f}" if value is not None else "—"


def ratio(numerator, denominator):
    return f"{numerator}/{denominator}" if denominator else "—"


def svg_chart(path, rows, *, positions=False):
    title = "Maximum position per finished game" if positions else "Win rate with 95% Wilson interval"
    width, left, right, top, spacing = 820, 220, 30, 46, 34
    height = top + spacing * len(rows) + 42
    maximum = max((value for row in rows for value in row["positions"]), default=0)
    scale = max(1000, ((maximum + 499) // 500) * 500) if positions else 1

    def x(value):
        return left + (width - left - right) * value / scale

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{title}">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        '<g font-family="Arial, sans-serif" fill="#172738" font-size="14">',
        f'<text x="16" y="24" font-size="17" font-weight="bold">{title}</text>']
    for tick in range(6):
        value = scale * tick / 5
        label = f"{value:g} px" if positions else f"{value:.0%}"
        svg += [f'<line x1="{x(value)}" y1="34" x2="{x(value)}" y2="{height - 34}" stroke="#d9e0e7"/>',
            f'<text x="{x(value)}" y="{height - 12}" text-anchor="middle">{label}</text>']
    for index, row in enumerate(rows):
        y = top + index * spacing
        name = escape(row["name"])
        color = "#12628e" if row["finished"] == TARGET else "#64748b"
        svg.append(f'<text x="{left - 12}" y="{y + 5}" text-anchor="end">{name}</text>')
        if positions:
            for point, value in enumerate(sorted(row["positions"])):
                offset = ((point * 7) % 11 - 5) * 1.6
                svg.append(f'<circle cx="{x(value)}" cy="{y + offset}" r="3.2" fill="{color}" opacity="0.68"><title>{name} · {value} px</title></circle>')
        elif row["finished"]:
            low, high = wilson(row["wins"], row["finished"])
            svg += [f'<line x1="{x(low)}" y1="{y}" x2="{x(high)}" y2="{y}" stroke="{color}" stroke-width="2"/>',
                f'<circle cx="{x(row["wins"] / row["finished"])}" cy="{y}" r="5" fill="{color}"/>']
    path.write_text("\n".join([*svg, "</g></svg>", ""]), encoding="utf-8")


def pareto_front(rows):
    """Participants that no cheaper or equally cheap participant beats on win rate."""
    points = sorted((row for row in rows if row["finished"] and row["cost"] is not None),
        key=lambda row: (row["cost"], -row["wins"] / row["finished"]))
    front, best = [], -1.0
    for row in points:
        if (rate := row["wins"] / row["finished"]) > best:
            front.append(row)
            best = rate
    return points, front


def pareto_chart(path, rows):
    width, height, left, right, top, bottom = 820, 460, 70, 40, 64, 52
    points, front = pareto_front(rows)
    highest = max((row["cost"] for row in points), default=0) or 1
    magnitude = 10 ** floor(log10(highest / 5))
    step = next(magnitude * factor for factor in (1, 2, 5, 10) if magnitude * factor * 5 >= highest)
    ticks = ceil(highest / step)
    scale = step * ticks

    def x(cost):
        return left + (width - left - right) * cost / scale

    def y(rate):
        return top + (height - top - bottom) * (1 - rate)

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Win rate and known cost per start">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        '<g font-family="Arial, sans-serif" fill="#172738" font-size="13">',
        '<text x="16" y="24" font-size="17" font-weight="bold">Win rate and known cost per start</text>',
        '<text x="16" y="44" fill="#64748b">Pareto front in blue: no other participant wins more for less. '
        'Known cost is a lower bound.</text>']
    for tick in range(ticks + 1):
        cost = step * tick
        svg += [f'<line x1="{x(cost):.1f}" y1="{top}" x2="{x(cost):.1f}" y2="{height - bottom}" stroke="#d9e0e7"/>',
            f'<text x="{x(cost):.1f}" y="{height - bottom + 18}" text-anchor="middle">${cost:g}</text>']
    for tick in range(6):
        rate = tick / 5
        svg += [f'<line x1="{left}" y1="{y(rate):.1f}" x2="{width - right}" y2="{y(rate):.1f}" stroke="#d9e0e7"/>',
            f'<text x="{left - 8}" y="{y(rate) + 4:.1f}" text-anchor="end">{rate:.0%}</text>']
    svg.append(f'<text x="{(left + width - right) / 2}" y="{height - 10}" text-anchor="middle" fill="#64748b">Known cost per start (USD)</text>')
    if front:
        line = " ".join(f"{x(row['cost']):.1f},{y(row['wins'] / row['finished']):.1f}" for row in front)
        svg.append(f'<polyline points="{line}" fill="none" stroke="#12628e" stroke-width="2"/>')
    for row in points:
        cx, cy = x(row["cost"]), y(row["wins"] / row["finished"])
        color = "#12628e" if row in front else "#94a3b8"
        name = escape(row["name"])
        # A label that would run into a point on its right goes below its own point.
        crowded = any(other is not row and other["wins"] * row["finished"] == row["wins"] * other["finished"]
            and 0 < x(other["cost"]) - cx < 8 * len(row["name"]) for other in points)
        if crowded:
            label = f'x="{cx - 4:.1f}" y="{cy + 22:.1f}"'
        elif cx + 10 + 8 * len(row["name"]) > width:
            label = f'x="{cx - 10:.1f}" y="{cy + 4:.1f}" text-anchor="end"'
        else:
            label = f'x="{cx + 10:.1f}" y="{cy + 4:.1f}"'
        svg += [f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{color}" stroke="#ffffff" stroke-width="2">'
            f'<title>{name} · {row["wins"]}/{row["finished"]} · ${row["cost"]:.5f}</title></circle>',
            f'<text {label}>{name}</text>']
    path.write_text("\n".join([*svg, "</g></svg>", ""]), encoding="utf-8")


def markdown_cell(value):
    return escape(str(value)).replace("|", "&#124;").replace("`", "&#96;")


def make_report(edition, output):
    with edition_source(edition) as source, edition_read_lock(source):
        metadata = read_json(source / "edition.json")
        sessions = list(session_paths(source, metadata))
        attempts = [attempt for participant, mode, path in sessions
            for attempt in attempts_in_session(source, participant, mode, path, metadata["modes"][mode])]
        output.mkdir(parents=True, exist_ok=True)
        with (output / "attempts.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(attempt.row for attempt in attempts)
        lines = ["# SuperMAIrio · Benchmark v1", "",
            f"Edition started {metadata['created_at']} · `{metadata['environment_id']}` · commit `{metadata['commit']}`.", "",
            "[Attempts CSV](attempts.csv) · [Logs and inputs for replay](edition.zip)", "",
            "Position is the maximum horizontal coordinate reached. "
            "Interruptions include provider failures and local stops. The Wilson interval assumes independent games. "
            "Latency per decision includes the network and, in the turn-based track, both questions. "
            f"Real-time sessions ran one at a time; turn-based sessions ran {metadata['turn_based_jobs']} at a time. "
            "Cost coverage counts recorded responses; failed or cancelled requests may add unreported costs.", ""]
        for mode, title in TITLES.items():
            rows = [summarize(participant, [attempt for attempt in attempts if attempt.row["mode"] == mode
                and attempt.row["participant"] == participant["name"]]) for participant in metadata["participants"]]
            rows.sort(key=lambda row: (row["finished"] != TARGET, -row["wins"], row["name"]))
            lines += [f"## {title}", "",
                "| Rank | Participant | Model | Endpoint | Wins | 95% CI | Interruptions (provider) | Median winning frames | Fastest win (frames) | Latency median/p95 s | Known $/start | Cost coverage | Median FPS | Late choices |",
                "| ---: | --- | --- | --- | ---: | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |"]
            rank, previous_wins = 0, None
            for index, row in enumerate(rows, 1):
                wins, finished, started = row["wins"], row["finished"], row["started"]
                interval = "–".join(f"{limit:.0%}" for limit in wilson(wins, finished)) if finished else "—"
                if finished == TARGET and wins != previous_wins:
                    rank, previous_wins = index, wins
                interruption = f"{ratio(started - finished, started)} ({row['provider_interruptions']})" if started else "—"
                fields = [rank if finished == TARGET else "Unranked", row["name"], row["model"], row["endpoint"],
                    f"{wins}/{finished} ({wins / finished:.0%})" if finished else "—", interval,
                    interruption, metric(row["winning_frames"]), metric(row["fastest_win"]),
                    " / ".join(metric(row["latency"][key], 3) for key in ("median", "p95")), metric(row["cost"], 5),
                    ratio(row["cost_known"], row["cost_received"]), metric(row["fps"], 2),
                    ratio(row["late_choices"], row["choices"]) if mode == "predictive" else "—"]
                lines.append("| " + " | ".join(map(markdown_cell, fields)) + " |")
            for name, label, positions in (("wins", "Win rate with intervals", False), ("progress", "Maximum distance", True)):
                chart = f"{mode}-{name}.svg"
                svg_chart(output / chart, rows, positions=positions)
                lines += ["", f"![{label}]({chart})"]
            pareto_chart(output / f"{mode}-pareto.svg", rows)
            lines += ["", f"![Win rate and known cost]({mode}-pareto.svg)"]
            lines.append("")
        (output / "README.md").write_text("\n".join(lines), encoding="utf-8")
        with ZipFile(output / "edition.zip", "w", compression=ZIP_DEFLATED) as archive:
            paths = [source / "edition.json", *(path / name for _, _, path in sessions for name in FILES)]
            for path in paths:
                if path.is_file():
                    info = ZipInfo(path.relative_to(source).as_posix())
                    archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED)


@contextmanager
def edition_read_lock(source):
    from supermairio.benchmark.edition import edition_lock

    if not (source / "edition.json").is_file():
        raise ValueError("Manifesto edition.json mancante")
    if (source / ".lock").exists():
        with edition_lock(source):
            yield
    else:
        yield


@contextmanager
def edition_source(path):
    if path.is_dir():
        yield path
        return
    with TemporaryDirectory() as directory, ZipFile(path) as archive:
        root = Path(directory)
        seen = set()
        for name in archive.namelist():
            parts = PurePosixPath(name).parts
            session_file = (len(parts) == 4 and parts[0] == "sessions" and parts[-1] in FILES
                and re.fullmatch(r"\d{3,}-(predictive|paused)", parts[1]) and re.fullmatch(r"[1-3]-\d{3,}", parts[2]))
            if name in seen or not (name == "edition.json" or session_file):
                raise ValueError("Benchmark archive with an invalid or duplicate path")
            seen.add(name)
            destination = root.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
        yield root


def verify_attempt(game, config, attempt, frames):
    row = attempt.row
    label = f"{row['session']} episode {row['episode']}"
    initial = game.reset(config["seed"]).info.get("x_pos")
    maximum = position = initial
    count = 0
    result = None
    for frame in frames:
        if frame["frames_executed"] != 1 or frame["frames"] != count + 1:
            raise ValueError(f"{label}: inconsistent frame numbering")
        if result is not None and result.done:
            raise ValueError(f"{label}: input after the end of the episode")
        result = game.step(frame["action"], 1)
        count += result.frames_executed
        position = result.observation.info.get("x_pos")
        maximum = max(maximum, position)
        if (position, result.terminated, result.truncated, result.reward) != (
                frame["x_pos"], frame["terminated"], frame["truncated"], frame["reward"]):
            raise ValueError(f"{label}: replay diverges at frame {count}")
    if attempt.summary is None:
        return
    info = result.observation.info if result else {}
    win = bool(info.get("flag_get") or info.get("clear"))
    death = bool(info.get("death"))
    reason = ("completed" if win else "death" if death else "frame_limit" if result and result.truncated else None)
    summary = attempt.summary
    if (count, initial, position, maximum, win, death) != (summary["frames"], summary["initial_x_pos"],
            summary["x_pos"], summary["max_x_pos"], summary["completed"], summary["death"]):
        raise ValueError(f"{label}: summary differs from the replay")
    if (reason or summary["reason"] in {"completed", "death", "frame_limit"}) and reason != summary["reason"]:
        raise ValueError(f"{label}: outcome differs from the replay")
    if summary["reason"] == "wall_limit" and (config["execution_mode"] != "predictive"
            or summary["wall_seconds"] < config["max_episode_seconds"]):
        raise ValueError(f"{label}: wall-clock limit inconsistent with the session")


def verify_edition(edition):
    from supermairio.game.emulator import MarioGame

    verified = 0
    with edition_source(edition) as source, edition_read_lock(source):
        metadata = read_json(source / "edition.json")
        for participant, mode, path in session_paths(source, metadata):
            config = read_json(path / "config.json")
            attempts = list(attempts_in_session(source, participant, mode, path, metadata["modes"][mode]))
            frames = {attempt.row["episode"]: [] for attempt in attempts}
            if attempts and not (path / "frames.jsonl").is_file():
                raise ValueError(f"File dei frame mancante in {path}")
            for frame in read_log(path / "frames.jsonl", recover=True):
                if frame["episode"] not in frames:
                    raise ValueError(f"Frame senza tentativo registrato in {path}")
                frames[frame["episode"]].append(frame)
            if not attempts:
                continue
            with MarioGame(config["max_frames"]) as game:
                for attempt in attempts:
                    verify_attempt(game, config, attempt, frames[attempt.row["episode"]])
                    verified += 1
    return verified
