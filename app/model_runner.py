"""Model controller: one request at a time, each decision a complete move, auditable episode timelines."""

import asyncio
from collections import deque
from concurrent.futures import CancelledError
from dataclasses import asdict
from statistics import median
from time import perf_counter, sleep

from app.config import DISPLAY_FPS
from app.contracts import Observation
from app.metrics import ControlHistory, Metrics, numeric
from app.moves import CONTINUE, MOVES, MoveExecutor
from app.openrouter import DecisionError, DecisionWorker, encode_png

SLOW_PROVIDER_SECONDS = 0.6  # median request latency that makes an episode unrepresentative


def run_model(config, *, game_factory, key_provider):
    from app.models import load_model
    from app.session import SessionLog
    client = load_model(config.model, key_provider(), config.request_timeout)
    realtime = config.execution_mode == "realtime"
    fps = config.game_fps if realtime else DISPLAY_FPS
    window = worker = log = current = last_entry = in_flight = None
    total = Metrics()
    episodes = []
    status = "stopped"
    episode = 0
    request_index = 0
    wall_total = 0.0

    def event(kind, **data):
        log.event(kind, episode=episode, at=perf_counter(), **data)

    def receive(entry):
        nonlocal last_discard, last_entry
        acquired = perf_counter()
        last_entry = entry
        handle = entry["handle"]
        decision = handle.result()
        last_discard = None
        current.decision(decision)
        latency = handle.completed_at - handle.started_at
        current.sample("request_seconds", latency)
        current.sample("polling_seconds", acquired - handle.completed_at)
        event("decision", index=entry["index"], acquired_at=acquired,
            request_started_at=handle.started_at, response_at=handle.completed_at,
            request_seconds=latency, polling_seconds=acquired - handle.completed_at,
            **asdict(decision))
        return decision, latency

    def discard_stale(index, age_frames, age):
        nonlocal consecutive_stale, stale_warning_sent, last_discard
        current.counts["stale_responses"] += 1
        current.counts["discarded_responses"] += 1
        consecutive_stale += 1
        last_discard = f"ultima risposta scartata: età {age_frames} frame > soglia {config.max_decision_frames}"
        event("request_discarded", index=index, reason="stale", observation_age_frames=age_frames,
            max_decision_frames=config.max_decision_frames, observation_age_seconds=age)
        if consecutive_stale >= 3 and not stale_warning_sent:
            stale_warning_sent = True
            print(f"Episodio {episode}: tre risposte obsolete consecutive; "
                f"ultima età {age_frames} frame ({age:.3f}s) > soglia {config.max_decision_frames} frame. "
                "Verificare --max-decision-frames: queste risposte non hanno eseguito mosse.")

    def retire(reason):
        nonlocal worker, in_flight
        # Closing joins the worker: an old episode can never deliver to the next.
        if worker is not None:
            worker.close()
        entry, in_flight = in_flight, None
        worker = None
        if entry is None:
            return
        try:
            receive(entry)
        except (asyncio.CancelledError, CancelledError):
            current.counts["cancelled_requests"] += 1
            event("request_cancelled", index=entry["index"], reason=reason,
                request_started_at=entry["handle"].started_at, response_at=entry["handle"].completed_at)
        else:
            current.counts["discarded_responses"] += 1
            event("request_discarded", index=entry["index"], reason=reason)

    def finish_episode(reason, ended):
        nonlocal current, wall_total
        duration = ended - episode_started
        wall_total += duration
        info = observation.info
        summary = {"episode": episode, "reason": reason, "started_at": episode_started,
            "ended_at": ended, "reward": reward, "initial_x_pos": initial_position,
            "x_pos": info.get("x_pos"), "max_x_pos": max_position,
            "terminated": bool(result and result.terminated),
            "truncated": reason in ("frame_limit", "wall_limit"),
            "death": bool(info.get("death")),
            "completed": bool(info.get("flag_get") or info.get("clear")),
            **current.summary(duration)}
        # Typical responses take 0.2-0.3 s; above this the model reacts too rarely to compare runs.
        latency = summary["timings"]["request_seconds"]["median"]
        summary["slow_provider"] = latency is not None and latency > SLOW_PROVIDER_SECONDS
        episodes.append(summary)
        log.event("episode_end", at=ended, **summary)
        total.merge(current)
        current = None

    def start_move(chosen, position):
        nonlocal active, selected, previous_position
        if active is not None and not active["ended"]:
            end_move("replaced")
        executor.start(chosen["move"])
        now = perf_counter()
        selected = chosen["move"].name
        previous_position = position
        current.counts["moves"] += 1
        current.sample("observation_age_seconds", now - chosen["observed_at"])
        if chosen["deferred"]:
            current.sample("deferred_seconds", now - chosen["decided_at"])
        active = {"index": chosen["index"], "move": selected, "observation_at": chosen["observed_at"],
            "start_position": position, "frames": 0, "last_frame_at": None, "ended": False}
        event("move_start", index=chosen["index"], move=selected, repeated=chosen["repeated"],
            started_at=now, observation_age_seconds=now - chosen["observed_at"],
            deferred_seconds=now - chosen["decided_at"] if chosen["deferred"] else None)

    def end_move(outcome):
        elapsed = (active["last_frame_at"] - active["observation_at"]
            if active["last_frame_at"] is not None else None)
        if elapsed is not None:
            current.sample("observation_to_last_frame_seconds", elapsed)
        history.record(active["index"], active["move"], active["frames"], active["start_position"],
            observation.info.get("x_pos"))
        event("move_end", index=active["index"], move=active["move"], frames_executed=active["frames"],
            outcome=outcome, last_frame_at=active["last_frame_at"], observation_to_last_frame_seconds=elapsed)
        active["ended"] = True

    def check_completed():
        if active is not None and not active["ended"] and executor.finished:
            end_move("completed")

    def finish_active(reason):
        nonlocal active, pending
        if active is not None and not active["ended"]:
            end_move("interrupted")
        active = None
        if pending is not None:
            current.counts["discarded_responses"] += 1
            event("request_discarded", index=pending["index"], reason=reason)
            pending = None

    try:
        log = SessionLog(config)
        print(f"Sessione modello: {config.model} | {config.execution_mode} | risultati: {log.path}")
        with game_factory(config.max_frames) as game:
            if not config.headless:
                from app.viewer import GameWindow
                window = GameWindow()
            for episode in range(1, config.episodes + 1):
                observation = game.reset(config.seed)
                observed_at = episode_started = perf_counter()
                episode_deadline = episode_started + config.max_episode_seconds
                initial_position = max_position = observation.info.get("x_pos")
                history = ControlHistory(initial_position)
                executor = MoveExecutor()
                latencies = deque(maxlen=5)
                reward = 0.0
                selected = previous_position = result = active = pending = None
                last_discard = None
                failed_once = False
                consecutive_stale = 0
                stale_warning_sent = False
                current = Metrics()
                worker = DecisionWorker(client)
                applied, source = executor.current()
                reason = None
                latency = None
                while reason is None:
                    pace_started = perf_counter()
                    if window:
                        window.poll()
                        window.consume_reset()
                        if not window.open:
                            reason = "stopped"
                            break
                    if realtime and perf_counter() >= episode_deadline:
                        reason = "wall_limit"
                        break
                    on_ground = observation.info.get("on_ground")
                    executor.settle(on_ground)
                    check_completed()
                    # Decision: a new move, or continue the current one (repeat it once ended).
                    decision = None
                    if in_flight is not None and in_flight["handle"].done():
                        entry, in_flight = in_flight, None
                        try:
                            decision, latency = receive(entry)
                        except DecisionError as exc:
                            # One more request for a provider hiccup; a second failure in a row stops.
                            if not exc.transient or failed_once:
                                raise
                            failed_once = True
                            current.counts["retried_requests"] += 1
                            event("request_failed", index=entry["index"], message=str(exc), retrying=True,
                                request_started_at=entry["handle"].started_at, response_at=entry["handle"].completed_at)
                        else:
                            failed_once = False
                    if decision is not None:
                        latencies.append(latency)
                        decided_at = perf_counter()
                        age = decided_at - entry["observed_at"]
                        # Staleness counts game frames: a slower game leaves more time to the model.
                        age_frames = current.counts["frames"] - entry["frame"]
                        if age_frames > config.max_decision_frames:
                            discard_stale(entry["index"], age_frames, age)
                        elif decision.move == CONTINUE and not executor.finished:
                            current.counts["continues"] += 1
                            consecutive_stale = 0
                            event("move_continued", index=entry["index"], move=executor.move.name,
                                move_frames=executor.frames)
                        else:
                            repeated = decision.move == CONTINUE
                            if repeated:
                                current.counts["continues"] += 1
                            consecutive_stale = 0
                            move = (executor.move or MOVES["wait"]) if repeated else MOVES[decision.move]
                            pending = {"index": entry["index"], "move": move, "observed_at": entry["observed_at"],
                                "decided_at": decided_at, "repeated": repeated, "deferred": False}
                    # Action: committed jump frames are never cut; a new jump waits for the landing.
                    if pending is not None:
                        if executor.can_start(pending["move"], on_ground):
                            start_move(pending, observation.info.get("x_pos"))
                            pending = None
                        elif not pending["deferred"]:
                            pending["deferred"] = True
                            current.counts["deferred_moves"] += 1
                            event("move_deferred", index=pending["index"], move=pending["move"].name,
                                reason="committed" if executor.committed else "airborne",
                                current_move=executor.move.name if executor.move else None)
                    # Call: realtime asks again as soon as a decision is applied, while the move
                    # runs; paused asks once the move has ended, with the game stopped.
                    if in_flight is None and pending is None and (realtime or executor.finished):
                        prepared_at = perf_counter()
                        png = encode_png(observation)
                        control = history.context(config.execution_mode)
                        control.update(current_move=executor.move.name if executor.move else None,
                            move_frames=executor.frames, move_finished=executor.finished,
                            move_committed=executor.committed, move_remaining_frames=executor.remaining,
                            tail_action=executor.tail_action.value)
                        if realtime:
                            control["game_fps"] = config.game_fps
                            control["recent_latency_seconds"] = round(median(latencies), 3) if latencies else None
                        shown = observation if config.scene else Observation(observation.rgb,
                            {key: value for key, value in observation.info.items() if key != "scene"})
                        request = client.build_request(shown, png, frames=current.counts["frames"],
                            previous_move=selected, previous_position=previous_position, control_context=control)
                        request_index += 1
                        screenshot = log.screenshot(request_index, png)
                        submitted_at = perf_counter()
                        current.counts["requests"] += 1
                        current.sample("preparation_seconds", submitted_at - prepared_at)
                        in_flight = {"index": request_index, "observed_at": observed_at,
                            "frame": current.counts["frames"], "handle": worker.submit(request.payload)}
                        event("request", index=request_index, frames=current.counts["frames"],
                            screenshot=screenshot, observation_at=observed_at,
                            preparation_started_at=prepared_at, submitted_at=submitted_at,
                            preparation_seconds=submitted_at - prepared_at, **request.trace)
                    # Preparation, logging and rendering can cross the wall deadline.
                    if realtime and perf_counter() >= episode_deadline:
                        reason = "wall_limit"
                        break
                    if realtime or (in_flight is None and (not executor.finished or pending is not None)):
                        applied, source = executor.current()
                        step_started = perf_counter()
                        result = game.step(applied, 1)
                        executor.advance(result.frames_executed)
                        observed_at = perf_counter()
                        observation = result.observation
                        current.counts["frames"] += result.frames_executed
                        reward += result.reward
                        position = observation.info.get("x_pos")
                        if numeric(position):
                            max_position = max(max_position, position) if numeric(max_position) else position
                        history.step(applied, position)
                        if source in ("move", "release"):
                            if source == "release":
                                current.counts["jump_release_frames"] += result.frames_executed
                            if active["last_frame_at"] is None:
                                current.sample("observation_to_first_frame_seconds", observed_at - active["observation_at"])
                            active["frames"] += result.frames_executed
                            active["last_frame_at"] = observed_at
                        else:
                            current.counts["tail_frames" if source == "tail" else "waiting_frames"] += result.frames_executed
                        event("execution", index=active["index"] if active is not None else request_index,
                            source=source, move=executor.move.name if executor.move else None, action=applied.value,
                            frames=current.counts["frames"], frames_executed=result.frames_executed,
                            execution_started_at=step_started, observation_at=observed_at,
                            reward=result.reward, x_pos=position, on_ground=observation.info.get("on_ground"),
                            terminated=result.terminated, truncated=result.truncated)
                        if result.done:
                            info = observation.info
                            reason = ("completed" if info.get("flag_get") or info.get("clear") else
                                "death" if info.get("death") else "frame_limit" if result.truncated else "terminated")
                        else:
                            check_completed()
                    if window:
                        timing = f"{latency * 1000:.0f} ms" if latency is not None and in_flight is None else "attesa"
                        diagnostic = f" | {last_discard}" if last_discard is not None else ""
                        move_label = executor.move.name if executor.move else "-"
                        window.show(observation, f"SuperMAIrio | {config.execution_mode} | mosse {current.counts['moves']} | scarti {current.counts['stale_responses']}{diagnostic} | episodio {episode} | {move_label} ({source}) | {timing} | frame {current.counts['frames']} | x={observation.info.get('x_pos', '?')}")
                    if reason is None and (realtime or window or in_flight is not None):
                        # Pace from this tick, never from a deadline in the past.
                        delay = max(0.0, 1 / fps - (perf_counter() - pace_started))
                        if realtime:
                            delay = min(delay, max(0.0, episode_deadline - perf_counter()))
                        sleep(delay)
                ended = perf_counter()
                retire(reason)
                finish_active(reason)
                finish_episode(reason, ended)
                print(f"Episodio {episode}: {reason}; frame={episodes[-1]['frames']}, x={observation.info.get('x_pos', '?')}, reward={reward:.1f}")
                if episodes[-1]["slow_provider"]:
                    print(f"Episodio {episode}: provider lento (mediana "
                        f"{episodes[-1]['timings']['request_seconds']['median']:.2f} s): risultato poco "
                        "rappresentativo; valutare --game-fps 30")
                if reason == "stopped":
                    break
            else:
                status = "finished"
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    except Exception as exc:
        status = "error"
        if current is not None:
            current.counts["errors"] += 1
        if log:
            failed = last_entry["handle"] if last_entry is not None else None
            event("error", index=last_entry["index"] if last_entry is not None else request_index, message=str(exc),
                request_started_at=failed.started_at if failed else None,
                response_at=failed.completed_at if failed else None)
        raise
    finally:
        ended = perf_counter()
        try:
            if worker is not None:
                try:
                    retire(status)
                except Exception as exc:
                    status = "error"
                    current.counts["errors"] += 1
                    event("error", index=request_index, message=str(exc))
                    raise
        finally:
            try:
                if current is not None:
                    finish_active(status)
                    finish_episode(status, ended)
                if window is not None:
                    window.close()
            finally:
                if log:
                    try:
                        log.finish(status=status, execution_mode=config.execution_mode,
                            **total.summary(wall_total), episodes=episodes,
                            reward=sum(item["reward"] for item in episodes),
                            initial_x_pos=episodes[0]["initial_x_pos"] if episodes else None,
                            x_pos=episodes[-1]["x_pos"] if episodes else None,
                            max_x_pos=max((item["max_x_pos"] for item in episodes
                                if numeric(item["max_x_pos"])), default=None),
                            completed_episodes=sum(item["completed"] for item in episodes),
                            deaths=sum(item["death"] for item in episodes),
                            current_episode=episode,
                            current_frames=episodes[-1]["frames"] if episodes else 0,
                            current_reward=episodes[-1]["reward"] if episodes else 0.0)
                    finally:
                        log.close()
