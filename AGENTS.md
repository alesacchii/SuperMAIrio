# Guida per gli agenti AI — SuperMAIrio

## Contesto

SuperMAIrio è un **benchmark pubblico dei System 1 model** (modelli a decisione
rapida) su Super Mario Bros 1-1 (`SuperMarioBros-1-1-v0`). Ciclo: osservazione
dalla RAM NES → richiesta HTTP Decisions → una scelta → pulsanti NES. Si misurano
vittorie, latenza, costo noto e affidabilità, a parità di condizioni.

- **Nessun provider fisso.** Ogni modello passa da un endpoint compatibile con la
  Decisions API, configurato con `SUPERMAIRIO_ENDPOINT`, `SUPERMAIRIO_MODEL` e il
  token facoltativo `SUPERMAIRIO_API_KEY` (l'ambiente prevale su `.env`).
  Partecipanti multipli in `benchmark.toml` (`model` oppure `env_prefix`).
- **Contesto identico per tutti i modelli:** stesse istruzioni, stato, scelte,
  anteprime e immagine (`ChoiceModel`); cambia solo l'ID.
- **Ogni input è scelto dal modello:** nessuna mossa automatica del programma.
- **Due prove** (`TRACKS` in `supermairio/config.py`): `realtime` (sessioni
  `predictive`: pulsanti, emulatore ombra, anteprime 30, 2 copie parallele) e
  `turn-based` (sessioni `paused`, `timed`: pulsanti poi durata). Le altre
  combinazioni (`realtime`, `moves`, pulsanti a turni) sono **sperimentali**.
- Il gioco (`supermairio play`) è separato dal benchmark ma usa le stesse
  variabili e, con `--track`, esattamente le stesse impostazioni. I default di
  `play` devono restare la configurazione migliore (= prova `realtime`).
- Repo pubblico **in inglese** (README, docs, CLI, codice). Questo file resta in
  italiano.

## Comandi

```powershell
uv sync --locked
uv run supermairio --help
uv run supermairio play --mode demo --headless --max-frames 120   # verifica senza endpoint
uv run supermairio bench run                                      # calendario, nessuna richiesta
uv run python -m unittest discover -s tests -v                    # suite standard, offline
uv run python -m unittest discover -s tests -p test_cli.py -v     # suite mirata
```

Prima della suite controllare che `SUPERMAIRIO_TEST_LIVE` non sia attivo. Test
del display: `SUPERMAIRIO_TEST_DISPLAY=1` (desktop OpenGL, catture in
`.local/verification/`). Test live: `SUPERMAIRIO_TEST_LIVE=1`, possono generare
costi: eseguirli, come `bench run --live`, solo se richiesto. Se la cache uv non
è accessibile usare `uv --cache-dir .uv-cache`.

Python 3.13, progetto installabile (hatchling, script `supermairio`). Conservare
l'override **pyglet 1.5.31** (1.5.21 fallisce su Windows/Python 3.13). Non
modificare `.venv` a mano.

## Mappa del codice

| Ambito | File | Test |
| --- | --- | --- |
| CLI, configurazione, prove | `supermairio/cli.py`, `config.py` | `test_cli.py`, `test_game.py` |
| Contratti condivisi | `supermairio/contracts.py` | `test_game.py` |
| Emulatore, snapshot, `simulate` | `game/emulator.py` | `test_game.py` |
| Scena dalla RAM (calibrata su 1-1) | `game/scene.py` | `test_scene.py` |
| Cataloghi ed esecutori | `game/control.py`, `game/moves.py` | `test_button_control.py`, `test_timed_control.py`, `test_moves.py`, `test_jump_replays.py` |
| Finestra e tastiera | `game/viewer.py`, `runtime/play.py` | `test_viewer.py`, `test_runner.py` |
| Trasporto HTTP, validazione, worker | `agent/client.py` | `test_decisions.py`, `test_worker_timing.py` |
| Prompt e adapter unico | `agent/prompt.py`, `agent/__init__.py` | `test_models.py`, `test_decisions.py` |
| Prova realtime (predittiva) | `runtime/predictive.py` | `test_predictive.py` |
| Cicli paused e realtime | `runtime/loop.py` | `test_realtime.py` |
| Log e metriche | `runtime/session.py`, `runtime/metrics.py` | `test_realtime.py`, `test_decisions.py` |
| Benchmark: edizioni, report, verifica | `benchmark/edition.py`, `benchmark/report.py` | `test_benchmark.py` |
| Replay GIF | `benchmark/replay.py` | — |

Documentazione: `README.md` e `docs/` (`benchmark`, `decisions-api`,
`how-it-works`, `play`, `results-format`, `experimental-modes`, `development`).

## Comportamenti da preservare

- **Emulatore.** `Observation.rgb` è una copia `uint8` 240×256×3 con metadati
  indipendenti. `step` sostituisce i pulsanti; `noop` li rilascia. Contare
  `frames_executed`. `reset` prima del primo step, dopo la fine e dopo un errore.
- **Scena.** Solo ciò che è sullo schermo, niente blocchi nascosti. `--no-scene`
  la rimuove e l'adapter deve funzionare senza. Ricalibrare indirizzi e codici
  nell'emulatore prima di cambiarli.
- **Prova realtime.** Il gioco non si ferma mai. L'ombra proietta i pulsanti già
  scelti fino al frame di applicazione; risposte in anticipo aspettano, quelle in
  ritardo si applicano subito con `resync`. Le sequenze di `PREDICTIVE_MOVES`
  (frame senza A, `*_hop`, `right_run_then_jump`) fanno parte della scelta. Le
  anteprime sono informazione, mai filtro. Ogni opzione in più costa
  un'anteprima: misurare prima di ampliare il catalogo. Scarti di 1–2 px
  (`prediction_mismatch`, byte `0x705`) sono attesi. Finestra con `vsync=False`.
- **Prova turn-based.** Due domande (`buttons`, poi `frames` con
  `state.chosen_buttons`) nello stesso timeout. Con A 2/4/8/16/28 frame, senza A
  2/4/8. Nessun rilascio automatico né fronte di A aggiunto.
- **Prompt.** Non modificare `GUIDE` (condiviso con `timed`) né i testi
  predittivi condivisi senza una nuova versione del benchmark. Revisioni
  correnti: predittiva 1, `timed` 1, pulsanti diretti 13, mosse 5.
- **Modalità sperimentali.** Mosse tutte interrompibili, nessun latch o attesa
  automatica; `continue` offerto solo con mossa attiva e mai riavviato; dopo una
  sostituzione in aria la stima dell'atterraggio resta sconosciuta fino al
  prossimo decollo (conservare `JUMP_AIRTIME`). In realtime al massimo una
  richiesta in corso; età controllata alla ricezione in frame
  (`max_decision_frames`), mai in `paused`. Non cambiare le durate calibrate senza
  rimisurarle.
- **Errori.** 5xx, timeout e connessione: un solo nuovo tentativo
  (`request_failed`). Secondo errore consecutivo, 4xx o risposta invalida
  arrestano la sessione. Il timeout copre l'intera richiesta. Nessuna risposta
  attraversa il reset. Registrare gli esiti parziali anche in caso di arresto.
  Preservare cancellazione e chiusura di worker e connessioni persistenti.
- **Benchmark.** `MODES` deriva da `TRACKS`; le chiavi `predictive`/`paused`
  nominano le sessioni registrate. `edition.json` contiene hash del codice e di
  `uv.lock`: una modifica impedisce di riprendere un'edizione esistente.

## Risultati, credenziali e metodo

- `runs/<sessione>/`: `config.json`, `events.jsonl`, `frames.jsonl`,
  `summary.json`, `screenshots/` su richiesta. Risultati versione **6**: tenere
  coerenti eventi, aggregazioni e `docs/results-format.md`. Leggere solo le
  sessioni utili all'analisi.
- Misure con `perf_counter`. Latenza della richiesta, preparazione, polling ed
  età dell'osservazione sono misure distinte. Non presentare la latenza del
  provider come tempo di inferenza, né un costo parziale come totale o zero.
- Mai token o header di autenticazione in codice, log, documentazione o
  risultati. `.env` è privato; `.venv/`, `.uv-cache/`, `__pycache__/`, `runs/`
  sono generati. Nessuna ROM nel repo.
- Stile Python esistente; separare contratti, emulatore, interfaccia, adapter,
  trasporto e misure; niente refactoring estranei al compito; non duplicare
  configurazioni fuori da `config.py`.
- Per modifiche funzionali eseguire i test pertinenti, poi la suite standard.
  Aggiornare README e `docs/` se cambiano CLI, protocollo, controllo o significato
  dei risultati. Riportare verifiche e limiti senza attribuire risultati simulati
  al provider reale; i numeri in vetrina devono restare onesti.
