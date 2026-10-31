# Aggiungere un modello

Ogni modello ha un file in `app/models/`: GPT Luna è definito in `gpt_luna.py`.
Il trasporto HTTP OpenRouter, la validazione delle risposte e il worker sono
condivisi in `app/openrouter.py`; il ciclo modello è in `app/model_runner.py`
e le aggregazioni in `app/metrics.py`. Il runner riceve una `DecisionRequest`
(payload e metadati per i log) e una `Decision`, senza conoscere il formato
dell'osservazione richiesto dal singolo modello.

Per aggiungere un modello, creare `app/models/nuovo_modello.py` con una classe
`Model`, un `model_id` univoco e i metodi `build_request(...)` e
`async decide(payload)`. Il costruttore riceve `(api_key, timeout)`.
Il modulo viene scoperto automaticamente: non occorre modificare il runner
o un registro. Nomi dei file con underscore iniziale sono riservati agli helper.

Un adapter che usa HTTP Decisions ma una diversa disposizione delle domande può
ridefinire `parse_response(body, payload)` su `OpenRouterClient`, restituendo una
`Decision`: timeout, connessioni e gestione degli errori restano nel trasporto
condiviso. Il parser predefinito conserva la domanda `next_action`.

Se il nuovo modello usa il protocollo Choice multimodale, il file può usare
la base condivisa, indipendente da Luna e Jev:

```python
from app.models._choice import ChoiceModel


class Model(ChoiceModel):
    model_id = "provider/identificativo-del-modello"
```

Usare un identificativo realmente disponibile e verificare che supporti quel
protocollo e gli input immagine. Per input, prompt o risposte differenti,
implementare i metodi dell'adapter nel nuovo file; `decide` deve restituire
una `Decision` con `move` uguale a una delle scelte offerte in `control_context["choices"]`.
`build_request` riceve `observation`, `png` e gli argomenti nominati `frames`,
`previous_move`, `previous_position` e l'opzionale `control_context=None`; restituisce una `DecisionRequest`
con `payload` da inviare e `trace` da registrare, entrambi senza credenziali.
Gli adapter devono accettare `control_context`, che il runner fornisce con
`execution_mode`, `control_mode`, `choices` (nomi e descrizioni delle scelte offerte),
`stuck` (booleano o `None`), `recent_moves` (ultime otto mosse,
indice, frame e delta x), `current_move`, `move_frames`, `move_finished`,
`move_remaining_frames` (`None` se la mossa finisce all'atterraggio o i pulsanti sono mantenuti),
`tail_action` (`noop` per le mosse, `None` per i pulsanti),
`landing_in_frames` (stima dell'atterraggio, `None` se sconosciuta o con `--no-scene`).
In `realtime` aggiunge `game_fps`, `recent_latency_seconds` (mediana delle ultime cinque latenze, conservata per compatibilità) e `recent_response_frames` (mediana degli ultimi cinque intervalli osservazione→ricezione in frame di gioco, `None` inizialmente).
La scena, se attiva, è in `observation.info["scene"]`; con `--no-scene` il runner la rimuove prima
di chiamare l'adapter, che deve funzionare anche senza.
L'assenza del contesto nelle chiamate dirette a GPT Luna produce il prompt a turni.
Le prove continue devono spiegare al modello il ciclo: nuova richiesta dopo il primo frame,
interruzioni, rilascio finale e continue offerto solo con mossa attiva. Gli adapter basati su `OpenRouterClient` riusano le connessioni; `prepare()` e `aclose()` sono chiamati dal worker se presenti. `DecisionWorker.ready` segnala la conclusione del setup; il runner lo attende prima del reset. I gestori di setup e richiesta espongono `wait(timeout)`, che si risveglia anche per errore o cancellazione senza consumare il risultato. Per cancellare una richiesta usare `handle.cancel()`: `done()`/`wait()` segnalano la conclusione effettiva della coroutine, compresa la pulizia HTTP. Non usare `handle.future.cancel()` per liberare lo slot del runner: quella future può risultare cancellata prima che la coroutine sia terminata.

```powershell
uv run main.py --model nuovo_modello
```

Sono accettati il nome del file senza `.py` e il `model_id` dell'adapter.
Un modello non configurato viene segnalato prima dell'avvio del gioco.
