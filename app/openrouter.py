"""OpenRouter Decisions protocol and cancellable concurrent-request worker."""

import asyncio
from io import BytesIO
import math
import sys
from threading import Event, Thread
from time import perf_counter, sleep

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


def parse_decision(body, choices=CHOICES, *, question="next_action") -> Decision:
    try:
        answer = body["answers"][question]
        if answer["type"] != "choice":
            raise DecisionError("Il modello non ha restituito una Choice utilizzabile")
        move = answer["choice"]
        if move not in choices:
            raise ValueError()
        model = body["model"]
        if not isinstance(model, str) or not model:
            raise ValueError()
        confidence = _probability(answer["confidence"]) if "confidence" in answer else None
        probabilities = answer.get("probabilities")
        if probabilities is not None:
            if not isinstance(probabilities, dict) or any(key not in choices for key in probabilities):
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
        """Warm pooled connections within the request budget; failure is non-fatal."""
        if type(self).decide is not OpenRouterClient.decide:
            return "skipped"  # The adapter uses its own transport.
        client = self._client()
        try:
            async with asyncio.timeout(self.timeout):
                responses = await asyncio.gather(*(client.head(ENDPOINT) for _ in range(connections)),
                    return_exceptions=True)
            # Even a 4xx/405 response has warmed the connection. No credentials are sent.
            if any(isinstance(item, (TimeoutError, httpx.TimeoutException)) for item in responses):
                return "timeout"
            return "failed" if any(isinstance(item, BaseException) for item in responses) else "ready"
        except (TimeoutError, httpx.TimeoutException):
            return "timeout"

    async def aclose(self):
        if self._http is not None:
            http, self._http, self._http_loop = self._http, None, None
            await http.aclose()

    def parse_response(self, body, payload) -> Decision:
        """Adapters may decode other question layouts without duplicating HTTP."""
        return parse_decision(body, payload["questions"]["next_action"]["criteria"])

    async def post(self, payload):
        """One Decisions call; returns the JSON body. Callers own the deadline."""
        response = await self._client().post(ENDPOINT, json=payload, headers={
            "Authorization": "Bearer " + self._api_key,
            "X-OpenRouter-Title": "SuperMAIrio",
        })
        if not response.is_success:
            raise DecisionError(f"OpenRouter: errore HTTP {response.status_code}",
                transient=response.status_code >= 500)
        try:
            return response.json()
        except ValueError as exc:
            raise DecisionError("OpenRouter: risposta JSON invalida") from exc

    async def exchange(self, payload) -> Decision:
        """Adapters may chain several calls; all of them share the decide deadline."""
        return self.parse_response(await self.post(payload), payload)

    async def decide(self, payload) -> Decision:
        try:
            # Whole-request deadline, including connect, upload and response body.
            async with asyncio.timeout(self.timeout):
                return await self.exchange(payload)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise DecisionError(f"OpenRouter: timeout dopo {self.timeout:g} secondi", transient=True) from exc
        except httpx.HTTPError as exc:
            raise DecisionError("OpenRouter: errore di connessione", transient=True) from exc


class DecisionRequestHandle:
    """One submitted request: its own timestamps and a thread-safe future."""

    def __init__(self):
        self.started_at = self.completed_at = None
        self.future = None
        self._ready = Event()
        self._cancel_callback = None
        self._task = None
        self._cancel_requested = False

    def bind(self, future):
        self.future = future
        future.add_done_callback(lambda _: self._ready.set())

    def wait(self, timeout):
        """Wake for success, failure or cancellation, without consuming the result."""
        if sys.platform == "win32" and timeout is not None and timeout > 0:
            # Windows Event.wait can round a short timeout to a coarse OS tick.
            # Python 3.13 sleep uses a high-resolution timer. Poll with bounded
            # sleeps so frame deadlines stay precise and replies wake us promptly,
            # without spinning or changing the system timer resolution.
            deadline = perf_counter() + timeout
            while not self._ready.is_set():
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    return False
                sleep(min(remaining, 0.002))
            return True
        return self._ready.wait(timeout)

    def done(self):
        return self.future.done()

    def result(self):
        return self.future.result()

    def cancel(self):
        """Request cancellation; done/wait signal actual coroutine completion.

        Cancelling the concurrent future directly would mark it done before the
        HTTP coroutine has finished cleanup, allowing overlapping requests.
        """
        self._cancel_callback()


class DecisionWorker:
    """Persistent event loop for concurrent requests; closing cancels all of them."""

    def __init__(self, client, *, connections=1, timeout=None):
        self.client = client
        self._closed = False
        self._tasks = set()
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._loop.run_forever, name="decisions", daemon=True)
        self._thread.start()
        self.ready = DecisionRequestHandle()
        self.ready.bind(asyncio.run_coroutine_threadsafe(self._tracked(
            self._prepare(connections, timeout if timeout is not None else getattr(client, "timeout", None))),
            self._loop))

    async def _prepare(self, connections, timeout):
        self.ready.started_at = perf_counter()
        try:
            prepare = getattr(self.client, "prepare", None)
            if prepare is None:
                return "skipped"
            async with asyncio.timeout(timeout):
                return await prepare(connections) or "ready"
        except TimeoutError:
            return "timeout"
        except Exception:
            return "failed"
        finally:
            self.ready.completed_at = perf_counter()

    async def _tracked(self, coroutine):
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            return await coroutine
        finally:
            self._tasks.discard(task)

    async def _decide(self, handle, payload):
        handle._task = asyncio.current_task()
        try:
            if handle._cancel_requested:
                raise asyncio.CancelledError()
            # Cancelling a direct caller must not cancel preparation for other callers.
            if not self.ready.done():
                await asyncio.shield(asyncio.wrap_future(self.ready.future))
            else:
                self.ready.result()
            handle.started_at = perf_counter()
            return await self.client.decide(payload)
        finally:
            handle.completed_at = perf_counter()

    def _cancel_request(self, handle):
        # Runs on the worker loop. Repeated cancellation must not interrupt cleanup.
        if handle._cancel_requested or handle.done():
            return
        handle._cancel_requested = True
        if handle._task is not None:
            handle._task.cancel()

    def _schedule_cancel(self, handle):
        if not self._closed:
            self._loop.call_soon_threadsafe(self._cancel_request, handle)

    def submit(self, payload):
        if self._closed:
            raise RuntimeError("Il worker è chiuso")
        handle = DecisionRequestHandle()
        handle._cancel_callback = lambda: self._schedule_cancel(handle)
        handle.bind(asyncio.run_coroutine_threadsafe(self._tracked(self._decide(handle, payload)), self._loop))
        return handle

    async def _shutdown(self):
        for task in list(self._tasks):
            if not task.cancelling():
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
