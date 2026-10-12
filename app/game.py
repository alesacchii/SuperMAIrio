"""Frame-based game adapter; knows nothing about controllers or models."""

from copy import deepcopy
from numbers import Integral
from typing import Any

import gymnasium as gym
import gym_super_mario_bros  # noqa: F401 -- registers Gymnasium environments
from nes_py.wrappers import JoypadSpace

from app.config import ENVIRONMENT_ID
from app.contracts import Action, BUTTONS, Observation, StepResult
from app.scene import PLAYER_FLOAT, read_scene


def require_frames(frames: int) -> None:
    if isinstance(frames, bool) or not isinstance(frames, Integral) or frames <= 0:
        raise ValueError("frames deve essere un intero positivo")


class MarioGame:
    def __init__(self, max_frames: int = 3600, *, environment: Any = None):
        require_frames(max_frames)
        self._actions = tuple(Action)
        self._ready = False
        self._closed = False
        if environment is not None:
            # Inject a discrete environment for lifecycle tests.
            self._env = environment
        else:
            raw = gym.make(ENVIRONMENT_ID, render_mode="rgb_array", max_episode_steps=int(max_frames))
            try:
                self._env = JoypadSpace(raw, [list(BUTTONS[action]) for action in self._actions])
            except BaseException:
                raw.close()
                raise

    def _observation(self, rgb: Any, info: dict) -> Observation:
        # nes-py exposes a live view of the native buffer. Own every returned frame.
        info = deepcopy(info)
        ram = getattr(getattr(self._env, "unwrapped", None), "ram", None)
        if ram is not None:
            snapshot = bytes(ram)
            # SMB player float state: 0 on the ground, otherwise jumping, falling or on the flagpole.
            info["on_ground"] = snapshot[PLAYER_FLOAT] == 0
            info["scene"] = read_scene(snapshot)
        return Observation(rgb.copy(order="C"), info)

    def reset(self, seed: int | None = None) -> Observation:
        if self._closed:
            raise RuntimeError("il gioco è chiuso")
        self._ready = False
        rgb, info = self._env.reset(seed=seed)
        observation = self._observation(rgb, info)
        self._ready = True
        return observation

    def step(self, action: Action | str, frames: int = 6) -> StepResult:
        require_frames(frames)
        try:
            selected = Action(action)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"azione non valida: {action!r}") from exc
        if self._closed or not self._ready:
            raise RuntimeError("eseguire reset prima di un comando o dopo la fine dell'episodio")
        reward_total = 0.0
        try:
            for executed in range(1, int(frames) + 1):
                rgb, reward, terminated, truncated, info = self._env.step(self._actions.index(selected))
                reward_total += float(reward)
                if terminated or truncated:
                    self._ready = False
                    break
            return StepResult(self._observation(rgb, info), reward_total, executed, bool(terminated), bool(truncated))
        except BaseException:
            self._ready = False
            raise

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._ready = False
            self._env.close()

    def __enter__(self) -> "MarioGame":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
