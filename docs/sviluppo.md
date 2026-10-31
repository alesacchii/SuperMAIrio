# Sviluppo

Backend, interfaccia del gioco e verifiche.

## Backend e riproducibilità

Usiamo `gym-super-mario-bros==9.1.0`, `nes-py==9.0.1`, Gymnasium e Pyglet, con dipendenze risolte in `uv.lock`. L'ambiente è `SuperMarioBros-1-1-v0`: un singolo tentativo sul primo livello.

È presente un override uv per **Pyglet 1.5.31**: il limite transitivo di nes-py seleziona 1.5.21, che fallisce su Windows/Python 3.13 con `COMPointer`. La release di manutenzione 1.5.31 è stata verificata con rendering e input di questo progetto. Usare uv per rispettare l'override; non modificare manualmente le librerie installate.

La ROM usata dall'ambiente proviene dal pacchetto del backend; il progetto non copia ROM nella propria struttura. I termini relativi a tali asset sono descritti nella [documentazione del backend](https://github.com/Kautenja/gym-super-mario-bros/blob/master/LICENSING.md).

## Interfaccia del gioco

`MarioGame`, in `app/game.py`, espone:

```python
from app.contracts import Action
from app.game import MarioGame

with MarioGame(max_frames=3600) as game:
    observation = game.reset(seed=123)
    result = game.step(Action.RIGHT_JUMP, frames=6)
    if result.done:
        observation = game.reset(seed=123)
```

| Azione | Pulsanti NES |
| --- | --- |
| `noop` | Nessuno |
| `jump` | A |
| `left` | Sinistra |
| `left_jump` | Sinistra + A |
| `left_run` | Sinistra + B |
| `left_run_jump` | Sinistra + A + B |
| `right` | Destra |
| `right_jump` | Destra + A |
| `right_run` | Destra + B |
| `right_run_jump` | Destra + A + B |

`reset(seed)` restituisce un'`Observation` con `rgb` (array NumPy `uint8`, forma `240×256×3`) e `info` (metadati del backend: posizione, tempo, vite, stato, completamento e morte). Le immagini e i metadati sono copie indipendenti: le chiamate successive non cambiano osservazioni già restituite.

`step(action, frames)` accetta un valore `Action` o il relativo nome e mantiene quei pulsanti per il numero di frame richiesto. Restituisce `StepResult` con `observation`, reward cumulativo `reward`, `frames_executed`, `terminated`, `truncated` e proprietà `done`. La durata effettiva può essere inferiore alla richiesta se l'episodio finisce. Il comando seguente sostituisce integralmente il precedente; `noop` rilascia i pulsanti e avanza normalmente. Non vengono inseriti frame aggiuntivi di rilascio. Quando l'ambiente espone la RAM NES, `info["on_ground"]` indica se Mario è a terra e `info["scene"]` descrive la scena visibile (vedi `app/scene.py`).

Azioni sconosciute e durate non intere positive generano `ValueError` senza avanzare il gioco. Prima del primo comando, dopo la fine dell'episodio o dopo un errore durante `step`, serve `reset`; altrimenti viene generato `RuntimeError`. `close()` libera le risorse e può essere richiamato senza effetti aggiuntivi. Un gioco chiuso non può essere riavviato: creare una nuova istanza.

## Verifiche

Le verifiche della revisione 2 includono setup lento/fallito/cancellato, acquisizione fra due frame, risposte immediate senza raffiche di richieste, mantenimento dei 30/60 FPS, ricezione durante uno step sincrono e stime basate sui frame effettivi. Verificano correttezza locale e coerenza del prompt; non dimostrano decisioni migliori o inferenza più rapida sul provider.

Nel confronto offline prima/dopo con clock e modello simulati (30 frame, risposte da 0, 5, 25 e 250 ms, a 30/60 FPS), la mediana del polling passa da 8–33 ms a zero. Numero di mosse e tempi osservazione→primo frame restano invariati: l'applicazione è ancora vincolata al tick del gioco. Lo zero è del clock simulato, non una misura sul sistema operativo. Il setup viene misurato anche nel tempo controller→primo frame; spostarlo prima dell'episodio non viene contabilizzato come un risparmio.

