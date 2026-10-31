# Protocolli

Specifiche dei tre protocolli di controllo e della modalità predittiva. Per una
panoramica vedere [come-funziona.md](come-funziona.md).

## Controllo diretto, indipendente dal modello

```powershell
# Controllo continuo in tempo reale: il modello decide ogni cambio dei pulsanti
uv run main.py --execution-mode realtime

# Stesso harness con un altro adapter
uv run main.py --execution-mode realtime --model gpt_luna
uv run main.py --execution-mode realtime --model jev
```

`app/control.py` definisce il protocollo di esecuzione, indipendentemente dal
provider. In `buttons` le scelte sono `noop`, `jump`, `left`, `left_jump`,
`left_run`, `left_run_jump` e le corrispondenti quattro combinazioni `right`.
Ogni scelta sostituisce esattamente i pulsanti precedenti al primo tick utile.
La stessa scelta ripetuta non introduce un rilascio intermedio. Il modello deve
scegliere esplicitamente una combinazione senza A prima di un nuovo salto:
l'harness non crea il fronte di pressione, non attende l'atterraggio e non
esegue sequenze. `continue` non serve e non viene offerto.

Una sola richiesta resta in corso. Dopo il primo frame della nuova scelta viene
acquisita l'osservazione successiva. Durante latenza, retry o scarto di una risposta
obsoleta continuano gli ultimi pulsanti scelti dal modello. Prima della prima
decisione si applica `noop`; il reset elimina lo stato precedente. I limiti di
episodio, età delle risposte e gestione degli errori restano gli stessi. A turni
(`paused`) ogni decisione esegue **un solo frame**, poi il gioco attende: non è
equivalente all'esecuzione di una mossa completa della modalità `moves`.

Il contesto dichiara `move.ends = "at next choice"` in realtime. `input.buttons`
elenca i pulsanti effettivamente premuti; `input.held_frames` indica da quanti
frame ciascuno è premuto, senza azzerarsi quando il modello ripete la scelta. La stima della
durata residua del salto è omessa perché il modello non ha ancora deciso quando
rilasciare A. Le distanze della scena rimangono informative e non selezionano
azioni. Prompt e costruzione della richiesta Choice sono condivisi in
`app/models/_choice.py`; ogni modello specifica solo l'identificativo. Il bordo
nero che porta lo screenshot a 280×280 (minimo richiesto da Jev) è applicato a
tutti i modelli, così il contesto non cambia da un modello all'altro. Un nuovo adapter Choice può estendere `ChoiceModel`; un protocollo diverso
può implementare `ModelController` usando le scelte in `control_context["choices"]`.

I log conservano lo schema risultati 6, identificando il controllo diretto con
`control_mode: "buttons"`, `protocol: "choice-buttons-v1"` e revisione prompt 12
(6 nelle prime prove dirette, 7 con i frame dei pulsanti premuti, 8 con descrizioni
esplicite dei comandi, 9 con istruzioni abbreviate, 10 con la proiezione dei blocchi,
11 con i tempi calibrati di pressione A, 12 con la distinzione fra salto nuovo e salto in corso).
Il catalogo registrato dichiara `until_next_choice` (oppure `one_frame` a turni).
Gli intervalli e il conteggio storico `moves` rappresentano in questo caso le
scelte dei pulsanti, anche quando ripetono la combinazione corrente.
I test offline verificano continuità, assenza di rilasci automatici, retry e reset;
non dimostrano il completamento del livello da parte di un provider reale.

Nel controllo diretto `jump_reach_px` compare solo a terra: descrive un nuovo
salto, non il percorso ancora disponibile in aria. `jump_observation` conserva
velocità alla pressione iniziale di A, frame trascorsi, durata effettiva della
pressione e portata totale calibrata a quella velocità. Non è una previsione
di atterraggio; collisioni, sterzate e rilascio di A cambiano il risultato.
Con `--no-scene` questo contesto derivato dalla RAM non viene inviato.

