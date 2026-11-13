# Results format

Every model session writes its own directory under `runs/`, which git ignores.
Benchmark editions use the same format, one directory per session. The
results version is **6**.

```
runs/<session>/
  config.json      every option, protocol, prompt revision, choice catalog; no credentials
  events.jsonl     requests, decisions, execution intervals, errors, episode starts and ends
  frames.jsonl     one record per emulator frame
  summary.json     session and per-episode summaries, including interrupted episodes
  screenshots/     PNGs sent to the model, only with --save-screenshots
```

## Files

**`config.json`** stores the session options, `results_version`,
`session_started_utc`, `endpoint`, the target FPS and the choice catalog. It
also stores `protocol` with its `prompt_revision`:

| Protocol | Used by | Prompt revision |
| --- | --- | --- |
| `choice-buttons-predictive-v1` | Real-time track | 1 |
| `choice-timed-buttons-v1` | Turn-based track, timed realtime | 1 |
| `choice-buttons-v1` | Direct buttons, realtime or paused | 13 |
| `choice-scene-v5` | Calibrated moves | 5 |

**`events.jsonl`** records requests, decisions, errors, discards,
cancellations and outcomes. For each interval governed by one choice it adds an
`execution` record, written when the next choice arrives or the episode ends:
index, choice, applicability, start and end frames, times and positions,
`move_frames`, `waiting_frames` and `move_end`. `episode_started` is written at
every start, even if the process dies before `episode_end`.

In the real-time track, each request also records `start_frame`, `target_frame`,
`hold_frames`, `role` (`chain`, `resync`, `branch`) and the projection and
preparation times. `choice_applied` reports `late_frames` and
`prediction_mismatch`.

**`frames.jsonl`** has one `frame` record per emulator frame: buttons, their
source, position, reward and status. `index` is the decision governing the
frame (`null` before the first one). `move_index` is the decision that started
the current sequence.

**`summary.json`** summarizes the session and every attempt: reward, initial,
final and maximum position, death, completion, end reason, counters and
timings. In the real-time track it also counts `late_choices`,
`prediction_mismatches`, `resyncs` and the parallel and speculative requests.

## Metrics

All times use `perf_counter`, one monotonic clock. Distributions report the
sample count, median and nearest-rank p95. Both are `null` when there are no
samples.

| Metric | Definition |
| --- | --- |
| `request_seconds` | From the actual start in the worker to the validated answer. Includes network and service; this is not pure inference time |
| `dispatch_seconds` | From submission to the worker to the actual start of the request |
| `preparation_seconds` | PNG encoding, payload construction and screenshot saving |
| `polling_seconds` | From the validated answer to its pickup by the runner |
| `observation_age_seconds` / `_frames` | From the observation to the start of the chosen input, including the wait for the right frame |
| `observation_to_first_frame_seconds` / `_last_frame_seconds` | From the observation to the first or last frame of the chosen input |
| `decisions_per_second` / `moves_per_second` | Decisions received or inputs started, over the attempts' wall time |
| `requests_per_second` | Requests sent, cancelled ones included, over the attempts' wall time |
| `effective_fps` | Frames executed over the attempts' wall time |
| `controller_to_first_frame_seconds` | From entering the controller to the first applied frame, including setup and reset |

An attempt's wall time includes preparation and waits. It excludes setup, reset
and closing the worker, which `worker_preparations` measures separately.

## Cost

`known_cost` sums the numeric `usage.cost` values of received decisions. It is
`null` when no response reports a cost. `cost_known_requests` and
`cost_missing_received_requests` give its coverage. Cancelled or failed requests
may have used credit that no response reported, so known cost is a lower bound,
never the total.

## Failures

Transient errors (HTTP 5xx, timeout, connection) get one retry, logged as
`request_failed` and counted in `retried_requests`. A second consecutive
failure, a 4xx response or an invalid answer stops the session with exit code 1.
Partial intervals and summaries are still written. The end of an episode, Esc,
closing the window and Ctrl+C cancel the request in flight. No answer ever
crosses a reset.
