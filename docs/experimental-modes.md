# Experimental modes

These protocols predate the benchmark and remain available through
`supermairio play` for research. They are not part of any leaderboard, and
results from different protocols are not comparable. The logs record each
session's `protocol` and `prompt_revision` (see [Results format](results-format.md)).

| Execution × control | Protocol ID | Notes |
| --- | --- | --- |
| `realtime` × `buttons` | `choice-buttons-v1` | Game keeps running; the model sees the state when the request left |
| `paused` × `buttons` | `choice-buttons-v1` | Turn-based, **one frame per choice** |
| `realtime` × `timed` | `choice-timed-buttons-v1` | One question with every button+duration pair |
| `realtime` / `paused` × `moves` | `choice-scene-v5` | Calibrated, interruptible move scripts |

## Realtime execution (`--execution-mode realtime`)

```powershell
uv run supermairio play --execution-mode realtime --headless
uv run supermairio play --execution-mode realtime --game-fps 30   # more time per decision
```

The game keeps running at `--game-fps` (at most 60) with the buttons of the last
choice, and there is no prediction. The state sent is the one of the frame where
the request left, so it is already 13–26 frames old when the answer arrives.
Only one request is in flight at a time. The next request starts one frame after
a choice is applied.

- **Stale answers.** An answer is discarded if the game has advanced more than
  `--max-decision-frames` (default 120) since its observation. The window shows
  the last discarded age. After three consecutive stale answers, the terminal
  prints one warning per episode.
- **Projection.** When an estimate exists, enemies, items, walls and pits gain
  `dx_at_response`: their distance when the answer is expected to arrive, at
  constant speeds (`dx + (object speed − Mario speed) × response_in_frames`).
  `response_in_frames` is the median of the last five observation-to-answer
  intervals. Acceleration, turns and collisions can make the projection wrong.
- **Slow provider.** An episode whose median latency is above 0.6 s is flagged
  `slow_provider` in the summary.

## Direct buttons (`--control-mode buttons`)

Ten NES combinations: `noop`, `jump`, `left`, `left_jump`, `left_run`,
`left_run_jump` and the four `right` equivalents. A choice replaces the buttons
exactly and holds them until the next choice. Repeating a choice does not
release A: a new jump needs a choice without A first. The harness never adds a
release, never waits for a landing and does not offer `continue`.

In `paused`, each choice runs **one frame**, then the game waits. This is not
equivalent to running a complete move. `jump_observation` reports the initial
A-press speed, the frames elapsed, the actual press duration and the calibrated
total reach at that speed. It is not a landing prediction. Landing estimates are
omitted, because the harness does not know when the model will release A.

## Timed buttons in realtime (`--control-mode timed`)

In the turn-based track, `timed` asks two questions: buttons, then duration. In
realtime a second call would double the delay, so the adapter asks **one**
question with every button+duration pair (for example `right_run_jump_28`). If
no new choice arrives before the duration ends, all buttons are released. The
durations are the turn-based ones: 2, 4, 8, 16 or 28 frames with A, and 2, 4 or
8 without. Each description gives the measured effect (jump height 27–34 px up
to 64–86 px).

## Calibrated moves (`--control-mode moves`)

The model picks a scripted move. All moves can be interrupted by the next choice.

| Choice | Sequence |
| --- | --- |
| `wait` | No button for 10 frames |
| `walk_right` / `walk_left` | Direction for 16 frames |
| `run_right` / `run_left` | Direction + B for 16 frames |
| `short_jump_right` / `short_jump_left` | Direction + A + B for 8 frames, then direction + B until landing |
| `high_jump_right` / `high_jump_left` | Direction + A + B for 28 frames, then direction + B until landing |
| `double_jump_right` | Two high jumps, landing and releasing A in between |
| `high_jump_up` | A for 28 frames, then no button until landing |
| `continue` | Only while a move is active: carries on, never restarts it |

- Landing is read from RAM address `0x001D` (`info["on_ground"]`). A segment
  that lasts until landing is capped at 60 frames.
- A new jump sequence while A is held starts with one release frame. At the
  end of a sequence, every button is released.
- `continue` is offered only while a move is active in the observation. If the
  move ends while the request is in flight, the answer is not applicable: no
  restart, one frame without buttons, then a new request. A `continue` that was
  not offered is an invalid answer.
- `move.landing` estimates the frames until Mario lands back at take-off height
  from `JUMP_AIRTIME` (short 27/30/29 and high 44/48/50 frames at the three
  speed bands, on flat ground). After a jump is replaced in the air, the
  estimate stays unknown until the next take-off from the ground.
- The demo (`--mode demo`) plays these moves through the same executor.

## Without the RAM scene (`--no-scene`)

The runner removes the scene from the observation, and the prompt asks the model
to work out everything from the screenshot. Use it to compare the two kinds of
perception. All adapters work without a scene.
