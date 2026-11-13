# SuperMAIrio

[![tests](https://github.com/alesacchii/SuperMAIrio/actions/workflows/tests.yml/badge.svg)](https://github.com/alesacchii/SuperMAIrio/actions/workflows/tests.yml)
![Python 3.13](https://img.shields.io/badge/python-3.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**A real-time benchmark for System 1 decision models, played on Super Mario Bros 1-1.**

System 1 models answer in a single fast step: no chain of thought, one choice
from a list. SuperMAIrio measures how well they control a game that does not
wait for them. At 60 FPS a 300 ms answer costs 18 frames, so latency is as much
part of the score as the quality of the choice.

Any model behind an HTTP endpoint that speaks the small
[Decisions API](docs/decisions-api.md) can take part. Endpoint and model ID come
from the environment: there is no provider-specific code.

## The two tracks

| Track | What the model decides | When the choice applies | Limit |
| --- | --- | --- | --- |
| **Real-time** | One of 10 button inputs, held until its next choice | The game never pauses. A shadow emulator predicts the state at the frame where the choice will apply, and that is what the model sees | 3,600 frames or 60 s wall clock |
| **Turn-based** | Buttons, then how many frames to hold them (two questions) | The game waits for both answers | 3,600 frames |

Every participant gets the same instructions, the same state read from the NES
RAM and the same options. Only the model ID changes. Each model plays 30
finished games per track, scheduled in three alternating blocks. The leaderboard
ranks wins with a 95% Wilson interval and reports latency, cost and
interruptions next to them. [Rules and scoring](docs/benchmark.md).

```mermaid
flowchart LR
    G[NES emulator<br/>60 FPS, never paused] -->|snapshot| S[Shadow emulator<br/>replays inputs already chosen]
    S -->|state at the frame<br/>where the choice applies| P[Prompt<br/>state + options + previews]
    P -->|HTTP POST| M[(Your model<br/>Decisions API)]
    M -->|one choice| G
```

## Quickstart

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```powershell
uv sync --locked
cp .env.example .env    # set SUPERMAIRIO_ENDPOINT, SUPERMAIRIO_MODEL, optional SUPERMAIRIO_API_KEY
```

**Benchmark**

```powershell
uv run supermairio bench run                       # print the schedule, no requests
uv run supermairio bench run --live                # collect the edition (may incur costs)
uv run supermairio bench report runs/benchmark-v1 --output results/v1
uv run supermairio bench verify results/v1/edition.zip
```

Participants are listed in [`benchmark.toml`](benchmark.toml): several models
on one endpoint, or one endpoint per model.

**Play**

```powershell
uv run supermairio play                            # the configured model, real-time track settings
uv run supermairio play --track turn-based         # exactly as in the turn-based track
uv run supermairio play --mode manual              # keyboard: arrows, Space, Shift
uv run supermairio play --mode demo                # scripted demo, no endpoint needed
```

The ROM comes with the `gym-super-mario-bros` dependency.

## Results

No edition has been published yet. A published edition includes its
leaderboard, every attempt as CSV, and an archive of the logs. Anyone can
replay that archive offline and check every reported position and outcome.

## Documentation

| | |
| --- | --- |
| [Benchmark](docs/benchmark.md) | Tracks, schedule, scoring, participants, collecting and publishing an edition |
| [Decisions API](docs/decisions-api.md) | The HTTP contract a model endpoint implements |
| [How it works](docs/how-it-works.md) | What the model receives and chooses, and the predictive loop |
| [Play](docs/play.md) | `supermairio play` options and keyboard controls |
| [Results format](docs/results-format.md) | Session logs in `runs/` and the definition of each metric |
| [Experimental modes](docs/experimental-modes.md) | Research protocols outside the benchmark |
| [Development](docs/development.md) | Code layout, tests and the dependency pins |

## Repository layout

```
supermairio/
  game/        emulator, RAM scene, button protocols, window
  agent/       Decisions client and the shared prompt
  runtime/     predictive and turn-based loops, session logs, metrics
  benchmark/   edition schedule, report, offline verification, GIF replays
  cli.py       the `supermairio` command
tests/         offline test suite (live and display checks are opt-in)
docs/          documentation
```

## License

MIT, see [LICENSE](LICENSE). SuperMAIrio is an independent research project
with no affiliation to Nintendo. Super Mario Bros is a trademark of Nintendo.
The ROM is provided by `gym-super-mario-bros` under
[its own terms](https://github.com/Kautenja/gym-super-mario-bros/blob/master/LICENSING.md).