**Confronto storico precedente alla versione 6.** Un secondo confronto sulla rivalutazione usa 180 frame, risposte simulate da 200 ms sempre `high_jump_right`, atterraggio dopo 41 frame e cancellazione immediata. In entrambi i casi partono cinque mosse; la latenza simulata del modello resta invariata. Cambia l'età dell'osservazione usata dalla decisione che viene applicata:

| FPS | Età mediana all'avvio prima → dopo | Richieste/s prima → dopo |
| --- | --- | --- |
| 30 | 1.400 → 433 ms | 1,01 → 4,53 |
| 60 | 700 → 250 ms | 2,01 → 6,03 |

Le richieste/s includono quelle cancellate, quindi possono superare la frequenza delle risposte complete. Il confronto dimostra decisioni basate su osservazioni più recenti, con più invii; non misura un miglioramento dell'inferenza o della sopravvivenza sul provider. I tre replay in `tests/fixtures/jump_replays.json` riproducono offline le morti alla buca, al Goomba e alle scale e verificano le informazioni corrette della scena. Le alternative prestabilite verificano che frenata e diversa scelta del salto possono evitare quei singoli incidenti; il salto alto alla buca incontra successivamente un altro pericolo. I replay contengono soltanto seed, pulsanti, durate e checkpoint, senza ROM o dipendenze dai log locali.

```powershell
uv run python -m unittest discover -s tests -v

# Include le verifiche della finestra: richiede un desktop con OpenGL
$env:SUPERMAIRIO_TEST_DISPLAY = '1'
uv run python -m unittest discover -s tests -v
Remove-Item Env:SUPERMAIRIO_TEST_DISPLAY
```

I test coprono mapping, durata, sostituzione e rilascio, input invalidi, fine episodio, reset, errori e chiusura. Sul backend reale verificano RGB, movimento, salto e limite dei frame. Le verifiche opzionali del display inviano eventi Pyglet per combinazioni, rilascio, perdita del focus, reset e arresto; salvano una cattura del rendering in `.local/verification/`. Sono verifiche degli eventi applicativi, non una prova di consegna dei tasti fisici da parte di Windows.

I test Decisions offline verificano PNG e payload, tutte le scelte, configurazione e credenziali, errori HTTP, timeout totale, pausa durante l'attesa, cancellazione, fine episodio e risultati salvati. I test dell'esecutore verificano copioni interrompibili, atterraggio e rilascio di A. I test della scena verificano le convenzioni su una RAM sintetica e, sul livello reale, Goomba, blocchi ?, tubi alti 2, 3 e 4 tile e la prima buca. I test continui usano clock e worker simulati per il ciclo a richiesta singola, `continue`, sostituzioni in aria, fine mossa, attribuzione degli intervalli, modalità a turni, soglia in frame, retry singolo, `--no-scene`, pacing, scarti, budget reale, storico, blocco, metriche e costi. Due prove usano emulatore reale e modello simulato, una con salti e atterraggi; una verifica opzionale del display controlla l'avanzamento durante l'attesa e Esc. Non effettuano chiamate a pagamento.

Per verificare il provider reale, impostare la chiave e attivare esplicitamente i test live. Usano il modello selezionato da `OPENROUTER_MODEL` (ambiente o `.env`, altrimenti decider). Questi inviano prima due immagini di colore diverso per controllare che i pixel vengano interpretati, poi eseguono un tentativo di gioco di 12 frame. Consumano credito OpenRouter e salvano la sessione di gioco in `runs/`.

```powershell
$env:SUPERMAIRIO_TEST_OPENROUTER = '1'
uv run python -m unittest discover -s tests -p test_openrouter_live.py -v
Remove-Item Env:SUPERMAIRIO_TEST_OPENROUTER
```

Se il controllo dei colori fallisce, il test non avvia la sessione di gioco. La verifica live ha superato tutti i controlli con Luna il 7 ottobre 2026 e con Jev 1.14 il 15 ottobre 2026; può essere ripetuta per verificare cambiamenti del provider o del modello.