## Pulsanti con durata scelta dal modello (`--control-mode timed`)

```powershell
# Il protocollo che ha completato 1-1: gioco fermo durante la decisione
uv run main.py --model decider --execution-mode paused --control-mode timed
```

In realtime, quando la scelta parte, lo screenshot è già vecchio: nella sessione
Luna a 60 FPS `runs/20261029T163436-a767de7d098d/` l'età ha mediana 17,5 frame
(p95 30). Correndo a 3 px/frame, Mario percorre circa 50 px (p95 90 px) prima
che la scelta abbia effetto. È il ritardo visibile guardando la finestra: la
latenza OpenRouter, non un errore di acquisizione dell'immagine. A turni (`paused`) il
gioco resta fermo: screenshot e stato descrivono esattamente l'istante in cui
la scelta parte. Con un solo frame per scelta, però, un salto alto richiede
circa 28 decisioni consecutive con A, e i modelli rilasciavano A dopo pochi frame.

`timed` fa scegliere al modello **i pulsanti e la loro durata**. L'adapter
pone due domande Choice in sequenza, nello stesso budget `--request-timeout`.
La prima (`buttons`) chiede quale combinazione NES premere. La seconda (`frames`)
chiede per quanti frame tenerla e riceve la scelta precedente in
`state.chosen_buttons`. Le risposte vengono unite in una mossa del catalogo,
per esempio `right_run_jump_28`. Con A le durate sono 2, 4, 8, 16 e 28 frame;
ogni opzione riporta l'altezza misurata del salto (da 27–34 px a 64–86 px).
Senza A sono 2, 4 e 8 frame: le durate lunghe senza A lasciavano Mario senza
reazioni ed erano la causa ricorrente delle morti nelle prove.

In realtime l'adapter usa invece **una sola chiamata** con tutte le combinazioni
offerte (per esempio `right_run_jump_28`), descritte con gli stessi effetti:
una seconda chiamata raddoppierebbe il ritardo prima dell'applicazione.

L'esecutore (`TimedExecutor`) tiene esattamente quei pulsanti per quei frame.
Non inserisce rilasci di A e non attende atterraggi; ripetere A non crea un
nuovo fronte di pressione. A turni la scelta successiva segue senza frame
intermedi. In realtime una nuova scelta sostituisce subito la precedente e, se
non arriva entro la durata, i pulsanti vengono rilasciati. Il contesto aggiunge
informazioni, senza mai indicare una mossa:

- `contact_in_frames`: frame stimati prima che il bordo di Mario incontri
  nemico, muro o buca alle velocità attuali;
- avviso `Ceiling` quando un blocco è sopra la traiettoria di un salto che
  partirebbe ora;
- avviso quando A resta premuto a terra, perché un nuovo salto richiede prima
  una scelta senza A;
- guida di gioco (Goomba, buche, tubi, scalinate) e obiettivo.

