# Benchmark

An edition of the benchmark plays every participant on both tracks of level 1-1,
under identical conditions, and publishes a leaderboard that anyone can verify
offline.

## Tracks

| | Real-time | Turn-based |
| --- | --- | --- |
| Game during a request | Keeps running at 60 FPS | Paused |
| What the model sees | The state at the frame where its choice will apply, predicted by a shadow emulator | The current state |
| Choice | One of 10 inputs (`PREDICTIVE_MOVES`), held until the next choice | Buttons, then a duration of 2–28 frames, in two questions |
| Previews | Each option ends with the emulated outcome of holding it for at least 30 frames | None |
| Requests | Two identical copies in parallel, the first answer is used | One chain of two questions |
| Episode limit | 3,600 frames or 60 s wall clock | 3,600 frames |
| Session key in the logs | `predictive` | `paused` |

Both tracks use seed 123, the scene read from the NES RAM, no screenshot,
headless execution and a 10 s timeout per decision. The definitions live in
`TRACKS` ([`supermairio/config.py`](../supermairio/config.py)).
`supermairio play --track` uses the same definitions. See
[How it works](how-it-works.md) for the state, options and timing.

Previews are information: they never filter options or suggest a move. Every
input comes from a model choice, and the program never jumps, brakes or reacts
on its own.

## Schedule

Each participant plays 10 finished games per track, with at most 13 starts.
A game is *finished* when it ends in a win, a death, the frame limit or the
wall-clock limit. Death and limits count as losses. An interruption caused by
the provider or by a local stop still uses a start, and is reported separately.

Real-time sessions run first, one at a time, so no other session competes for
the CPU or the network while the game is running. Turn-based sessions follow;
with `--jobs N`, up to N participants play them at the same time. The game waits
for every answer in that track, so concurrency cannot change an outcome, but
latency is measured under concurrent requests: the edition records the number
of jobs and the report states it.

Before every real-time session the emulator throughput is measured. Below
2,000 frames/s the session stops before contacting the model, because slow
previews would delay the model's choices. You can resume the edition when the
machine is idle.

## Scoring

- **Ranking:** wins over finished games, with a 95% Wilson interval. Only
  participants with all 10 finished games are ranked. The others are listed as
  *Unranked*.
- **Next to the ranking:** interruptions (provider), median frames of the
  winning games, frames of the fastest win, median and p95 latency per decision, known cost
  per start, cost coverage, median effective FPS, and late choices in the
  real-time track.
- **Cost** is the sum of `usage.cost` returned by the endpoint. It is *known*
  cost: cancelled or failed requests, and responses without `usage.cost`, may
  have cost more. The coverage column says how many responses reported a cost.

## Participants

[`benchmark.toml`](../benchmark.toml) lists the participants. Each entry has a
unique `name` and either a `model` ID served by `SUPERMAIRIO_ENDPOINT`, or an
`env_prefix` that reads its own endpoint, model and key:

```toml
[[participants]]
name = "configured-model"
env_prefix = "SUPERMAIRIO"

[[participants]]
name = "second-model"
model = "another-model-id"

[[participants]]
name = "local-model"
env_prefix = "SUPERMAIRIO_LOCAL"
```

```dotenv
SUPERMAIRIO_ENDPOINT=https://decisions.example.test/choice
SUPERMAIRIO_MODEL=first-model-id
SUPERMAIRIO_API_KEY=
SUPERMAIRIO_LOCAL_ENDPOINT=http://127.0.0.1:8000/decisions
SUPERMAIRIO_LOCAL_MODEL=local-model
SUPERMAIRIO_LOCAL_API_KEY=
```

Endpoints must be absolute HTTP(S) URLs without credentials, query or fragment.
A key is optional and only sent to its own endpoint. The process environment
overrides `.env`. Endpoints and model IDs are published with the results. Keys
are never written to disk.

## Collecting an edition

```powershell
uv run supermairio bench run                                   # dry run: print the schedule
uv run supermairio bench run --live --edition runs/benchmark-v1
uv run supermairio bench run --live --jobs 4                   # 4 turn-based sessions at a time
```

- `--participants FILE` uses another participants file.
- The edition directory stores `edition.json`: the schedule, participants,
  the number of turn-based jobs,
  track settings, git commit, a hash of the source code and `uv.lock`, the
  Python version, OS and CPU. A later run that finds a different plan, code or
  environment refuses to continue. Start a new directory instead.
- To resume after a stop, rerun the same command. A game recorded as started
  keeps its slot even if the process died during it.

## Publishing and verifying

```powershell
uv run supermairio bench report runs/benchmark-v1 --output results/v1
uv run supermairio bench verify results/v1/edition.zip
```

`report` writes:

- `README.md` with one leaderboard per track,
- `attempts.csv` with every attempt,
- six SVG charts per edition: win rate with intervals, maximum distance, and
  win rate against known cost per start with its Pareto front, for each track,
- `edition.zip` with the edition manifest and every session log.

`verify` replays every recorded input in the emulator, from the edition
directory or from the ZIP archive. It checks frame numbering, position, reward,
outcome and the wall-clock limit against the logs. Latency and cost cannot be
replayed: they are measurements taken during the live run.
