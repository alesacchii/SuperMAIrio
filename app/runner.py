"""Model observation/decision loop, local demo and manual controller."""

from itertools import cycle
from time import perf_counter, sleep

from app.config import Config, DISPLAY_FPS, openrouter_key, parse_config
from app.contracts import Action, StepResult
from app.game import MarioGame
from app.moves import MOVES, MoveExecutor

# Exercise every move once, then keep running and jumping to the right.
DEMO_SEQUENCE = (
    "wait", "walk_right", "walk_left", "high_jump_up", "run_left", "short_jump_left",
    "high_jump_left", "run_right", "run_right", "short_jump_right", "double_jump_right",
)
DEMO_LOOP = ("run_right", "run_right", "high_jump_right")


def demo_moves():
    yield from (MOVES[name] for name in DEMO_SEQUENCE)
    yield from (MOVES[name] for name in cycle(DEMO_LOOP))


def report(episode: int, result: StepResult, frames: int, reward: float) -> str:
    info = result.observation.info
    if info.get("flag_get") or info.get("clear"):
        outcome = "livello completato"
    elif result.truncated:
        outcome = "limite di frame raggiunto"
    elif info.get("death"):
        outcome = "Mario ha perso una vita"
    else:
        outcome = "episodio terminato"
    message = f"Episodio {episode}: {outcome}; frame={frames}, x={info.get('x_pos', '?')}, reward={reward:.1f}"
    print(message)
    return message


def run_local(config: Config) -> None:
    window = None
    try:
        with MarioGame(config.max_frames) as game:
            if not config.headless:
                from app.viewer import GameWindow
                window = GameWindow()
            episode = 1
            observation = game.reset(config.seed)
            moves = demo_moves()
            executor = MoveExecutor()
            upcoming = None
            selected = Action.NOOP
            frames = 0
            reward = 0.0
            finished = False
            caption = "SuperMAIrio — livello 1-1"
            if config.mode == "manual":
                print("Frecce: movimento | Spazio: salto | Shift: corsa | R: reset | Esc: uscita")
            if window:
                window.show(observation, caption)
            while True:
                frame_started = perf_counter()
                if window:
                    window.poll()
                    if not window.open:
                        break
                    if window.consume_reset() and config.mode == "manual":
                        episode += 1
                        observation = game.reset(config.seed)
                        frames, reward = 0, 0.0
                        finished = False
                        caption = "SuperMAIrio — livello 1-1"
                if not finished:
                    if config.mode == "manual":
                        selected = window.action()
                    else:
                        # The demo plays the model's moves through the same executor.
                        on_ground = observation.info.get("on_ground")
                        executor.settle(on_ground)
                        if executor.finished:
                            upcoming = upcoming or next(moves)
                            executor.start(upcoming)
                            upcoming = None
                        selected, _ = executor.current()
                    # One emulator step per tick keeps commands interruptible.
                    result = game.step(selected, 1)
                    observation = result.observation
                    frames += result.frames_executed
                    reward += result.reward
                    if config.mode == "demo":
                        executor.advance(result.frames_executed)
                    label = executor.move.name if config.mode == "demo" and executor.move else selected.value
                    caption = f"SuperMAIrio — episodio {episode} | {label} | frame {frames} | x={observation.info.get('x_pos', '?')}"
                    if result.done:
                        caption = report(episode, result, frames, reward)
                        finished = True
                if window:
                    window.show(observation, caption + (" | R: nuovo tentativo" if finished and config.mode == "manual" else ""))
                if finished and config.mode == "demo":
                    if episode >= config.episodes:
                        break
                    episode += 1
                    observation = game.reset(config.seed)
                    moves = demo_moves()
                    executor = MoveExecutor()
                    upcoming = None
                    frames, reward = 0, 0.0
                    finished = False
                if window:
                    sleep(max(0.0, 1 / DISPLAY_FPS - (perf_counter() - frame_started)))
    finally:
        if window is not None:
            window.close()


def run_model(config: Config) -> None:
    if config.execution_mode == "predictive":
        from app.predictive import run_predictive as run_session
    else:
        from app.model_runner import run_model as run_session
    run_session(config, game_factory=MarioGame, key_provider=openrouter_key)


def run(config: Config) -> None:
    if config.mode == "model":
        run_model(config)
    else:
        run_local(config)


def main(argv: list[str] | None = None) -> int:
    config = parse_config(argv)
    try:
        run(config)
    except KeyboardInterrupt:
        print("Sessione arrestata.")
        return 130
    except Exception as exc:
        print(f"Impossibile completare la sessione: {exc}")
        return 1
    return 0
