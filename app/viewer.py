"""Pyglet window and input using public APIs only."""

import pyglet
from pyglet.window import key

from app.contracts import Action, Observation, keyboard_action


class GameWindow:
    def __init__(self):
        # Without vsync a flip takes 2 ms instead of 12: the game loop keeps its 60 FPS and its polling.
        self.window = pyglet.window.Window(width=768, height=720, caption="SuperMAIrio — livello 1-1", vsync=False)
        self.open = True
        self.reset_requested = False
        self._pressed: set[int] = set()
        self._image = None
        self.window.push_handlers(
            on_close=self._on_close,
            on_key_press=self._on_key_press,
            on_key_release=self._on_key_release,
            on_deactivate=self._on_deactivate,
            on_draw=self._on_draw,
        )

    def _on_close(self):
        self.open = False
        self._pressed.clear()

    def _on_key_press(self, symbol, modifiers):
        if symbol == key.ESCAPE:
            self.open = False
            self._pressed.clear()
        elif symbol == key.R:
            self.reset_requested = True
            self._pressed.clear()
        else:
            self._pressed.add(symbol)

    def _on_key_release(self, symbol, modifiers):
        self._pressed.discard(symbol)

    def _on_deactivate(self):
        self._pressed.clear()

    def _on_draw(self):
        self.window.clear()
        if self._image is not None:
            self._image.blit(0, 0, width=self.window.width, height=self.window.height)

    def poll(self) -> None:
        self.window.dispatch_events()

    def consume_reset(self) -> bool:
        requested = self.reset_requested
        self.reset_requested = False
        return requested

    def action(self) -> Action:
        return keyboard_action(
            key.LEFT in self._pressed, key.RIGHT in self._pressed,
            key.SPACE in self._pressed, bool(self._pressed & {key.LSHIFT, key.RSHIFT}),
        )

    def show(self, observation: Observation, caption: str) -> None:
        if not self.open:
            return
        rgb = observation.rgb
        height, width, _ = rgb.shape
        self._image = pyglet.image.ImageData(width, height, "RGB", rgb.tobytes(), pitch=-width * 3)
        self.window.set_caption(caption)
        self.window.switch_to()
        self._on_draw()
        self.window.flip()

    def close(self) -> None:
        self.open = False
        self.window.close()
