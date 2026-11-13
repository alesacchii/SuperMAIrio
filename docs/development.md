# Development

## Setup

The project targets **Python 3.13** and uses [uv](https://docs.astral.sh/uv/).

```powershell
uv sync --locked
uv run supermairio --help
uv run supermairio play --mode demo --headless --max-frames 120   # smoke test, no endpoint
```

If the default uv cache is not accessible, use `uv --cache-dir .uv-cache`.

**Pinned dependencies.** The emulator is `gym-super-mario-bros==9.1.0` on
`nes-py==9.0.1`, environment `SuperMarioBros-1-1-v0`. uv overrides
**pyglet to 1.5.31**: nes-py's upper bound would select 1.5.21, which fails on
Windows with Python 3.13 (`COMPointer`). Change dependencies through
`pyproject.toml` and `uv lock`, never by editing `.venv`. The ROM ships with the
backend package. Do not add ROMs or `.nes` files to the repository.

## Code layout

| Package | Modules | Responsibility |
| --- | --- | --- |
| `supermairio` | `cli.py`, `config.py`, `contracts.py` | Command line, validated configuration and track definitions, shared types (`Action`, `Observation`, `Decision`, …) |
| `supermairio.game` | `emulator.py` | `MarioGame`: frame stepping, reset, snapshot and `simulate` for shadow emulators |
| | `scene.py` | The scene read from the NES RAM, calibrated on 1-1 |
| | `control.py`, `moves.py` | Choice catalogs and executors for every protocol |
| | `viewer.py` | Pyglet window and keyboard |
| `supermairio.agent` | `client.py` | Decisions HTTP client, response validation, cancellable request worker |
| | `prompt.py` | `ChoiceModel`: instructions, state JSON and options, identical for every model |
| `supermairio.runtime` | `predictive.py` | Real-time track loop: shadow emulators, previews, parallel copies |
| | `loop.py` | Paused and realtime loops |
| | `play.py` | Demo, keyboard and model session dispatch |
| | `session.py`, `metrics.py` | Session logs and measurements |
| `supermairio.benchmark` | `edition.py` | Participants, schedule, resumable collection |
| | `report.py` | Leaderboard, CSV, charts, archive and offline verification |
| | `replay.py` | GIF replays of recorded episodes |

The packages keep contracts, emulator, interface, adapter, transport and
measurements apart.

### The game interface

```python
from supermairio.contracts import Action
from supermairio.game.emulator import MarioGame

with MarioGame(max_frames=3600) as game:
    observation = game.reset(seed=123)
    result = game.step(Action.RIGHT_JUMP, frames=6)
    if result.done:
        observation = game.reset(seed=123)
```

- `Observation.rgb` is an independent `uint8` copy of shape 240×256×3. `info`
  holds position, time, lives, status, `on_ground` and `scene`.
- `step` replaces the previous buttons entirely; `noop` releases them.
  `frames_executed` can be lower than requested when the episode ends.
- Call `reset` before the first step, after the end of an episode and after a
  failed step. A closed game cannot be restarted.

## Tests

```powershell
uv run python -m unittest discover -s tests -v
uv run python -m unittest discover -s tests -p test_predictive.py -v   # one module
```

The standard suite runs offline, with simulated clocks, workers and HTTP
transports, and makes no paid calls. It covers configuration and the CLI,
buttons and executors, the RAM scene on the real level, the request worker and
its timeouts, retries and cancellation, the paused, realtime and predictive
loops, logs and metrics, and benchmark collection, report and verification.
`tests/fixtures/jump_replays.json` replays three recorded deaths (pit, Goomba,
stairs) offline, with seed and inputs only.

Two suites are opt-in. Both read the flag from the process environment, not
from `.env`.

```powershell
# Window checks: needs a desktop with OpenGL; saves captures to .local/verification/
$env:SUPERMAIRIO_TEST_DISPLAY = '1'
uv run python -m unittest discover -s tests -p test_viewer.py -v
Remove-Item Env:SUPERMAIRIO_TEST_DISPLAY

# Live endpoint check: uses SUPERMAIRIO_* settings and may incur costs
$env:SUPERMAIRIO_TEST_LIVE = '1'
uv run python -m unittest discover -s tests -p test_decisions_live.py -v
Remove-Item Env:SUPERMAIRIO_TEST_LIVE
```

Make sure `SUPERMAIRIO_TEST_LIVE` is unset before running the standard suite.

## Continuous integration

[`.github/workflows/tests.yml`](../.github/workflows/tests.yml) runs the standard
suite and the demo smoke test on Ubuntu and Windows for every push to `master`
and every pull request.

## Changing the benchmark

The track definitions (`TRACKS` in `config.py`), the prompt (`agent/prompt.py`),
the choice catalogs and the calibrated durations (`game/control.py`,
`game/moves.py`) define what the benchmark measures. Change them only with a
new benchmark version: an edition records a hash of the source code and refuses
to resume after a change. When a change alters what the logs mean, update
`RESULTS_VERSION` in `runtime/session.py` and the
[results format](results-format.md).