L'avviso di nemico vicino ignora i nemici oltre il muro che Mario ha davanti.
Il registro usa `protocol: "choice-timed-buttons-v1"` e la revisione 1 del prompt
`timed`. `probabilities` riporta la probabilità dei pulsanti scelti moltiplicata
per quella di ogni durata; `usage.cost` somma le due chiamate. Il 29 ottobre
2026 `decider` ha completato 1-1 in quattro episodi su quattro, identici
(sessioni `runs/20261029T174114-fc4cdb1bca6a/` e `runs/20261029T174438-ad54abd24e6a/`).
È una prova a turni, non una vittoria a velocità reale: vedere le
[verifiche](harness-verification-2026-10-29.md#protocollo-timed-a-turni).

## Modalità predittiva (`--execution-mode predictive`)

```powershell
# La configurazione delle vittorie a 60 FPS è quella predefinita
uv run main.py

# Le stesse opzioni in forma esplicita, con il benchmark da 10 episodi senza finestra
uv run main.py --model decider --execution-mode predictive --choice-preview 30 --parallel-requests 2 --no-image --headless --episodes 10
```

Il gioco gira a `--game-fps` (60) e non si ferma mai. La differenza rispetto a
`realtime` è che cosa vede il modello. In `realtime` lo stato è quello del frame
della richiesta, vecchio di 13–26 frame quando la scelta parte. In `predictive`
i pulsanti fino alla prossima scelta sono già noti: un **emulatore ombra** li
riproduce da uno snapshot del gioco (`MarioGame.snapshot` e `simulate`, in
thread separati: l'emulatore nativo rilascia il GIL) fino al frame in cui la
scelta richiesta sarà applicata. Il modello riceve stato e, se attivo,
screenshot di quell'istante. Una risposta in anticipo aspetta il suo frame;
una in ritardo si applica subito, e le previsioni successive vengono rifatte
dallo stato reale (`resync`).

Ogni scelta è tenuta fino alla scelta successiva. La distanza fra due scelte
(`move.hold_frames`, di solito 36–60 frame) è calcolata dal 95° percentile delle
latenze e dei tempi di preparazione misurati, così che la risposta arrivi in
tempo; `--decision-frames` ne fissa solo il minimo. Con le anteprime attive, mentre una richiesta è in
volo, l'ombra calcola già lo stato futuro per ciascuna risposta possibile.

Il catalogo `PREDICTIVE_MOVES` (in `app/control.py`) ha 10 scelte, tutte
selezionate dal modello e tenute fino alla scelta successiva:

- `noop`, `left`, `left_run`, `right`, `right_run`, `right_jump`, `right_run_jump`;
- `right_hop`, `right_run_hop`: A per 8 frame, poi tutti i pulsanti rilasciati;
- `right_run_then_jump`: right+B per 4 frame, poi right+B+A (salto con rincorsa).

Un input con A scelto a terra mentre A è già premuto inizia con un frame senza
A, perché il NES veda una nuova pressione; in aria A resta premuto. È la
definizione della scelta di salto, non una mossa aggiunta dal programma. Il
salto verticale e i salti a sinistra non sono offerti: ogni scelta costa
un'anteprima per richiesta.

`--choice-preview N` aggiunge in fondo alla descrizione di ogni opzione il suo
esito emulato: tenendo solo quella scelta per almeno N frame (e comunque per la
durata prevista più 10), prolungando finché Mario è in aria o sopra una buca,
`Preview: Mario dies after 21 frames.` oppure `Preview: alive after 43 frames,
90 px right, on the ground.` L'anteprima è informazione: il programma non
sceglie, non scarta opzioni e non indica una mossa. Lo stato riporta anche
`No forward progress for N frames` dopo 90 frame senza un nuovo massimo di x.

`--parallel-requests N` invia N copie identiche di ogni richiesta e usa la prima
risposta valida (le altre restano registrate per il costo): elimina gli stalli
occasionali del provider e riduce la coda della latenza, moltiplicando il costo.
`--speculative-width N` è sperimentale: mentre la risposta n è in volo invia una
richiesta n+1 per ciascuna delle N risposte più frequenti, con il proprio stato
previsto; porta la cadenza a 8–18 frame, ma non è combinabile in modo utile con
le anteprime per il costo di emulazione.

`events.jsonl` registra per ogni richiesta `start_frame`, `target_frame`,
`hold_frames`, `role` (`chain`, `resync`, `branch`) e i tempi di proiezione e
preparazione; `choice_applied` riporta `late_frames` e `prediction_mismatch`
(posizione reale diversa da quella mostrata). Il riepilogo aggiunge
`late_choices`, `prediction_mismatches`, `resyncs`, `hedge_losers`,
`hedged_answers` e i contatori della speculazione. Il registro usa
`protocol: "choice-buttons-predictive-v1"`, revisione prompt 1.

Limiti: lo snapshot nativo di nes_py non trasferisce tutto lo stato fra istanze
dell'emulatore, quindi raramente (2 scelte su ~440 nel benchmark) la posizione
reale differisce di 1–2 px da quella prevista; il runner lo rileva e risincronizza.
La cadenza dipende dalla CPU locale: le vittorie sono state ottenute con ~2900 frame/s
di emulazione su 8 thread (anteprime in ~0,25 s). Il runner misura il throughput
all'avvio, lo registra come `emulation_throughput` e avvisa sotto 2000 frame/s:
con la CPU occupata da altre applicazioni le scelte diventano lente e in ritardo e
il risultato non è rappresentativo.
Le anteprime rendono il compito diverso dal `realtime` puro: confrontare le due
modalità separatamente.

## Protocollo a mosse calibrate (`--control-mode moves`)

Il client invia le richieste a `https://openrouter.ai/api/alpha/decisions` su connessioni HTTP persistenti, preparate prima del reset di ogni episodio, usando lo [schema OpenRouter](https://openrouter.ai/openapi.json). `state` è un array con una parte `text` (JSON compatto) e una parte `image_url` (screenshot PNG/base64 RGB originale 240×256). Il testo contiene solo ciò che serve a decidere:

| Campo | Contenuto |
| --- | --- |
| `mario` | `size` (small/big/fire), `on_ground`, `vertical` (rising/falling/none), `speed` in px/frame, `screen_x` nello screenshot e `jump_reach_px` (distanza in avanti coperta da salto corto e alto alla velocità attuale, interpolata fra le misure da fermo, camminando e correndo) |
| `progress` | `x`, `flag_x` (asta di 1-1, circa 3160) e `percent` |
| `nearby` | `enemies` (tipo, `dx`, `dy`, direzione e `speed` in px/frame), `obstacle_ahead` (primo muro entro 10 tile: tipo, `dx`, `height_tiles` sopra il terreno di Mario), `pit_ahead` (prima buca sotto o davanti a Mario: porzione visibile `dx`, `width_px`, bordi `near_edge_visible`/`far_edge_visible`, `width_is_lower_bound`, `under_mario`), `blocks` (blocchi ? e mattoni raggiungibili), `items` (fungo e altri power-up) |
| `move` | mossa corrente, fase (`running`, `ended`, `none`), `frames_executed`, `starting` (selezionata, ancora senza frame eseguiti), `ends` (`in N frames`, `at landing`, `ended`), `then` (sempre `no buttons`), `landing` (solo con la scena e quando la stima esiste: `in_frames`, frame fino all'atterraggio all'altezza di partenza, e `travel_px`, percorso orizzontale fino ad allora alla velocità attuale) e `response_in_frames` (mediana arrotondata degli ultimi cinque intervalli osservazione→ricezione in frame effettivi; `null` inizialmente, 0 a turni) |
| `recent_moves` | ultime tre mosse con delta x |
| `warnings` | solo se servono: nemico vicino (al massimo due, testo neutro senza suggerire mosse), mancato progresso, tempo sotto 100 |

`dx` è il bordo sinistro dell'oggetto meno quello di Mario (positivo a destra, Mario è largo 16 px); `dy` è l'altezza del bordo inferiore dell'oggetto sopra i piedi di Mario. 16 px = 1 tile. In `realtime`, quando la stima è disponibile, nemici, oggetti, muro e buca hanno anche `dx_at_response`: la distanza stimata alla **ricezione della risposta**, a velocità costanti (`dx + (speed oggetto − speed Mario) × response_in_frames`). La stima usa i frame effettivamente avanzati, comprese le risposte valide poi scartate come obsolete. La scelta viene applicata al primo tick utile; non esistono attese software per committed o atterraggio. Accelerazione, inversioni e collisioni possono rendere inesatta la proiezione; il modello deve considerare anche `dx`. All'inizio manca una stima; a turni il gioco è fermo: in entrambi i casi la proiezione non viene aggiunta. Livello, vite, frame trascorsi, `y_pos` grezza e indici non vengono inviati.

**Scena dalla RAM.** `app/scene.py` legge la RAM NES a ogni frame e la espone in `info["scene"]`: posizione e velocità di Mario e dei nemici, mappa dei tile visibili (tubi, scale, mattoni, blocchi ?, terreno) e slot del power-up. Riporta solo ciò che è sullo schermo; i blocchi nascosti non compaiono e i Goomba schiacciati vengono esclusi. Il modello riceve quindi misure esatte invece di doverle stimare dai pixel. Con `--no-scene` il runner rimuove la scena dall'osservazione e il prompt chiede di ricavare tutto dallo screenshot, per confrontare le due percezioni.

Per le buche, `dx` indica l'inizio della **porzione visibile**, che può trovarsi dietro Mario durante l'attraversamento. `width_px` conta solo i pixel visibili, anche nelle tile parzialmente sullo schermo: se manca uno dei bordi, `width_is_lower_bound` è vero e la larghezza completa resta sconosciuta. `under_mario` indica sovrapposizione orizzontale con i 16 pixel di Mario, anche durante un salto sopra la buca; non significa che stia già cadendo. La scansione non legge tile fuori dallo schermo per dedurre bordi nascosti. Anche `dx_at_response` proietta la porzione visibile, senza inventare la posizione di un bordo sconosciuto.

**Guida di gioco.** Le istruzioni riportano obiettivo e priorità (sopravvivere, avanzare, fungo, monete), effetto dei contatti per Mario piccolo e grande, come trattare Goomba, Koopa e gusci, buche, tubi e scale, cosa fanno blocchi ?, funghi e mattoni, e la legenda delle coordinate. Le descrizioni delle mosse includono la portata misurata: un salto alto copre circa 3 tile da fermo, 5 camminando e 9 in corsa, con 4–5 tile di altezza. La revisione 2 distingue i contatti dannosi dallo schiacciamento di un Goomba, chiarisce che camminare o rilasciare i pulsanti non elimina subito l'inerzia e richiede di valutare i pericoli durante la latenza e l'attesa di esecuzione. Gli esempi di 35/55 frame non equivalgono a un numero fisso di decisioni. La portata dei salti resta approssimativa nelle condizioni calibrate.

La revisione 5 descrive mosse interrompibili e osservazioni acquisite dopo il primo frame. Una sequenza di salto scelta in aria non garantisce un decollo e non viene accodata all'atterraggio. Rilasciare A può accorciare il salto. Queste regole non garantiscono decisioni migliori sul provider.

**Immagini Jev.** Il provider richiede almeno 256 px per lato e 78.400 pixel totali ([limiti TypeSafe](https://docs.typesafe.ai/images#limits)). Dal 30 ottobre 2026 l'adapter condiviso aggiunge a ogni modello, non solo a Jev, 24 colonne nere a destra e 40 righe sotto, ottenendo 280×280 senza cambiare i pixel originali o le coordinate. Il prompt spiega di ignorare il bordo. La trasformazione compare nel trace `image_preprocessing`; gli screenshot salvati restano gli originali 256×240. Nei confronti considerare la diversa presentazione e il tempo di preparazione, incluso nelle misure.

`questions.next_action` è di tipo `choice`, con un criterio per ogni mossa più `continue`. Il client valida `answers.next_action.type`, `choice` e le chiavi delle probabilità contro il catalogo prima di eseguire la mossa. Confidence e probabilità, quando presenti, vengono registrate senza applicare soglie.

**Mosse.** Il catalogo `app/moves.py` è copiato in `config.json`. Durate e pulsanti calibrati restano invariati; tutte le sequenze sono interrompibili.

| Scelta | Sequenza |
| --- | --- |
| `wait` | Nessun pulsante per 10 frame |
| `walk_right` / `walk_left` | Direzione per 16 frame |
| `run_right` / `run_left` | Direzione + B per 16 frame |
| `short_jump_right` / `short_jump_left` | Direzione + A + B per 8 frame, poi direzione + B fino all'atterraggio |
| `high_jump_right` / `high_jump_left` | Direzione + A + B per 28 frame, poi direzione + B fino all'atterraggio |
| `double_jump_right` | Due salti alti, con atterraggio e A rilasciato fra i due; interrompibile in ogni fase |
| `high_jump_up` | A per 28 frame, poi nessun pulsante fino all'atterraggio |
| `continue` | Solo con mossa attiva: prosegue senza riavviarla o programmare ripetizioni |

L'atterraggio è letto dalla RAM NES (`0x001D`) in `info["on_ground"]`; il segmento fino all'atterraggio dura al massimo 60 frame. Una nuova sequenza di salto dopo A premuto inizia con un frame di rilascio (`release`), valido come primo frame prima della nuova richiesta. Un atterraggio anticipato conclude il salto; nel doppio salto passa al secondo. Ogni scelta può sostituire qualunque segmento, senza latch o attese. A fine sequenza si esegue `noop` (`waiting`), senza mantenere la direzione.

`continue` viene offerto solo con mossa attiva nell'osservazione. Se termina durante la richiesta, la risposta è non applicabile: nessun riavvio, pulsanti rilasciati, un frame e nuova richiesta. Un continue non offerto è una risposta invalida. `paused` resta a turni, con richiesta a fine mossa e senza continue quando manca una mossa attiva.

`JUMP_AIRTIME` conserva le misure su terreno piano: corto 27/30/29 frame e alto 44/48/50 nelle tre fasce di velocità. `move.landing` stima l'atterraggio all'altezza di partenza. Dopo una sostituzione in aria la stima è sconosciuta fino a un nuovo decollo da terra; resta sconosciuta anche per cadute senza salto o voli oltre il tempo previsto. Piattaforme e collisioni possono cambiare l'atterraggio reale.

Il contesto contiene mossa corrente o ultima, frame eseguiti, fine della sequenza, stima dell'atterraggio e latenza recente. Gli avvisi di mancato progresso e pericolo sono informativi: non eseguono manovre automatiche.

Prima del reset il runner attende la preparazione del worker, mantenendo la finestra responsiva. La preparazione HTTP ha un limite totale pari a `--request-timeout`; errori o timeout del preriscaldamento non impediscono la prima richiesta. Il setup è misurato separatamente dall'episodio. Durante il gioco, l'attesa viene interrotta dalla conclusione della richiesta: il runner acquisisce la risposta anche fra due frame, ma in realtime applica la decisione al primo frame consentito. Il risveglio non accelera il gioco e non genera chiamate multiple sulla stessa osservazione. Le operazioni sincrone, come uno step o il rendering, restano non interrompibili.

Le note sperimentali del 7–8 ottobre riportate sotto descrivono le revisioni allora in uso, inclusi `dx_at_move_start` e i vecchi avvisi. La revisione 2 usa invece distanze alla ricezione della risposta e non associa 35/55 frame a un numero fisso di decisioni.

È sempre in corso al massimo una richiesta. Dopo la prima osservazione, ogni richiesta realtime segue un frame eseguito dopo l’applicazione della scelta precedente. Una risposta è obsoleta se alla ricezione il gioco è avanzato di più di `--max-decision-frames` dallo screenshot. Dopo scarto o errore temporaneo ritentabile si richiede lo stato dopo il successivo frame, mentre la sequenza corrente prosegue. In `paused` il gioco non avanza durante la richiesta e le risposte non scadono. Il limite reale viene controllato fra le operazioni sincrone.

La soglia iniziale di 500 ms è stata corretta a 2 secondi dopo due prove live del 7 ottobre 2026: tutte le 40 decisioni ricevute erano state scartate, con età fra 580 ms e 1,65 secondi, e Mario era rimasto a x=40. Il modello sceglieva movimenti, ma il filtro impediva l'esecuzione. La prova con backend reale e modello simulato a 650 ms riproduce lo stallo con soglia 0,5 secondi e conferma l'avanzamento con soglia 2 secondi. I comandi restavano di 6 frame (circa 100 ms) seguiti da `noop`: il movimento avveniva a impulsi.
