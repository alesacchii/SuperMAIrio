"""Monotonic episode measurements and bounded controller history."""

from collections import Counter, deque
import math
from statistics import median

from app.contracts import BUTTONS


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def distribution(values):
    if not values:
        return {"samples": 0, "median": None, "p95": None}
    ordered = sorted(values)
    return {"samples": len(values), "median": median(values),
        "p95": ordered[math.ceil(0.95 * len(values)) - 1]}


class Metrics:
    def __init__(self):
        self.counts = Counter()
        self.samples = {name: [] for name in ("request_seconds", "preparation_seconds", "dispatch_seconds",
            "polling_seconds", "observation_age_seconds", "observation_age_frames",
            "observation_to_first_frame_seconds", "observation_to_last_frame_seconds")}
        self.known_cost = 0.0
        self.cost_known_requests = 0

    def sample(self, name, value):
        self.samples[name].append(value)

    def decision(self, decision):
        self.counts["decisions"] += 1
        cost = (decision.usage or {}).get("cost")
        if numeric(cost) and cost >= 0:
            self.known_cost += cost
            self.cost_known_requests += 1

    def merge(self, other):
        self.counts.update(other.counts)
        for name in self.samples:
            self.samples[name].extend(other.samples[name])
        self.known_cost += other.known_cost
        self.cost_known_requests += other.cost_known_requests

    def summary(self, seconds):
        counts = {name: self.counts[name] for name in ("requests", "decisions", "moves", "continues",
            "frames", "waiting_frames", "jump_release_frames", "airborne_frames", "execution_intervals",
            "not_applicable_decisions", "stale_responses", "discarded_responses", "cancelled_requests",
            "retried_requests", "errors")}
        return {**counts, "wall_seconds": seconds,
            "requests_per_second": counts["requests"] / seconds if seconds > 0 else None,
            "decisions_per_second": counts["decisions"] / seconds if seconds > 0 else None,
            "moves_per_second": counts["moves"] / seconds if seconds > 0 else None,
            "effective_fps": counts["frames"] / seconds if seconds > 0 else None,
            "timings": {name: distribution(values) for name, values in self.samples.items()},
            "known_cost": self.known_cost if self.cost_known_requests else None,
            "cost_known_requests": self.cost_known_requests,
            "cost_missing_received_requests": counts["decisions"] - self.cost_known_requests}


class ControlHistory:
    def __init__(self, position):
        self.positions = deque([position], maxlen=121)
        self.directional = deque(maxlen=120)
        self.moves = deque(maxlen=8)

    def step(self, action, position):
        self.positions.append(position)
        self.directional.append(any(button in ("left", "right") for button in BUTTONS[action]))

    def record(self, index, move, frames, start_position, end_position):
        self.moves.append({"index": index, "move": move, "frames": frames,
            "delta_x": end_position - start_position if numeric(start_position) and numeric(end_position) else None})

    def context(self, mode):
        if any(not numeric(x) for x in self.positions):
            stuck = None
        else:
            stuck = (len(self.directional) == 120 and sum(self.directional) >= 30
                and max(self.positions) - min(self.positions) <= 2)
        return {"execution_mode": mode, "stuck": stuck, "recent_moves": list(self.moves)}
