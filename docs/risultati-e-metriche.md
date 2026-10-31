# Risultati e metriche

Che cosa viene salvato in `runs/` a ogni sessione e come sono definite le misure.

Gli errori temporanei del provider (HTTP 5xx, timeout, errori di connessione) ottengono **un solo** nuovo tentativo: l'evento `request_failed` lo registra, `retried_requests` lo conta e parte una nuova richiesta dopo il successivo frame, mentre la mossa in corso prosegue. Un secondo errore consecutivo arresta la sessione con codice `1`; errori 4xx (incluso 429), rifiuti e risposte invalide la arrestano subito. Il timeout comprende l'intera richiesta HTTP. Fine episodio, Esc, chiusura finestra e Ctrl+C annullano la richiesta in corso; una risposta già completata viene registrata e scartata. Nessuna risposta attraversa il reset. R serve soltanto in modalità manuale.

Ogni sessione modello crea una cartella distinta sotto `runs/`, esclusa da Git, con:

- `config.json`: tutte le opzioni della sessione, versione risultati `6`, modalità, FPS, catalogo delle scelte e `protocol` con la relativa `prompt_revision`: `choice-buttons-v1` (controllo diretto), `choice-timed-buttons-v1` (`timed`), `choice-buttons-predictive-v1` (modalità predittiva) oppure `openrouter-choice-scene-v5` (mosse). Nessuna credenziale.
- `screenshots/`: presente con `--save-screenshots`, contiene i PNG inviati, numerati per richiesta; altrimenti il riferimento screenshot negli eventi è `null`.
- `events.jsonl`: richieste, decisioni, `execution_start` e un riepilogo `execution` per intervallo governato da una scelta, incluso continue. Si chiude alla scelta successiva o a fine episodio: indice, scelta, applicabilità, frame/tempi/posizioni iniziali e finali, `move_frames`, `waiting_frames` e `move_end` (frame ed esito della fine o sostituzione). `move_start`/`move_end` descrivono la sequenza; `decision_not_applicable` segnala continue arrivato dopo la fine. Restano errori, scarti, cancellazioni ed esiti.
- `frames.jsonl`: singoli frame (`event="frame"`), pulsanti, fonte, posizione, reward e stato. `index` indica la decisione dell'intervallo, incluso continue; `move_index` quella che avviò la sequenza. Prima della prima decisione `index` è `null`. I frame dopo la fine restano nell'intervallo precedente, con `source="waiting"`.
- `summary.json`: riepilogo della sessione e di ogni tentativo, compresi quelli interrotti; `slow_provider` segnala i tentativi con latenza mediana sopra 0,6 s.

Tutti i timestamp usano `perf_counter`, in secondi sullo stesso orologio monotono. Le distribuzioni riportano numero di campioni, mediana e p95 nearest-rank; senza campioni mediana e p95 sono `null`.

| Misura | Definizione |
| --- | --- |
| `request_seconds` | Dall'avvio effettivo nel worker alla risposta validata; include rete e servizio, esclude il polling del runner. Campioni sulle decisioni ricevute. |
| `dispatch_seconds` | Dall'invio al worker all'avvio effettivo della richiesta; campioni sulle decisioni ricevute. |
| `preparation_seconds` | Codifica PNG, costruzione payload ed eventuale salvataggio screenshot. |
| `polling_seconds` | Dalla risposta validata all'acquisizione nel runner. |
| `observation_age_seconds` | Dall'osservazione all'avvio della mossa scelta, inclusa l’attesa del tick utile. |
| `observation_to_first_frame_seconds` / `observation_to_last_frame_seconds` | Dall'osservazione al ritorno del primo/ultimo frame della mossa, anche per mosse sostituite o interrotte. |
| `decisions_per_second` / `moves_per_second` | Decisioni ricevute / mosse iniziate (esclusi i continue), divise per il tempo reale dei tentativi. |
| `effective_fps` | Frame effettivamente eseguiti divisi per il tempo reale dei tentativi. |

`summary.json` aggiunge `worker_preparations`: per ogni setup, episodio, inizio/fine, durata e risultato (`ready`, `failed`, `timeout`, `skipped` o `cancelled`). L'evento corrispondente è `worker_prepared`. `controller_to_first_frame_seconds` misura dall'ingresso nel controller al ritorno del primo frame della prima mossa applicata, includendo caricamento, setup e reset; è `null` se nessuna mossa viene eseguita. Queste misure permettono di distinguere una riduzione reale dell'attesa iniziale dal suo spostamento fuori dall'episodio.

Risultati versione 6: i risultati storici non sono modificati né direttamente confrontabili fra protocolli e revisioni del prompt. Rimossi contatori e misure di code, rivalutazioni, latch, committed e tail. `requests_per_second` conta gli invii per secondo; `observation_age_frames` e `observation_age_seconds` misurano l'età dello screenshot all'avvio della scelta.

`execution_intervals` conta gli intervalli chiusi; `continues` conta i continue gestiti, compresi quelli scaduti (`not_applicable_decisions`). `moves` conta le nuove sequenze, incluso wait, senza continue. `waiting_frames` include attesa iniziale e frame dopo la fine; `jump_release_frames` conta i rilasci tecnici, `airborne_frames` i frame iniziati in aria. Ogni intervallo distingue frame di mossa (incluso il rilascio tecnico) e attesa.

Il tempo reale del tentativo include preparazione e attese, esclude setup, reset e chiusura del worker. Decisioni, scarti, cancellazioni, retry ed errori hanno contatori distinti. Gli intervalli parziali si chiudono anche su errore o arresto. Le risposte acquisite durante la chiusura sono conteggiate e scartate.


I riepiloghi includono reward, posizione iniziale/finale/massima, morte, completamento e motivo della fine. La sessione somma i reward e conta morti e tentativi completati; la posizione iniziale è quella del primo tentativo, la finale quella dell'ultimo e la massima è il massimo fra i tentativi. `known_cost` somma soltanto costi numerici validi restituiti dalle decisioni ricevute; resta `null` se assenti. `cost_known_requests` e `cost_missing_received_requests` ne indicano la copertura: richieste cancellate o fallite possono aver consumato credito non riportato. Queste misure non isolano l'inferenza e il tempo osservazione→azione non prova da solo la reazione a uno specifico ostacolo.
