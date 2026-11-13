# How it works

The model controls Mario through repeated decisions. For each decision, the
program reads the game, builds a request, gets one choice back and turns it into
NES buttons.

1. Read the game state from the emulator RAM (and the screenshot, if enabled).
2. Build a request: fixed instructions, the state, and the options allowed at
   that moment, each with its description.
3. The model answers with **one** option.
4. Check that the option was offered (otherwise the session stops) and map it to
   the NES buttons A, B, left and right.
5. The game advances; repeat.

Every request is self-contained. The model has no conversation history.

## What the model receives

**Instructions.** One fixed text per protocol. It gives the goal (reach the
flag; survive first, then advance, then take the mushroom) and explains the
controls: when A starts a jump, how long to hold it for a low or high jump, and
B to run. It also says when the choice applies and how long it lasts. A short
legend and a game guide follow: Goombas, Koopas and shells, pits, pipes,
stairs, ? blocks, mushrooms, Mario's inertia and the limit of the view. The
instructions never say which option to pick.

**State.** A compact JSON document read from the NES RAM. With `--no-scene`,
only Mario's size, ground contact and x remain.

| Field | Content |
| --- | --- |
| `mario` | size, `on_ground`, `vertical` (rising/falling), `speed` in px/frame, screen position; on the ground `jump_reach_px`, the measured reach of a low and a high jump at the current speed |
| `progress` | `x`, the flag position and the level percentage |
| `nearby.enemies` | type, `dx`/`dy` from Mario, direction and speed; some protocols add `contact_in_frames` or `dx_at_response` |
| `nearby.obstacle_ahead` | first wall ahead (pipe, step, block) and its height in tiles |
| `nearby.pit_ahead` | first pit under or ahead of Mario: distance, visible width, which edges are visible |
| `nearby.blocks`, `items`, `surfaces` | reachable ? blocks and bricks, power-ups, visible solid surfaces to land on |
| `move` | current input, for how many frames, when it ends; in the real-time track `hold_frames`, how long the next choice will stay active |
| `input` | buttons actually pressed and for how many frames |
| `jump_observation` | in the air: speed and A-press duration of the current jump |
| `warnings` | only when relevant: enemy close, block above a jump starting now, no forward progress for N frames, time almost up |

Distances are in pixels (16 px = 1 tile). `dx` is the object's left edge minus
Mario's, and `dy` the height of the object's bottom above Mario's feet. The
state only reports what is on screen: hidden blocks never appear. RAM addresses
and codes are calibrated on level 1-1 ([`scene.py`](../supermairio/game/scene.py)).

**Screenshot** (off in both benchmark tracks, see `--image`): the 256×240 frame
padded with black to 280×280. Every model gets the same padding.

**Options.** IDs and descriptions of the choices allowed at that moment. In the
real-time track every description ends with the emulated outcome of that
option, for example `Preview: Mario dies after 21 frames.` or
`Preview: alive after 43 frames, 90 px right, on the ground.`

## What the model can choose

| Protocol | Options | After the choice |
| --- | --- | --- |
| Real-time track (`PREDICTIVE_MOVES`) | `noop`, `left`, `left_run`, `right`, `right_run`, `right_jump`, `right_run_jump`, `right_hop`, `right_run_hop`, `right_run_then_jump` | Held until the next choice. `*_hop` holds A for 8 frames, then releases every button. `right_run_then_jump` holds right+B for 4 frames, then right+B+A |
| Turn-based track (`TIMED_MOVES`) | Buttons, then duration: 2, 4, 8, 16 or 28 frames with A (the jump height), 2, 4 or 8 without | Those buttons for those frames, then the next decision |

A jump input chosen on the ground while A is already held starts with one frame
without A, so that the NES sees a new press. In the air, A stays held. This frame
is part of the chosen option and is stated in its description.

## When the choice applies: the real-time track

At 60 FPS, a model that answers in 300 ms sees a state 18 frames old by the
time its choice arrives. The real-time track removes that gap without ever
pausing the game:

1. The inputs until the next choice are already known: they are the choices
   already made.
2. A **shadow emulator** restores a snapshot of the game and replays those
   inputs (`MarioGame.snapshot` and `simulate`, in worker threads; the native
   emulator releases the GIL) up to the frame where the requested choice will
   apply.
3. The model receives the state of *that* frame.
4. An early answer waits for its frame. A late answer applies at once, and the
   next predictions restart from the real state (`resync`).

The distance between two choices (`move.hold_frames`, typically 36–60 frames)
comes from the 95th percentile of the measured latency and preparation time, so
that answers arrive in time. With previews enabled, while a request is in
flight, the shadow already projects the future state for each possible answer.

**Previews.** For every option, a separate emulator holds that option for at
least 30 frames, or the expected hold plus 10 frames if longer. The preview
continues while Mario is in the air or above a pit, and its outcome is appended
to the option's description.

**Parallel copies.** Each request is sent twice. The first valid answer is
used, and the other is recorded for its cost. This removes occasional provider
stalls and shortens the latency tail, at twice the cost.

**Limits.** The native snapshot does not carry every byte of state between
instances. Rare 1–2 px differences between predicted and real position are
expected. They are logged as `prediction_mismatch` and followed by a resync.
The cadence depends on the CPU: emulation throughput is logged as
`emulation_throughput` at startup, and the benchmark requires at least
2,000 frames/s.

## What the program never does

Every input comes from a model choice. The program never jumps, brakes, turns,
releases buttons or reacts to landings and dangers on its own. The only fixed
sequences live *inside* an option the model chose, and are stated in its
description: the turn-based durations, the hop and run-up jumps, and the
frame without A that makes a new jump possible. Before the first choice of an
episode, Mario stands still. Previews, warnings and distances are information:
they never remove options or point to one.
