"""Model controller: one request at a time, each decision a complete move, auditable episode timelines."""

import asyncio
from collections import deque
from concurrent.futures import CancelledError
from dataclasses import asdict
from statistics import median
from time import perf_counter, sleep

from app.config import DISPLAY_FPS
from app.contracts import Observation
from app.control import control_protocol, direct_control, offered_choices
from app.metrics import ControlHistory, Metrics, numeric
from app.moves import CONTINUE, Flight
from app.openrouter import DecisionError, DecisionWorker, encode_png

SLOW_PROVIDER_SECONDS = 0.6  # median request latency that makes an episode unrepresentative


def mario_speed(observation):
    return ((observation.info.get("scene") or {}).get("mario") or {}).get("speed")


def run_model(config, *, game_factory, key_provider):
    controller_started = perf_counter()
    controller_to_first_frame = None
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
    preparations = []
    setup_started = None
    setup_recorded = True

    def create_worker():
        nonlocal worker, setup_started, setup_recorded
        setup_started = perf_counter()
        setup_recorded = False
        worker = DecisionWorker(client, timeout=config.request_timeout)

    def record_setup():
        nonlocal setup_recorded
        if setup_recorded or worker is None:
            return
        handle = worker.ready
        try:
            outcome = handle.result()
        except (asyncio.CancelledError, CancelledError):
            outcome = "cancelled"
        ended = handle.completed_at if handle.completed_at is not None else perf_counter()
        data = {"episode": episode or 1, "started_at": setup_started, "ended_at": ended,
            "seconds": ended - setup_started, "outcome": outcome}
        preparations.append(data)
        log.event("worker_prepared", at=perf_counter(), **data)
        setup_recorded = True

    def wait_for_response(delay):
        if in_flight is not None:
            in_flight["handle"].wait(delay)
        else:
            sleep(delay)

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
        dispatch = handle.started_at - entry["submitted_at"]
        current.sample("dispatch_seconds", dispatch)
        current.sample("request_seconds", latency)
        current.sample("polling_seconds", acquired - handle.completed_at)
        event("decision", index=entry["index"], acquired_at=acquired,
            request_started_at=handle.started_at, response_at=handle.completed_at,
            request_seconds=latency, dispatch_seconds=dispatch, polling_seconds=acquired - handle.completed_at,
            **asdict(decision))
        return decision, latency, acquired

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
            record_setup()
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
        # Paused episodes wait for every answer: latency cannot change their outcome.
        summary["slow_provider"] = realtime and latency is not None and latency > SLOW_PROVIDER_SECONDS
        episodes.append(summary)
        log.event("episode_end", at=ended, **summary)
        total.merge(current)
        current = None

    def start_move(chosen, position):
        nonlocal active, selected, previous_position
        if direct_control(config.control_mode) or observation.info.get("on_ground") is not True:
            flight.invalidate()
        executor.start(chosen["move"])
        now = perf_counter()
        selected = chosen["move"].name
        previous_position = position
        current.counts["moves"] += 1
        current.sample("observation_age_seconds", now - chosen["observed_at"])
        age_frames = current.counts["frames"] - chosen["frame"]
        current.sample("observation_age_frames", age_frames)
        active = {"index": chosen["index"], "move": selected, "observation_at": chosen["observed_at"],
            "start_position": position, "frames": 0, "last_frame_at": None, "ended": False}
        event("move_start", index=chosen["index"], move=selected,
            started_at=now, observation_age_seconds=now - chosen["observed_at"],
            observation_age_frames=age_frames)

    def close_execution(reason, ended=None):
        nonlocal interval
        if interval is None:
            return
        event("execution", **interval, ended_at=perf_counter() if ended is None else ended, end_frame=current.counts["frames"],
            end_x_pos=observation.info.get("x_pos"), outcome=reason)
        current.counts["execution_intervals"] += 1
        interval = None

    def open_execution(chosen, applicable=True):
        nonlocal interval
        close_execution("next_decision")
        interval = {"index": chosen["index"], "choice": chosen["choice"],
            "move": executor.move.name if not executor.finished else None,
            "applicable": applicable, "started_at": perf_counter(),
            "start_frame": current.counts["frames"], "start_x_pos": observation.info.get("x_pos"),
            "frames_executed": 0, "move_frames": 0, "waiting_frames": 0,
            "first_frame_at": None, "last_frame_at": None, "move_end": None}
        event("execution_start", index=chosen["index"], choice=chosen["choice"],
            applicable=applicable, frame=current.counts["frames"])

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
        if interval is not None:
            interval["move_end"] = {"frame": current.counts["frames"], "outcome": outcome}

    def check_completed():
        if active is not None and not active["ended"] and executor.finished:
            end_move("completed")

    def finish_active(reason, ended=None):
        nonlocal active, received
        if active is not None and not active["ended"]:
            end_move("interrupted")
        active = None
        close_execution(reason, ended)
        if received is not None:
            current.counts["discarded_responses"] += 1
            event("request_discarded", index=received["index"], reason=reason)
            received = None

    def submit_request():
        nonlocal in_flight, request_index, last_request_frame
        prepared_at = perf_counter()
        png = encode_png(observation) if config.image else None
        control = history.context(config.execution_mode)
        control.update(control_mode=config.control_mode,
            choices=offered_choices(catalog, scripted=config.control_mode == "moves", active=not executor.finished))
        if direct_control(config.control_mode):
            control["input"] = executor.input_context()
            control["jump_observation"] = flight.observed() if config.scene else None
        control.update(current_move=executor.move.name if executor.move else None,
            move_frames=executor.frames, move_finished=executor.finished,
            move_remaining_frames=executor.remaining,
            tail_action="noop" if config.control_mode == "moves" else None,
            # From the RAM speed: --no-scene withholds it like the rest of the scene.
            landing_in_frames=flight.landing_in(mario_speed(observation), observation.info.get("on_ground"),
                executor.jump_hold_left) if config.scene and config.control_mode == "moves" else None)
        if realtime:
            control["game_fps"] = config.game_fps
            control["recent_latency_seconds"] = round(median(latencies), 3) if latencies else None
            control["recent_response_frames"] = median(response_frames) if response_frames else None
        shown = observation if config.scene else Observation(observation.rgb,
            {key: value for key, value in observation.info.items() if key != "scene"})
        request = client.build_request(shown, png, frames=current.counts["frames"],
            previous_move=selected, previous_position=previous_position, control_context=control)
        request_index += 1
        screenshot = log.screenshot(request_index, png)
        submitted_at = perf_counter()
        current.counts["requests"] += 1
        last_request_frame = current.counts["frames"]
        current.sample("preparation_seconds", submitted_at - prepared_at)
        in_flight = {"index": request_index, "observed_at": observed_at,
            "submitted_at": submitted_at,
            "frame": current.counts["frames"],
            "choices": tuple(control["choices"]),
            "handle": worker.submit(request.payload)}
        event("request", index=request_index, frames=current.counts["frames"],
            screenshot=screenshot, observation_at=observed_at,
            preparation_started_at=prepared_at, submitted_at=submitted_at,
            preparation_seconds=submitted_at - prepared_at, **request.trace)

    try:
        log = SessionLog(config)
        print(f"Sessione modello: {config.model} | {config.execution_mode} | risultati: {log.path}")
        create_worker()
        with game_factory(config.max_frames) as game:
            if not config.headless:
                from app.viewer import GameWindow
                window = GameWindow()
            for episode in range(1, config.episodes + 1):
                if worker is None:
                    create_worker()
                while not worker.ready.done():
                    if window:
                        window.poll()
                        window.consume_reset()
                        if not window.open:
                            break
                    worker.ready.wait(1 / DISPLAY_FPS)
                if window and not window.open:
                    break
                record_setup()
                observation = game.reset(config.seed)
                observed_at = episode_started = perf_counter()
                episode_deadline = episode_started + config.max_episode_seconds
                initial_position = max_position = observation.info.get("x_pos")
                history = ControlHistory(initial_position)
                catalog, executor = control_protocol(config.control_mode, paused=not realtime)
                flight = Flight()
                latencies = deque(maxlen=5)
                response_frames = deque(maxlen=5)
                reward = 0.0
                selected = previous_position = result = active = received = interval = None
                last_entry = None
                last_discard = None
                failed_once = False
                consecutive_stale = 0
                stale_warning_sent = False
                current = Metrics()
                applied, source = executor.current()
                reason = None
                latency = None
                next_frame_at = episode_started
                last_request_frame = None
                while reason is None:
                    if window:
                        window.poll()
                        window.consume_reset()
                        if not window.open:
                            reason = "stopped"
                            break
                    if realtime and perf_counter() >= episode_deadline:
                        reason = "wall_limit"
                        break
                    # Receive even between frames. Applying a choice remains frame-paced.
                    decision = None
                    if in_flight is not None and in_flight["handle"].done():
                        entry, in_flight = in_flight, None
                        try:
                            decision, latency, decided_at = receive(entry)
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
                        if decision.move not in entry["choices"]:
                            raise DecisionError("Risposta Decisions invalida: scelta non offerta")
                        latencies.append(latency)
                        age = decided_at - entry["observed_at"]
                        # Staleness counts game frames: a slower game leaves more time to the model.
                        age_frames = current.counts["frames"] - entry["frame"]
                        response_frames.append(age_frames)
                        if realtime and age_frames > config.max_decision_frames:
                            discard_stale(entry["index"], age_frames, age)
                        else:
                            received = {"index": entry["index"], "choice": decision.move,
                                "observed_at": entry["observed_at"], "decided_at": decided_at,
                                "frame": entry["frame"]}
                    now = perf_counter()
                    if realtime and now >= episode_deadline:
                        reason = "wall_limit"
                        break
                    if (realtime or window) and now < next_frame_at:
                        deadline = min(next_frame_at, episode_deadline) if realtime else next_frame_at
                        wait_for_response(max(0.0, deadline - now))
                        continue
                    on_ground = observation.info.get("on_ground")
                    executor.settle(on_ground)
                    check_completed()
                    if received is not None:
                        chosen, received = received, None
                        consecutive_stale = 0
                        if chosen["choice"] == CONTINUE:
                            current.counts["continues"] += 1
                            applicable = not executor.finished
                            if not applicable:
                                current.counts["not_applicable_decisions"] += 1
                            open_execution(chosen, applicable)
                            event("move_continued" if applicable else "decision_not_applicable",
                                index=chosen["index"], move=executor.move.name if executor.move else None,
                                reason=None if applicable else "move_finished", move_frames=executor.frames)
                        else:
                            # End the old interval only after recording its move replacement.
                            if active is not None and not active["ended"]:
                                end_move("replaced")
                            close_execution("next_decision")
                            start_move({**chosen, "move": catalog[chosen["choice"]]}, observation.info.get("x_pos"))
                            open_execution(chosen)
                    if in_flight is None and (last_request_frame is None or not realtime and executor.finished):
                        submit_request()
                    # Preparation, logging and rendering can cross the wall deadline.
                    if realtime and perf_counter() >= episode_deadline:
                        reason = "wall_limit"
                        break
                    if realtime or (in_flight is None and not executor.finished):
                        applied, source = executor.current()
                        state = {"airborne_frames": on_ground is False}
                        speed = mario_speed(observation)
                        step_started = perf_counter()
                        next_frame_at = step_started + 1 / fps
                        result = game.step(applied, 1)
                        executor.advance(result.frames_executed)
                        observed_at = perf_counter()
                        observation = result.observation
                        current.counts["frames"] += result.frames_executed
                        for name, active_state in state.items():
                            if active_state:
                                current.counts[name] += result.frames_executed
                        flight.step(applied, on_ground, observation.info.get("on_ground"), speed)
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
                                if controller_to_first_frame is None:
                                    controller_to_first_frame = observed_at - controller_started
                            active["frames"] += result.frames_executed
                            active["last_frame_at"] = observed_at
                        else:
                            current.counts["waiting_frames"] += result.frames_executed
                        if interval is not None:
                            interval["frames_executed"] += result.frames_executed
                            interval["waiting_frames" if source == "waiting" else "move_frames"] += result.frames_executed
                            if interval["first_frame_at"] is None:
                                interval["first_frame_at"] = observed_at
                            interval["last_frame_at"] = observed_at
                        log.frame(episode=episode, at=observed_at,
                            index=interval["index"] if interval is not None else None,
                            move_index=active["index"] if active is not None else None,
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
                            executor.settle(observation.info.get("on_ground"))
                            check_completed()
                        # Request uses the resulting pixels and state, never the pre-action screenshot.
                        if reason is None and in_flight is None and (realtime or executor.finished):
                            if not realtime or perf_counter() < episode_deadline:
                                submit_request()
                    if window:
                        timing = f"{latency * 1000:.0f} ms" if latency is not None and in_flight is None else "attesa"
                        diagnostic = f" | {last_discard}" if last_discard is not None else ""
                        move_label = executor.move.name if executor.move else "-"
                        window.show(observation, f"SuperMAIrio | {config.execution_mode} | mosse {current.counts['moves']} | scarti {current.counts['stale_responses']}{diagnostic} | episodio {episode} | {move_label} ({source}) | {timing} | frame {current.counts['frames']} | x={observation.info.get('x_pos', '?')}")
                    if reason is None and (realtime or window or in_flight is not None):
                        # A response may wake us early; only the frame gate advances the game.
                        delay = (max(0.0, next_frame_at - perf_counter())
                            if realtime or (window and in_flight is None) else 1 / fps)
                        if realtime:
                            delay = min(delay, max(0.0, episode_deadline - perf_counter()))
                        wait_for_response(delay)
                ended = perf_counter()
                retire(reason)
                finish_active(reason, ended)
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
                    if current is not None:
                        current.counts["errors"] += 1
                    event("error", index=request_index, message=str(exc))
                    raise
        finally:
            try:
                if current is not None:
                    finish_active(status, ended)
                    finish_episode(status, ended)
                if window is not None:
                    window.close()
            finally:
                if log:
                    try:
                        log.finish(status=status, execution_mode=config.execution_mode,
                            **total.summary(wall_total), episodes=episodes,
                            worker_preparations=preparations,
                            controller_to_first_frame_seconds=controller_to_first_frame,
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
