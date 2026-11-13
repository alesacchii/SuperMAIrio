# Play

`supermairio play` runs level 1-1 outside the benchmark: with the configured
model, with a scripted demo or from the keyboard. It reads the same
`SUPERMAIRIO_ENDPOINT`, `SUPERMAIRIO_MODEL` and `SUPERMAIRIO_API_KEY` as the
benchmark (process environment first, then `.env`). Without options it uses
the real-time track settings.

```powershell
uv run supermairio play                                # model, real-time track settings, with a window
uv run supermairio play --track turn-based             # exactly as in the turn-based track
uv run supermairio play --headless --episodes 10       # ten attempts, no window
uv run supermairio play --model another-model-id       # another model on the same endpoint
uv run supermairio play --save-screenshots             # keep the images sent to the model
uv run supermairio play --mode manual                  # keyboard
uv run supermairio play --mode demo                    # scripted demo, no endpoint needed
uv run supermairio play --help                         # every option
```

Every model session writes a directory under `runs/`, described in
[Results format](results-format.md). Turn any of them into a GIF:

```powershell
uv run supermairio replay runs/<session> --episode 1 --scale 2 --output replay.gif
```

The replay runs the recorded inputs in the emulator. It stops if a position
differs from the log, so the GIF shows exactly what happened.

## Keyboard

| Key | Action |
| --- | --- |
| Left / Right arrows | Move |
| Space | Jump (NES A) |
| Left or right Shift | Run (NES B), with a direction |
| R | Restart the attempt, also after it ended |
| Esc or closing the window | Quit |
| Ctrl+C in the terminal | Quit with exit code 130 |

Combinations are allowed. Pressing both directions cancels the movement; jump
still works. Releasing a key or losing focus releases its buttons. After a
manual attempt ends, the game waits for R.

## Options

Options that do not apply to the chosen mode are rejected before the game
opens.

**Session**

| Option | Default | Effect |
| --- | --- | --- |
| `--mode {model,demo,manual}` | `model` | `demo` plays a fixed move sequence that exercises the controls (not a strategy); `manual` needs a window |
| `--headless` | window | No window (model and demo). Real-time modes keep their game speed |
| `--episodes N` | `1` | Independent attempts (model and demo) |
| `--seed N` | `123` | Environment reset seed |
| `--max-frames N` | `3600` | Frame limit per attempt (one minute at 60 FPS) |
| `--max-episode-seconds S` | `60` | Wall-clock limit per attempt, in `predictive` and `realtime` |
| `--save-screenshots` | off | Keep the images sent to the model in `runs/<session>/screenshots/`. Turns `--image` on |

**Model and requests**

| Option | Default | Effect |
| --- | --- | --- |
| `--track {realtime,turn-based}` | none | Use the exact settings of a benchmark track. Rejects options that would change them |
| `--model ID` | `SUPERMAIRIO_MODEL` | Model ID sent to the endpoint |
| `--request-timeout S` | `10` | Budget for a whole decision, including both questions in the turn-based protocol |
| `--execution-mode {predictive,paused,realtime}` | `predictive` (`realtime` with `timed` or `moves`) | `predictive`: the real-time track loop. `paused`: turn-based. `realtime`: [experimental](experimental-modes.md) |
| `--control-mode {buttons,timed,moves}` | `buttons` | `buttons`: held until the next choice. `timed`: buttons and duration. `moves`: [experimental](experimental-modes.md). `predictive` requires `buttons` |

**Observation**

| Option | Default | Effect |
| --- | --- | --- |
| `--scene` / `--no-scene` | on | Send the state read from the RAM. Without it, the screenshot is the only observation and is turned on |
| `--image` / `--no-image` | off in `predictive`, on otherwise | Send the screenshot. The scene and the image cannot both be off |

**Predictive mode**

| Option | Default | Effect |
| --- | --- | --- |
| `--choice-preview N` | `30` | Append to each option the emulated outcome of holding it for at least N frames. `0` disables previews |
| `--parallel-requests N` | `2` | Send N identical copies of each request and use the first answer. Cost scales with N |
| `--decision-frames N` | `0` (minimum 8) | Minimum frames between two choices. The real distance grows when the measured latency requires it |
| `--speculative-width N` | `0` | Experimental: while an answer is in flight, request the next choice for each of the N likeliest answers. Choices every 8–18 frames at N times the cost |
| `--game-fps N` | `60` | Game speed in `predictive` and `realtime`, at most 60 |

The predictive mode is CPU-intensive: it measures emulation throughput at
startup and warns below 2,000 frames/s.

## Window and terminal

In predictive mode the window title shows the episode, the input being held,
the number of choices, the frames between two choices, the frame and the
position. The terminal prints the outcome and the known cost of each episode,
then the session total.
