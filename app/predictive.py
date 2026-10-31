"""Predictive realtime controller: the game never waits, the model sees the instant its choice applies.

Every input is a model choice, held until the next one. The game keeps running at the configured
FPS while requests are in flight. The buttons until the next choice are already known, so shadow
emulators play them from a snapshot up to the frame where that choice takes effect, and the model
receives that predicted screenshot and state. An answer that arrives early waits for its frame; one
that arrives late applies at once and the delay is recorded.

A chain of choices cannot be faster than the request latency: the next request needs the previous
answer. Speculative branches remove that bound. While the answer for choice n is in flight, a request
for choice n+1 is sent for each possible answer n, each with its own predicted state. When answer n
arrives, the branch that matches it continues; the others are unused. The model still selects every
input: speculation only prepares its questions earlier.
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from collections import Counter, deque
from itertools import count
from math import ceil
from time import perf_counter, sleep

from app.contracts import Action, BUTTONS, Observation, has_jump, without_jump
from app.control import PREDICTIVE_MOVES, choice_frames, offered_choices
from app.metrics import ControlHistory, Metrics, numeric
from app.moves import Flight
from app.openrouter import DecisionError, DecisionWorker, encode_png

MIN_HOLD = 8
MAX_HOLD = 90  # a longer hold keeps predictions valid; a late answer forces a resync
FIRST_LATENCY = 0.45  # seconds, until a few answers have been measured
LATENCY_QUANTILE = 0.95
MARGIN_FRAMES = 2  # submission and frame pacing
START_MARGIN = 20  # extra frames before the first choice of an episode
SLOW_EMULATION_FPS = 2000  # measured ~2900 on an idle 8-thread machine, ~1100-1500 when busy
IDLE_EMULATION_FPS = 2900
FIRST_PREPARATION = 0.25  # seconds of previews and request preparation at IDLE_EMULATION_FPS
ANTICIPATE_MAX_HOLD = 50  # above this, emulating every possible answer costs more than it saves
SHADOWS = 4  # emulators for parallel predictions; the native emulator releases the GIL
# One emulator per offered choice: with fewer, the last previews wait for a free thread.
PREVIEW_SHADOWS = len(PREDICTIVE_MOVES)
PREVIEW_STEP = 8  # frames added while a preview ends in the air
PREVIEW_MARGIN = 10  # preview frames beyond the expected hold
PREVIEW_LANDING_CAP = 3  # a preview stops at three times its frames even in the air
# Branch order when fewer branches than choices are allowed: most chosen first, then this order.
PRIORITY = ("right_run", "right_run_jump", "right", "right_jump", "noop", "right_run_hop", "right_hop",
    "right_run_then_jump", "left", "left_run")


def quantile(values, share, default):
    if len(values) < 3:
        return default
    ordered = sorted(values[-30:])
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def held_after(held, plan):
    """Consecutive frames each button is held after playing plan."""
    for action in plan:
        held = {button: held.get(button, 0) + 1 for button in BUTTONS[action] if button != "NOOP"}
    return held


def segment_plan(spec, view, length):
    """Frames of a segment: ("choice", name) is a newly applied choice, its first frames depending on the
    buttons held and the ground at that instant; ("script", first_frames, rest) continues one in progress."""
    if spec[0] == "choice":
        prefix, rest = choice_frames(spec[1], view["held"], view["on_ground"])
    else:
        prefix, rest = list(spec[1]), spec[2]
    return (prefix + [rest] * length)[:length]


def start_view(observation):
    return {"flight": Flight(), "held": Action.NOOP, "held_for": 0, "held_frames": {},
        "on_ground": observation.info.get("on_ground"), "speed": mario_speed(observation)}


def mario_speed(observation):
    return ((observation.info.get("scene") or {}).get("mario") or {}).get("speed")


def advance_view(view, plan, frames):
    """Buttons, jump and ground state after playing plan; frames gives ground and speed after each frame."""
    view = {**view, "flight": deepcopy(view["flight"])}
    for action, after in zip(plan, frames):
        view["flight"].step(action, view["on_ground"], after["on_ground"], view["speed"])
        view["held_frames"] = held_after(view["held_frames"], [action])
        view["held_for"] = view["held_for"] + 1 if action == view["held"] else 1
        view["held"] = action
        view["on_ground"], view["speed"] = after["on_ground"], after["speed"]
    return view


def predict(shadow, state, view, segments):
    """Emulate segments of (spec, frames), see segment_plan. Stops at death or flag."""
    observation, played = None, 0
    for spec, length in segments:
        plan = segment_plan(spec, view, length)
        if not plan:
            continue
        observation, frames, state = shadow.simulate(state, plan)
        view = advance_view(view, plan, frames)
        played += len(frames)
        if len(frames) < len(plan):
            return {"state": state, "view": view, "observation": observation, "complete": False, "played": played}
    return {"state": state, "view": view, "observation": observation, "complete": True, "played": played}


def over_pit(observation):
    pit = (observation.info.get("scene") or {}).get("pit_ahead")
    return bool(pit and pit.get("under_mario"))


def preview(shadow, state, view, start, choice, frames):
    """Emulated result of holding only this choice for frames from the shown instant: information, not a plan."""
    node = predict(shadow, state, view, [(("choice", choice), frames)])
    played = node["played"]
    # In the air or over a pit at the end: keep the same input until he lands or dies, so a jump or
    # a run off an edge shows where it ends.
    _, rest = choice_frames(choice, view["held"], view["on_ground"])
    while (node["complete"] and played < PREVIEW_LANDING_CAP * frames
            and (node["view"]["on_ground"] is False or over_pit(node["observation"]))):
        node = predict(shadow, node["state"], node["view"], [(("script", (), rest), PREVIEW_STEP)])
        played += node["played"]
    node["played"] = played
    info = node["observation"].info
    outcome = ("dies" if info.get("death") else "flag" if info.get("flag_get") else "alive")
    result = {"outcome": outcome}
    result["frames"] = node["played"]
    if numeric(info.get("x_pos")) and numeric(start.get("x_pos")):
        result["dx"] = info["x_pos"] - start["x_pos"]
    if numeric(info.get("y_pos")) and numeric(start.get("y_pos")):
        result["dy"] = info["y_pos"] - start["y_pos"]
    result["on_ground"] = node["view"]["on_ground"]
    return result


class ShadowPool:
    """Threads that each own a shadow emulator for predictions and request preparation."""

    def __init__(self, factory, size, max_frames, seed):
        self._local = threading.local()
        self._games = []
        self._lock = threading.Lock()

        def init():
            game = factory(max_frames)
            game.reset(seed)
            self._local.game = game
            with self._lock:
                self._games.append(game)

        self._size = size
        self._pool = ThreadPoolExecutor(size, thread_name_prefix="shadow", initializer=init)
        # Create every emulator before the episode starts.
        for future in [self._pool.submit(sleep, 0.05) for _ in range(size)]:
            future.result()

    def submit(self, function, *args):
        return self._pool.submit(lambda: function(self._local.game, *args))

    def throughput(self, frames=60):
        """Emulated frames per second with every shadow busy at once: the budget of the previews."""
        def run(game):
            unwrapped = game._env.unwrapped
            for _ in range(frames):
                unwrapped._frame_advance(0)
        started = perf_counter()
        for future in [self.submit(run) for _ in range(self._size)]:
            future.result()
        return self._size * frames / (perf_counter() - started)

    def close(self):
        self._pool.shutdown(wait=True, cancel_futures=True)
        for game in self._games:
            game.close()


def run_predictive(config, *, game_factory, key_provider):
    from app.models import load_model
    from app.session import SessionLog
    client = load_model(config.model, key_provider(), config.request_timeout)
    fps = config.game_fps
    width = config.speculative_width
    window = worker = log = current = shadows = previewers = None
    total = Metrics()
    episodes = []
    status = "stopped"
    episode = 0
    request_index = 0
    wall_total = 0.0
    latencies = []
    projections = []
    entry_ids = count(1)
    first_preparation = FIRST_PREPARATION if config.choice_preview else 0.1  # seconds, until measured
    chosen = Counter()
    # The shadow threads need the GIL back after every native frame: switch sooner than the 5 ms default.
    switch_interval = sys.getswitchinterval()
    sys.setswitchinterval(0.001)

    def event(kind, **data):
        log.event(kind, episode=episode, at=perf_counter(), **data)

    def hold_for(start, frame):
        """Frames the choice applied at start is held: the next answer must arrive before start + hold."""
        needed = ceil(fps * (quantile(latencies, LATENCY_QUANTILE, FIRST_LATENCY)
            + quantile(projections, LATENCY_QUANTILE, first_preparation))) + MARGIN_FRAMES
        # --decision-frames is a minimum: a shorter hold could not receive the next answer in time.
        return max(config.decision_frames or MIN_HOLD, min(MAX_HOLD, frame + needed - start))

    def prepare(shadow, state, view, segments, start, context, base=None):
        """Shadow thread: predicted node at the target frame and its request, so the game loop stays at FPS.
        base, when given, is that node already being emulated while the previous answer was in flight."""
        started = perf_counter()
        node = base.result() if base is not None else predict(shadow, state, view, segments)
        predicted = perf_counter()
        projected, node_view = node["observation"], node["view"]
        control = {**context, "control_mode": "buttons", "game_fps": fps, "decision_frames": context["hold"],
            "choices": offered_choices(PREDICTIVE_MOVES, scripted=False, active=True),
            "input": {"buttons": list(node_view["held_frames"]), "held_frames": node_view["held_frames"]},
            "jump_observation": node_view["flight"].observed() if config.scene else None,
            "current_move": node_view["held"].value, "move_frames": node_view["held_for"],
            "move_finished": False, "move_remaining_frames": None}
        if config.choice_preview and node["complete"]:
            start_info = {"x_pos": projected.info.get("x_pos"), "y_pos": projected.info.get("y_pos")}
            # At least until the next choice can act, with a margin: a shorter preview hides what kills there.
            horizon = max(config.choice_preview, context["hold"] + PREVIEW_MARGIN)
            futures = {choice: previewers.submit(preview, node["state"], node_view, start_info, choice, horizon)
                for choice in control["choices"]}
            control["preview"] = {choice: future.result() for choice, future in futures.items()}
            control["preview_frames"] = horizon
        # Frames at the predicted instant since Mario last got farther right.
        x = projected.info.get("x_pos")
        control["frames_without_progress"] = (0 if not numeric(context["best_x"]) or not numeric(x)
            or x > context["best_x"] else start + node["played"] - context["best_frame"])
        png = encode_png(projected) if config.image else None
        shown = projected if config.scene else Observation(projected.rgb,
            {key: value for key, value in projected.info.items() if key != "scene"})
        request = client.build_request(shown, png, frames=start, previous_move=node_view["held"].value,
            previous_position=None, control_context=control)
        node.update(request=request, png=png, choices=tuple(control["choices"]),
            predicted=(projected.info.get("x_pos"), projected.info.get("y_pos")),
            projection_seconds=predicted - started, preparation_seconds=perf_counter() - predicted)
        return node

    try:
        log = SessionLog(config)
        print(f"Sessione modello: {config.model} | predictive | rami speculativi: {width} | risultati: {log.path}")
        shadows = ShadowPool(game_factory, SHADOWS, config.max_frames, config.seed)
        if config.choice_preview:
            previewers = ShadowPool(game_factory, PREVIEW_SHADOWS, config.max_frames, config.seed)
            # Shadows only replay snapshots: their own state after this measure does not matter.
            rate = previewers.throughput()
            # Previews take longer on a busy CPU: start from a matching estimate, not the idle one.
            first_preparation = FIRST_PREPARATION * max(1.0, IDLE_EMULATION_FPS / rate)
            log.event("emulation_throughput", at=perf_counter(), frames_per_second=rate, threads=PREVIEW_SHADOWS)
            if rate < SLOW_EMULATION_FPS:
                print(f"Emulazione lenta: {rate:.0f} frame/s con {PREVIEW_SHADOWS} thread (servono circa "
                    f"{SLOW_EMULATION_FPS}). CPU occupata: anteprime lente, scelte più distanti e in ritardo; "
                    "risultato poco rappresentativo.")
        with game_factory(config.max_frames) as game:
            if not config.headless:
                from app.viewer import GameWindow
                window = GameWindow()
            for episode in range(1, config.episodes + 1):
                connections = max(1, width + 1) * config.parallel_requests
                worker = DecisionWorker(client, timeout=config.request_timeout, connections=connections)
                worker.ready.wait(config.request_timeout)
                observation = game.reset(config.seed)
                episode_started = next_frame_at = perf_counter()
                deadline = episode_started + config.max_episode_seconds
                initial_position = max_position = observation.info.get("x_pos")
                progress_frame = 0  # last frame that set a new maximum x
                current = Metrics()
                history = ControlHistory(initial_position)
                view = start_view(observation)
                frame = 0
                # Inputs of the choice in progress: its first frames, then rest until the next choice.
                script, rest, current_choice = deque(), Action.NOOP, None
                applied_index = None
                pending = []  # answered choices waiting for their frame, in order
                main = None  # request whose answer is the next choice
                branches = {}  # speculative requests for the choice after main, by main's possible answer
                branched_from = None
                orphans = []  # unused speculative requests: their cost is still recorded
                failed_once = False
                reward = 0.0
                result = None
                reason = None
                hold_estimate = hold_for(0, 0)

                def launch(state, start_view_, start, segments, role, candidate=None, base=None):
                    hold = segments[-1][1]
                    # The next hold is not known yet: the current one is the model's estimate.
                    context = {**history.context(config.execution_mode), "hold": hold,
                        "best_x": max_position, "best_frame": progress_frame}
                    target = start + sum(length for _, length in segments)
                    return {"id": next(entry_ids), "role": role, "candidate": candidate, "target": target,
                        "start": start, "hold": hold, "launched_at": perf_counter(), "handle": None,
                        "future": shadows.submit(prepare, state, start_view_, segments, start, context, base)}

                def anticipate(entry):
                    """While entry's answer is in flight, emulate the next target for every possible answer."""
                    node = entry["node"]
                    if not config.choice_preview or width or not node["complete"]:
                        return
                    answer_frame = frame + ceil(fps * quantile(latencies, LATENCY_QUANTILE, FIRST_LATENCY))
                    hold = hold_for(entry["target"], answer_frame)
                    if hold > ANTICIPATE_MAX_HOLD:
                        return  # busy CPU: emulating every answer would delay the next previews
                    entry["candidates"] = (hold, {choice: previewers.submit(predict, node["state"], node["view"],
                        [(("choice", choice), hold)]) for choice in node["choices"]})

                def resync():
                    """Predict again from the real state: held input, then the answered choices in order."""
                    hold = hold_for(pending[-1]["target"] if pending else frame, frame)
                    marks = [choice["target"] for choice in pending]
                    # The choice in progress continues with its remaining first frames.
                    segments = [(("script", tuple(script), rest), marks[0] - frame if marks else hold)]
                    for number, choice in enumerate(pending):
                        segments.append((("choice", choice["choice"]),
                            marks[number + 1] - choice["target"] if number + 1 < len(marks) else hold))
                    return launch(game.snapshot(), view, frame, segments, "resync")

                def send(entry):
                    nonlocal request_index
                    node = entry["node"] = entry["future"].result()
                    request = node["request"]
                    request_index += 1
                    entry["index"] = request_index
                    # From launch to submission: queueing, emulation, previews and request preparation.
                    projections.append(perf_counter() - entry["launched_at"])
                    current.counts["requests"] += 1
                    current.sample("projection_seconds", node["projection_seconds"])
                    current.sample("preparation_seconds", node["preparation_seconds"])
                    entry["submitted_at"] = perf_counter()
                    entry["handle"] = worker.submit(request.payload, copies=config.parallel_requests)
                    anticipate(entry)
                    event("request", index=request_index, role=entry["role"], candidate=entry["candidate"],
                        frames=frame, start_frame=entry["start"], target_frame=entry["target"],
                        hold_frames=hold_estimate, complete_prediction=node["complete"],
                        projected_death=bool(node["observation"].info.get("death")),
                        projection_seconds=node["projection_seconds"],
                        preparation_seconds=node["preparation_seconds"],
                        wait_seconds=entry["submitted_at"] - entry["launched_at"],
                        screenshot=log.screenshot(request_index, node["png"]), **request.trace)

                def drop(entry):
                    if entry["handle"] is not None:
                        orphans.append(entry["handle"])
                    elif entry["future"] is not None:
                        entry["future"].cancel()
                    current.counts["unused_speculative_requests"] += entry["handle"] is not None

                # The first answer of an episode is often slower; Mario only stands still meanwhile.
                start_hold = hold_for(0, 0) + START_MARGIN
                main = launch(game.snapshot(), view, 0, [(("script", (), Action.NOOP), start_hold)], "chain")
                while reason is None:
                    if window:
                        window.poll()
                        window.consume_reset()
                        if not window.open:
                            reason = "stopped"
                            break
                    if perf_counter() >= deadline:
                        reason = "wall_limit"
                        break
                    # Requests are sent as soon as their prediction is ready, also between frames.
                    for entry in [main, *branches.values()]:
                        if entry is not None and entry["handle"] is None and entry["future"].done():
                            send(entry)
                    # Speculate on main's answer as soon as main's predicted state exists.
                    if width and main is not None and main["handle"] is not None and branched_from != main["id"]:
                        branched_from = main["id"]
                        node = main["node"]
                        if node["complete"]:
                            hold = hold_for(main["target"], frame)
                            ranked = sorted(PREDICTIVE_MOVES, key=lambda name: (-chosen[name], PRIORITY.index(name)))
                            for candidate in ranked[:width]:
                                branches[candidate] = launch(node["state"], node["view"], main["target"],
                                    [(("choice", candidate), hold)], "branch", candidate)
                    for handle in [item for item in orphans if item.done()]:
                        orphans.remove(handle)
                        try:
                            current.unused(handle.result(), "unused_speculative_answers")
                        except Exception:
                            current.counts["unused_speculative_failures"] += 1
                    # Answers apply in order: a newer one waits until the previous choice has been applied.
                    if main is not None and main["handle"] is not None and main["handle"].done() and len(pending) < 2:
                        entry, handle = main, main["handle"]
                        try:
                            decision = handle.result()
                        except DecisionError as exc:
                            if not exc.transient or failed_once:
                                raise
                            failed_once = True
                            current.counts["retried_requests"] += 1
                            event("request_failed", index=entry["index"], message=str(exc), retrying=True)
                            entry["handle"] = worker.submit(entry["node"]["request"].payload,
                                copies=config.parallel_requests)
                        else:
                            failed_once = False
                            if decision.move not in entry["node"]["choices"]:
                                raise DecisionError("Risposta Decisions invalida: scelta non offerta")
                            latency = handle.completed_at - handle.started_at
                            latencies.append(latency)
                            current.decision(decision)
                            current.sample("request_seconds", latency)
                            current.counts["hedge_losers"] += handle.hedge_losers
                            event("decision", index=entry["index"], role=entry["role"],
                                request_started_at=handle.started_at, response_at=handle.completed_at,
                                request_seconds=latency, received_frame=frame, target_frame=entry["target"],
                                hedge_losers=handle.hedge_losers, **asdict(decision))
                            chosen[decision.move] += 1
                            pending.append({"index": entry["index"], "choice": decision.move,
                                "target": entry["target"], "predicted": entry["node"]["predicted"]})
                            follow = branches.pop(decision.move, None)
                            for other in branches.values():
                                drop(other)
                            branches = {}
                            if width:
                                current.counts["speculation_hits" if follow else "speculation_misses"] += 1
                            if follow is not None and frame >= entry["target"]:
                                # A late answer makes every later prediction stale: resync instead.
                                drop(follow)
                                follow = None
                            if follow is None and frame < entry["target"]:
                                # No branch for this answer: predict the next choice from main's state now.
                                node = entry["node"]
                                hold, ready = entry.get("candidates", (None, {}))
                                if decision.move in ready:
                                    follow = launch(None, None, entry["target"], [(("choice", decision.move), hold)],
                                        "chain", base=ready[decision.move])
                                else:
                                    follow = (launch(node["state"], node["view"], entry["target"],
                                        [(("choice", decision.move), hold_for(entry["target"], frame))], "chain")
                                        if node["complete"] else None)
                            main = follow
                    if main is None and not pending:
                        # A predicted death or flag did not happen: predict again from the real state.
                        main = resync()
                    now = perf_counter()
                    if now < next_frame_at:
                        # Short sleeps: Windows event waits round to a coarse tick (see DecisionRequestHandle).
                        sleep(min(next_frame_at - now, 0.002))
                        continue
                    # Apply a choice at its predicted frame; a late one applies at once.
                    stale = False
                    while pending and frame >= pending[0]["target"]:
                        choice = pending.pop(0)
                        late = frame - choice["target"]
                        # On time, the shown state must be the real one: a check of the shadow emulation.
                        actual = (observation.info.get("x_pos"), observation.info.get("y_pos"))
                        mismatch = not late and actual != choice["predicted"]
                        current.counts["prediction_mismatches"] += mismatch
                        stale = stale or late > 0 or mismatch
                        first, rest = choice_frames(choice["choice"], view["held"], view["on_ground"])
                        script = deque(first)
                        current_choice = choice["choice"]
                        applied_index = choice["index"]
                        current.counts["moves"] += 1
                        current.sample("late_frames", late)
                        current.counts["late_choices"] += late > 0
                        event("choice_applied", index=choice["index"], move=current_choice, frame=frame,
                            target_frame=choice["target"], late_frames=late, prediction_mismatch=mismatch,
                            **({"predicted_position": choice["predicted"], "actual_position": actual} if mismatch else {}))
                    if stale:
                        # Later predictions assumed this choice on time: they no longer match the game.
                        for entry in [main, *branches.values()]:
                            if entry is not None:
                                drop(entry)
                        branches, branched_from = {}, None
                        main = resync()
                        current.counts["resyncs"] += 1
                        event("resync", frame=frame, pending=[choice["index"] for choice in pending])
                    if perf_counter() >= deadline:
                        reason = "wall_limit"
                        break
                    step_started = perf_counter()
                    # Fixed frame schedule; after a long stall, restart it instead of bursting frames.
                    next_frame_at = max(next_frame_at + 1 / fps, step_started - 2 / fps)
                    applied = script.popleft() if script else rest
                    result = game.step(applied, 1)
                    observation = result.observation
                    frame += result.frames_executed
                    current.counts["frames"] += result.frames_executed
                    if applied_index is None:
                        current.counts["waiting_frames"] += result.frames_executed
                    if observation.info.get("on_ground") is False:
                        current.counts["airborne_frames"] += result.frames_executed
                    view = advance_view(view, [applied], [{"on_ground": observation.info.get("on_ground"),
                        "speed": mario_speed(observation)}])
                    reward += result.reward
                    position = observation.info.get("x_pos")
                    if numeric(position):
                        if not numeric(max_position) or position > max_position:
                            max_position, progress_frame = position, frame
                    history.step(applied, position)
                    hold_estimate = hold_for(0, 0) if not branches else next(iter(branches.values()))["hold"]
                    log.frame(episode=episode, at=perf_counter(), index=applied_index, move_index=applied_index,
                        source="move" if applied_index is not None else "waiting",
                        move=current_choice, action=applied.value,
                        frames=frame, frames_executed=result.frames_executed, execution_started_at=step_started,
                        observation_at=perf_counter(), reward=result.reward, x_pos=position,
                        on_ground=observation.info.get("on_ground"),
                        terminated=result.terminated, truncated=result.truncated)
                    if result.done:
                        info = observation.info
                        reason = ("completed" if info.get("flag_get") or info.get("clear") else
                            "death" if info.get("death") else "frame_limit" if result.truncated else "terminated")
                    if window:
                        window.show(observation, f"SuperMAIrio | predictive | episodio {episode} | {applied.value} | "
                            f"scelte {current.counts['moves']} | ogni {hold_estimate} frame | frame {frame} | x={position}")
                ended = perf_counter()
                for entry in [main, *branches.values()]:
                    if entry is not None:
                        if entry["handle"] is None:
                            entry["future"].cancel()
                        elif not entry["handle"].done():
                            current.counts["cancelled_requests"] += 1
                            event("request_cancelled", index=entry["index"], reason=reason)
                for choice in pending:
                    current.counts["discarded_responses"] += 1
                    event("request_discarded", index=choice["index"], reason=reason)
                current.counts["cancelled_requests"] += sum(not item.done() for item in orphans)
                worker.close()
                for item in worker.extra_decisions:
                    current.unused(item, "hedged_answers")
                worker = None
                duration = ended - episode_started
                wall_total += duration
                info = observation.info
                summary = {"episode": episode, "reason": reason, "started_at": episode_started, "ended_at": ended,
                    "reward": reward, "initial_x_pos": initial_position, "x_pos": info.get("x_pos"),
                    "max_x_pos": max_position, "terminated": bool(result and result.terminated),
                    "truncated": reason in ("frame_limit", "wall_limit"), "death": bool(info.get("death")),
                    "completed": bool(info.get("flag_get") or info.get("clear")),
                    "speculative_width": width, **current.summary(duration)}
                episodes.append(summary)
                log.event("episode_end", at=ended, **summary)
                total.merge(current)
                current = None
                print(f"Episodio {episode}: {reason}; frame={summary['frames']}, x={info.get('x_pos', '?')}, "
                    f"scelte={summary['moves']}, in ritardo={summary['late_choices']}, "
                    f"costo noto={summary['known_cost'] or 0:.4f}$")
                if reason == "stopped":
                    break
            else:
                status = "finished"
                print(f"Completati {sum(item['completed'] for item in episodes)}/{len(episodes)} episodi, "
                    f"costo noto {total.known_cost:.4f}$, risultati in {log.path}")
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    except Exception as exc:
        status = "error"
        if current is not None:
            current.counts["errors"] += 1
        if log:
            event("error", index=request_index, message=str(exc))
        raise
    finally:
        try:
            if worker is not None:
                worker.close()
            if shadows is not None:
                shadows.close()
            if previewers is not None:
                previewers.close()
            sys.setswitchinterval(switch_interval)
            if window is not None:
                window.close()
        finally:
            if log:
                try:
                    log.finish(status=status, execution_mode=config.execution_mode, **total.summary(wall_total),
                        episodes=episodes, completed_episodes=sum(item["completed"] for item in episodes),
                        deaths=sum(item["death"] for item in episodes),
                        max_x_pos=max((item["max_x_pos"] for item in episodes if numeric(item["max_x_pos"])),
                            default=None))
                finally:
                    log.close()
