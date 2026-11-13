# Decisions API

A model takes part in SuperMAIrio through one HTTP endpoint. The endpoint
receives the game state and a multiple-choice question, and returns one of the
offered options. You can put any model behind it: a hosted API, a local server
or a wrapper around your own policy.

```dotenv
SUPERMAIRIO_ENDPOINT=http://127.0.0.1:8000/decisions   # full POST URL
SUPERMAIRIO_MODEL=local-model                          # sent as "model"
SUPERMAIRIO_API_KEY=                                   # optional Bearer token
```

## Request

`POST` to the endpoint, with a JSON body. When a key is configured, the request
also has the header `Authorization: Bearer <key>`.

```json
{
  "model": "local-model",
  "state": [
    {"type": "text", "text": "{\"mario\":{\"on_ground\":true,\"speed\":1.5},\"progress\":{\"x\":40}}"}
  ],
  "questions": {
    "next_action": {
      "type": "choice",
      "instructions": "Choose Mario's next input. ...",
      "criteria": {
        "right_run": "Hold right and B ... Preview: alive after 43 frames, 90 px right, on the ground.",
        "noop": "Release all buttons ..."
      }
    }
  }
}
```

- `state[0].text` is a compact JSON document with the state read from the NES
  RAM. [How it works](how-it-works.md#what-the-model-receives) describes its
  fields.
- With screenshots enabled (not used by the benchmark tracks), `state` also has
  `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}`:
  the 256×240 frame padded with black to 280×280.
- `criteria` maps each offered option ID to its description. Only these IDs
  are valid answers.
- Each request is self-contained: the endpoint never needs a conversation
  history.

### Turn-based track: two questions

The turn-based track sends two requests in sequence for each decision. Both
share the `--request-timeout` budget.

1. A request with the question `buttons`, whose criteria are the button
   combinations.
2. A request with the question `frames`, whose criteria are the durations
   offered for the chosen buttons. The state JSON gains
   `"chosen_buttons": "<first answer>"`.

The two answers form one move, for example `right_run_jump` + `28`.

## Response

```json
{"model": "local-model", "answers": {"next_action": {"type": "choice", "choice": "right_run"}}}
```

| Field | Required | Rule |
| --- | --- | --- |
| `model` | yes | non-empty string |
| `answers.<question>.type` | yes | `"choice"` |
| `answers.<question>.choice` | yes | one of the keys of `criteria` |
| `answers.<question>.confidence` | no | number in [0, 1] |
| `answers.<question>.probabilities` | no | object from offered IDs to numbers in [0, 1] |
| `usage` | no | object; `usage.cost` is summed as known cost |
| `id`, `provider` | no | strings, recorded in the logs |

`<question>` is the question name of the request: `next_action`, `buttons` or
`frames`. Confidence and probabilities are recorded, never used as thresholds.

## Errors and timeouts

| Situation | Effect |
| --- | --- |
| HTTP 5xx, timeout, connection error | Transient: one retry, logged as `request_failed`. A second consecutive failure stops the session |
| HTTP 4xx (including 429) | Stops the session |
| Invalid JSON, unknown structure, or a choice that was not offered | Stops the session |

The timeout covers the whole request: connection, upload and response body. In
the benchmark, a stopped session counts as an interruption and the schedule
continues with the next slot. Connections are kept alive between requests, and
warmed with a `HEAD` request (without credentials) before each episode.

## Checking an endpoint

```powershell
$env:SUPERMAIRIO_TEST_LIVE = '1'
uv run python -m unittest discover -s tests -p test_decisions_live.py -v
Remove-Item Env:SUPERMAIRIO_TEST_LIVE
```

The live test sends two plain-colour images to check that the model reads
pixels, then plays a 12-frame turn-based session. It may incur costs.

## Custom adapters

Every model uses the same adapter, `ChoiceModel`
([`supermairio/agent/prompt.py`](../supermairio/agent/prompt.py)). This keeps
the context identical across models. For research outside the benchmark, the
runners accept any object that implements the `ModelController` protocol
([`supermairio/agent/__init__.py`](../supermairio/agent/__init__.py)):

- `build_request(observation, png, *, frames, previous_move=None,
  previous_position=None, control_context=None)` returns a `DecisionRequest`
  with the `payload` to send and a `trace` to log, both without credentials.
  `control_context["choices"]` lists the options offered at that moment.
- `async decide(payload)` returns a `Decision` whose `move` is one of the offered
  choices.

HTTP transport, timeouts, retries and the concurrent request worker live in
[`supermairio/agent/client.py`](../supermairio/agent/client.py). An adapter that
keeps the transport but uses a different question layout can override
`DecisionsClient.parse_response`.
