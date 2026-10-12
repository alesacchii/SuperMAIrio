# Guida per gli agenti AI — SuperMAIrio

## Contesto e obiettivo

SuperMAIrio è un progetto sperimentale Python che usa Super Mario Bros come
ambiente per studiare i **System One Model**, orientati a decisioni rapide.
Il ciclo è: osservazione del gioco → decisione del modello → pulsanti NES →
nuova osservazione. Si misurano qualità del controllo, latenza, frequenza delle
decisioni, affidabilità e costo, mantenendo confrontabili le condizioni delle prove.

Il backend attuale esegue `SuperMarioBros-1-1-v0`. Sono implementate le modalità
`model` (predefinita), `demo` e `manual`. Il primo adapter è GPT Luna,
`openai/gpt-6-luna-decisions`, tramite la Decisions API OpenRouter e una domanda
`choice` sulle mosse del catalogo (`app/moves.py`) più `continue`. Altri modelli e confronti descritti nel README
possono essere obiettivi futuri: verificarne la presenza nel codice prima di
considerarli implementati. La demo verifica il controllo dei comandi; non è una
strategia che garantisce il completamento del livello.

## File da leggere all'inizio

1. `README.md`: obiettivi scientifici, avvio, protocollo, modalità di esecuzione,
   definizioni delle metriche e risultati sperimentali. Alcune sezioni raccontano
   fasi precedenti: per il comportamento attuale confrontarle con codice e test.
2. `pyproject.toml` e `.python-version`: versione Python, dipendenze e override uv.
   Consultare `uv.lock` quando si interviene sulle dipendenze.
3. `app/contracts.py`: contratti condivisi (`Action`, `Observation`, `Decision`,
   `DecisionRequest`, `StepResult`) e mapping dei pulsanti; `app/moves.py`:
   catalogo delle mosse ed esecutore frame per frame; `app/scene.py`: scena
   letta dalla RAM NES (indirizzi e codici calibrati su 1-1).
4. `app/config.py`: opzioni CLI, valori predefiniti, validazione e caricamento
   della chiave OpenRouter.
5. `main.py` e `app/runner.py`: ingresso del programma, selezione del controller,
   ciclo demo/manuale e gestione degli errori.

Leggere poi i moduli e i test pertinenti alla richiesta, seguendo questa mappa.

## Mappa del codice e letture mirate

| Ambito | File da leggere | Test di riferimento |
| --- | --- | --- |
| Emulatore, frame, reset, azioni e osservazioni | `app/game.py`, `app/contracts.py` | `tests/test_game.py` |
| Finestra, tastiera, focus, rendering e arresto | `app/viewer.py`, `app/runner.py` | `tests/test_viewer.py`, `tests/test_runner.py` |
| Mosse, segmenti committed, atterraggio e rilascio di A | `app/moves.py`, `app/game.py` | `tests/test_moves.py`, `tests/test_game.py` |
| Scena dalla RAM: nemici, muri, buche, blocchi, power-up | `app/scene.py`, `app/game.py` | `tests/test_scene.py` |
| Ciclo modello, realtime/paused, richiesta singola e risposte obsolete | `app/model_runner.py`, `app/moves.py`, `app/openrouter.py`, `app/config.py` | `tests/test_realtime.py`, `tests/test_decisions.py` |
| Protocollo HTTP, validazione, timeout e worker asincrono | `app/openrouter.py`, `app/contracts.py` | `tests/test_decisions.py` |
| Prompt, immagini, contesto e nuovi modelli | `app/models/gpt_luna.py`, `app/models/__init__.py`, `app/contracts.py`, `app/moves.py` | `tests/test_models.py`, `tests/test_decisions.py`, `tests/test_realtime.py` |
| Log, metriche, costi e rilevamento del mancato progresso | `app/session.py`, `app/metrics.py`, `app/model_runner.py` | `tests/test_realtime.py`, `tests/test_decisions.py` |
| Verifica del provider reale | `tests/test_openrouter_live.py`, `.env.example`, sezione Verifiche del README | Test live esplicitamente attivati |

## Ambiente e comandi

Il progetto usa **Python 3.13** (`>=3.13,<3.14`) e **uv**; non è un pacchetto
installabile (`package = false`). Eseguire i comandi dalla radice del progetto.

```powershell
# Installazione riproducibile
uv sync --locked

# Opzioni CLI, senza avviare il gioco
uv run main.py --help

# Verifica locale senza chiave e senza chiamate OpenRouter
uv run main.py --mode demo --headless --max-frames 120

# Suite standard, senza chiamate a pagamento con i flag opzionali disattivati
uv run python -m unittest discover -s tests -v

# Esempio di suite mirata
uv run python -m unittest discover -s tests -p test_realtime.py -v
```

Se la cache uv predefinita non è accessibile, usare `uv --cache-dir .uv-cache`
al posto di `uv`. Conservare l'override **Pyglet 1.5.31**: evita un problema di
compatibilità Windows/Python 3.13 della versione transitiva 1.5.21. Non correggere
le dipendenze modificando manualmente i file dentro `.venv`.

I test del display richiedono un desktop con OpenGL e il flag
`SUPERMAIRIO_TEST_DISPLAY=1`; le catture sono salvate in `.local/verification/`.
I test live richiedono `SUPERMAIRIO_TEST_OPENROUTER=1` e consumano credito.
Avviare sessioni modello reali o test live quando richiesti dal compito; per le
verifiche ordinarie usare i test con client, worker e clock simulati. Prima della
suite standard controllare che il flag live non sia già attivo nell'ambiente.

