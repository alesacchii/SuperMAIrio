"""OpenRouter Decisions protocol and cancellable concurrent-request worker."""

import asyncio
from io import BytesIO
import math
from threading import Thread
from time import perf_counter

import httpx
from PIL import Image

from app.contracts import Decision, Observation
from app.moves import CHOICES

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"


class DecisionError(RuntimeError):
    """An unusable decision; messages never include credentials or raw bodies.

    transient marks provider failures worth one more request: HTTP 5xx, timeouts and connection errors.
    """

    def __init__(self, message, *, transient=False):
        super().__init__(message)
        self.transient = transient


def encode_png(observation: Observation) -> bytes:
    output = BytesIO()
    Image.fromarray(observation.rgb).save(output, format="PNG")
    return output.getvalue()



def _probability(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise DecisionError("Risposta Decisions invalida: probabilità fuori intervallo")
    return float(value)


def parse_decision(body) -> Decision:
    try:
        answer = body["answers"]["next_action"]
        if answer["type"] != "choice":
            raise DecisionError("Il modello non ha restituito una Choice utilizzabile")
        move = answer["choice"]
        if move not in CHOICES:
            raise ValueError()
        model = body["model"]
        if not isinstance(model, str) or not model:
            raise ValueError()
        confidence = _probability(answer["confidence"]) if "confidence" in answer else None
        probabilities = answer.get("probabilities")
        if probabilities is not None:
            if not isinstance(probabilities, dict) or any(key not in CHOICES for key in probabilities):
                raise ValueError()
            probabilities = {key: _probability(value) for key, value in probabilities.items()}
        usage = body.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise ValueError()
        for key in ("id", "provider"):
            if body.get(key) is not None and not isinstance(body[key], str):
                raise ValueError()
        return Decision(move, model, body.get("id"), body.get("provider"), confidence, probabilities, usage)
    except (KeyError, TypeError, ValueError) as exc:
        raise DecisionError("Risposta Decisions invalida: struttura o mossa non riconosciuta") from exc


class OpenRouterClient:
    _http = _http_loop = None

    def __init__(self, api_key: str, timeout: float, *, transport=None):
        self._api_key = api_key
        self.timeout = timeout
        self._transport = transport

    def _client(self):
        # Keep-alive across requests: a new connection costs a TCP+TLS handshake.
        loop = asyncio.get_running_loop()
        if self._http is None or self._http_loop is not loop:
            self._http = httpx.AsyncClient(timeout=self.timeout, transport=self._transport, follow_redirects=False)
            self._http_loop = loop
        return self._http

    async def prepare(self, connections=1):
        """Open pooled connections before the first decision; failures are ignored."""
        if type(self).decide is not OpenRouterClient.decide:
            return  # The adapter uses its own transport.
        client = self._client()
        await asyncio.gather(*(client.head(ENDPOINT) for _ in range(connections)), return_exceptions=True)

    async def aclose(self):
        if self._http is not None:
            http, self._http, self._http_loop = self._http, None, None
            await http.aclose()

    async def decide(self, payload) -> Decision:
        try:
            # Whole-request deadline, including connect, upload and response body.
            async with asyncio.timeout(self.timeout):
                response = await self._client().post(ENDPOINT, json=payload, headers={
                    "Authorization": "Bearer " + self._api_key,
                    "X-OpenRouter-Title": "SuperMAIrio",
                })
                if not response.is_success:
                    raise DecisionError(f"OpenRouter: errore HTTP {response.status_code}",
                        transient=response.status_code >= 500)
                try:
                    body = response.json()
                except ValueError as exc:
                    raise DecisionError("OpenRouter: risposta JSON invalida") from exc
                return parse_decision(body)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise DecisionError(f"OpenRouter: timeout dopo {self.timeout:g} secondi", transient=True) from exc
        except httpx.HTTPError as exc:
            raise DecisionError("OpenRouter: errore di connessione", transient=True) from exc


class DecisionRequestHandle:
    """One submitted request: its own timestamps and a thread-safe future."""

    def __init__(self):
        self.started_at = self.completed_at = None
        self.future = None

    def done(self):
        return self.future.done()

    def result(self):
        return self.future.result()


class DecisionWorker:
    """Persistent event loop for concurrent requests; closing cancels all of them."""

    def __init__(self, client, *, connections=1):
        self.client = client
        self._closed = False
        self._tasks = set()
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._loop.run_forever, name="decisions", daemon=True)
        self._thread.start()
        prepare = getattr(client, "prepare", None)
        if prepare is not None:
            asyncio.run_coroutine_threadsafe(self._tracked(prepare(connections)), self._loop)

    async def _tracked(self, coroutine):
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            return await coroutine
        finally:
            self._tasks.discard(task)

    async def _decide(self, handle, payload):
        handle.started_at = perf_counter()
        try:
            return await self.client.decide(payload)
        finally:
            handle.completed_at = perf_counter()

    def submit(self, payload):
        if self._closed:
            raise RuntimeError("Il worker è chiuso")
        handle = DecisionRequestHandle()
        handle.future = asyncio.run_coroutine_threadsafe(self._tracked(self._decide(handle, payload)), self._loop)
        return handle

    async def _shutdown(self):
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        aclose = getattr(self.client, "aclose", None)
        if aclose is not None:
            await aclose()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result()
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()
            self._loop.close()