## Comportamenti da preservare

- `Observation.rgb` è una copia RGB NumPy `uint8`, forma `240×256×3`; anche
  i metadati sono indipendenti dalle osservazioni successive.
- `MarioGame.step` sostituisce integralmente i pulsanti precedenti. `noop`
  rilascia i pulsanti e fa avanzare il gioco. Contare `frames_executed`, che può
  essere inferiore alla durata richiesta. Serve `reset` prima del primo step,
  dopo la fine dell'episodio o dopo un errore di step.
- `realtime` fa avanzare il gioco anche durante le richieste, alla velocità
  configurata (massimo 60 FPS), anche headless. `paused` ferma il gioco durante
  la decisione ed è una modalità di debug (a turni); distinguerla nei confronti.
- Ciclo Chiamo → Decisione → Azione → Chiamo: al massimo una richiesta in corso.
  Ogni decisione è una mossa completa oppure `continue`. In `realtime` la richiesta
  successiva parte quando la decisione viene applicata, mentre la mossa prosegue;
  in `paused` parte a fine mossa.
- I segmenti committed (la parte con A dei salti) non vengono interrotti: una
  mossa nuova attende, e un salto nuovo attende anche l'atterraggio
  (`info["on_ground"]`, dalla RAM NES). L'esecutore rilascia A per un frame
  prima di un salto che segue A premuto; a fine copione la direzione resta
  premuta senza A. Le durate sono calibrate sull'emulatore: rimisurarle prima
  di cambiarle.
- L'età di una risposta si controlla alla ricezione, in frame di gioco
  (`max_decision_frames`); in `paused` non scade. L'età all'avvio della mossa
  è registrata come misura.
- La scena riporta solo ciò che è sullo schermo (niente blocchi nascosti) e il
  runner la rimuove con `--no-scene`: l'adapter deve funzionare anche senza.
  Ricalibrare indirizzi e codici nell'emulatore prima di cambiarli. Nessuna risposta deve
  attraversare il reset. Preservare cancellazione e chiusura del worker e delle
  connessioni HTTP persistenti.
- Errori temporanei (HTTP 5xx, timeout, connessione) hanno un solo nuovo
  tentativo, registrato come `request_failed`; un secondo errore consecutivo,
  un 4xx o una risposta invalida arrestano la sessione. Il timeout riguarda
  l'intera richiesta. Gli esiti parziali devono essere registrati anche in caso
  di arresto.

I valori predefiniti e le regole esatte sono in `app/config.py` e nei test;
non duplicare configurazioni in nuovi moduli.

## Aggiungere o modificare un modello

Ogni modulo pubblico `app/models/<nome>.py` deve esportare una classe `Model`
con `model_id` univoco, costruttore `(api_key, timeout)`, `build_request(...)`
e `async decide(payload)`. La scoperta è automatica; i moduli con underscore
iniziale sono helper. Non aggiungere un registro manuale nel runner.

`build_request` riceve osservazione, PNG, `frames`, `previous_move`,
`previous_position` e `control_context=None`; restituisce una `DecisionRequest`
con payload e trace senza credenziali. Gli adapter devono accettare il contesto
fornito dal runner e descrivere correttamente il ciclo a mosse. `decide`
restituisce una `Decision` con `move` uguale a una mossa del catalogo o `continue`.
Per lo stesso protocollo multimodale Choice si può estendere l'adapter GPT Luna
cambiando `model_id`; verificare il supporto del nuovo modello al protocollo
e agli input immagine. Tenere i dettagli specifici nell'adapter, il trasporto
in `app/openrouter.py` e l'orchestrazione in `app/model_runner.py`.

## Risultati, credenziali e metodo di lavoro

- `runs/<sessione>/` contiene `config.json`, `events.jsonl`, `summary.json`
  e, su richiesta, `screenshots/`. Leggere solo le sessioni utili all'analisi;
  non includere tutta la cartella nel contesto iniziale. I risultati hanno
  versione `4`: preservare coerenza fra eventi, aggregazioni e documentazione.
- Usare `perf_counter` per le misure temporali. Latenza della richiesta,
  preparazione, polling ed età dell'osservazione sono misure distinte.
  Non presentare la latenza OpenRouter come puro tempo di inferenza, né un
  costo parziale o sconosciuto come costo totale o zero.
- La chiave è `OPENROUTER_API_KEY`, caricata dall'ambiente o da `.env` nella
  radice; l'ambiente ha precedenza. Consultare `.env.example` per il formato.
  Non stampare o inserire chiavi e header di autenticazione in codice, log,
  documentazione o risultati.
- `.venv/`, `.uv-cache/`, `__pycache__/` e `runs/` sono file generati;
  `.env` è configurazione privata. Il backend fornisce la ROM: non aggiungere
  ROM o file `.nes` al progetto. Consultare `.gitignore` prima di aggiungere asset.
- Seguire lo stile Python esistente e mantenere separati contratti, emulatore,
  interfaccia, adapter, trasporto e misure. Evitare refactoring estranei al compito.
- Per modifiche funzionali eseguire i test pertinenti, poi la suite standard
  quando appropriato. Aggiornare il README se cambiano CLI, protocollo,
  comportamento del controllo o significato dei risultati. Riportare le
  verifiche eseguite e gli eventuali limiti senza attribuire risultati simulati
  al provider reale.
