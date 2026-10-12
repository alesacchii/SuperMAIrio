# SuperMAIrio

SuperMAIrio è un progetto scientifico che utilizza Super Mario come ambiente sperimentale per esplorare le potenzialità dei **System One Model**: modelli orientati a decisioni rapide, con risposte essenziali che indicano quale azione compiere.

## Obiettivo del progetto

Il progetto vuole studiare quanto velocemente questi modelli riescano a prendere decisioni utili in una situazione dinamica. Super Mario rende osservabili le conseguenze di ogni scelta: avanzare, saltare o aspettare può permettere di superare un ostacolo oppure causare la perdita di una vita.

L'obiettivo è misurare sia la qualità delle decisioni sia la loro frequenza nel tempo. Vogliamo capire se la rapidità di questa categoria di modelli consente di effettuare molte decisioni in un breve intervallo e se questo vantaggio si traduce in un controllo efficace del gioco.

Il risultato atteso è una dimostrazione accompagnata da misure sperimentali: Mario controllato dal modello e dati che mostrino velocità, capacità di reazione e prestazioni.

## Modelli e accesso tramite OpenRouter

Useremo modelli della categoria System One Model attraverso **OpenRouter**, con richieste orientate alla sola decisione: il modello dovrà scegliere l'azione da eseguire, senza produrre spiegazioni estese.

Il primo modello configurato è **GPT Luna**, identificativo OpenRouter [`openai/gpt-6-luna-decisions`](https://openrouter.ai/openai/gpt-6-luna-decisions). Il client usa la Decisions API OpenRouter con una domanda `Choice` sulle dieci azioni consentite. **Jev** resta un candidato per confronti successivi.

Il progetto riguarda l'utilizzo e il confronto di questi modelli. La scelta del modello dovrà poter cambiare mantenendo lo stesso ambiente di gioco e le stesse condizioni sperimentali.

## Come il modello controllerà Mario

Il gioco verrà eseguito in un ambiente controllabile dal progetto. A intervalli regolari, il sistema raccoglierà un'osservazione della situazione, la invierà al modello tramite OpenRouter e riceverà una decisione. Quella decisione verrà tradotta nei comandi di Mario.

Il ciclo sarà continuo: **osservazione del gioco → decisione del modello → azione di Mario → nuova osservazione**.

Le azioni disponibili comprenderanno movimenti semplici, come andare a destra o a sinistra, saltare, correre e restare fermi, oltre alle combinazioni necessarie per giocare. Il modello sceglierà fra queste possibilità.

La rappresentazione dell'osservazione verrà scelta in base alle capacità dei modelli: immagini del gioco oppure una descrizione compatta dello stato. Nei confronti, tutti i modelli dovranno ricevere informazioni equivalenti; anche il tempo necessario a prepararle farà parte delle misure.

## La velocità come elemento centrale

Per dimostrare il valore delle decisioni rapide, sarà fondamentale osservare il comportamento mentre il gioco avanza. Il modello dovrà reagire a ostacoli, nemici e cambiamenti della scena con un ritardo abbastanza contenuto da rendere utile la scelta.

Una prima verifica potrà prevedere pause tra le azioni per controllare il collegamento con il gioco. La dimostrazione della velocità richiederà invece esperimenti con il gioco in movimento e una misura del tempo reale trascorso.

Misureremo separatamente il tempo di risposta delle richieste e il tempo dell'intero ciclo, dall'osservazione all'esecuzione del comando. Le prestazioni osservate tramite OpenRouter comprenderanno anche rete, instradamento e servizio del modello: questi fattori dovranno essere considerati nell'interpretazione dei risultati.

## Cosa misureremo

- **Rapidità:** tempo necessario per ottenere una decisione, inclusi i ritardi occasionali.
- **Frequenza:** numero di decisioni ricevute e di azioni effettivamente eseguite al secondo.
- **Reattività:** tempo tra un cambiamento del gioco e l'esecuzione dell'azione conseguente.
- **Efficacia:** avanzamento nel livello, ostacoli superati, vite perse e livelli completati.
- **Affidabilità:** decisioni utilizzabili, richieste fallite e risposte arrivate troppo tardi.
- **Costo:** costo delle decisioni e delle sessioni di gioco.

Molte decisioni al secondo saranno un risultato interessante se riusciranno anche a guidare Mario con efficacia. Studieremo quindi il rapporto fra velocità e qualità delle scelte.

## Metodo sperimentale

Partiremo da un singolo livello e da un insieme limitato di azioni. Ripeteremo più sessioni per ogni modello, mantenendo comparabili osservazioni, velocità del gioco, durata dei comandi e budget di tempo reale.

Confronteremo i modelli anche con un comportamento casuale e con una semplice strategia predefinita. Registreremo le condizioni delle prove e la variabilità dei risultati, così da distinguere un comportamento ripetibile da una singola sessione riuscita.

Una dimostrazione visiva mostrerà Mario insieme alle decisioni del modello e ai loro tempi, rendendo leggibile il legame fra ciò che accade nel gioco e la risposta del sistema.

## Fasi del progetto

1. Preparare l'ambiente di gioco e verificare che i comandi possano controllare Mario.
2. Collegare OpenRouter e un primo System One Model al ciclo di osservazione e azione.
3. Misurare la velocità delle decisioni e il comportamento durante il gioco.
4. Confrontare più modelli in condizioni equivalenti.
5. Realizzare una dimostrazione e raccogliere i risultati sulle potenzialità e sui limiti di questa categoria.

## Stato attuale

Il primo livello dispone di tre controller: modello (predefinito), demo e tastiera. Il ciclo OpenRouter con screenshot, decisione e azione è implementato e verificato sia offline sia sul servizio reale. L'ambiente Python è gestito con **uv**.

La fase 4 introduce il gioco continuo a 60 FPS, il rilascio dei pulsanti durante le richieste, lo scarto delle osservazioni obsolete e misure per tentativo e sessione. Il controllo continuo è verificato con modello simulato e backend reale, anche con finestra; il precedente controllo live verifica il protocollo con pause.

Dall'8 ottobre 2026 il modello sceglie **mosse** complete (salto alto, doppio salto, corsa…) con una sola richiesta in corso, al posto dei pulsanti mantenuti e delle richieste sfalsate. Il ciclo è verificato offline e con emulatore reale. Nelle prime sessioni live a 60 FPS Mario ha raggiunto x≈1270–1410. Dalla stessa data il modello riceve anche una guida di gioco e una scena letta dalla RAM (nemici, muri, buche, blocchi, power-up); l'effetto sul provider deve ancora essere misurato.

Il 7 ottobre 2026 GPT Luna ha riconosciuto correttamente due immagini, rossa e blu, senza indicazioni testuali del colore. Il successivo tentativo live di 12 frame ha ricevuto ed eseguito due decisioni, facendo avanzare Mario da x=40 a x=44. Il formato multimodale `state` è quindi verificato su OpenRouter. Questa prova breve verifica il collegamento e non dimostra ancora il completamento del livello o l'efficacia del controllo in tempo reale.

## Installazione e avvio

Su Windows con Python 3.13 e uv, dalla cartella del progetto:

```powershell
uv sync --locked

# Impostare la chiave per la sessione PowerShell corrente
$env:OPENROUTER_API_KEY = 'la-tua-chiave-openrouter'

# Avvio predefinito con GPT Luna e finestra
uv run main.py
```

In alternativa, copiare `.env.example` in `.env` e compilare `OPENROUTER_API_KEY`. Il file `.env` viene letto dalla cartella del progetto; una variabile già presente nell'ambiente ha precedenza. La chiave non viene salvata nei risultati. Demo e tastiera non richiedono credenziali.

Il comando predefinito apre il livello **1-1** in modalità continua, con un ciclo **Chiamo → Decisione → Azione → Chiamo**: screenshot e stato vengono inviati al modello, che sceglie una **mossa** completa (per esempio un salto alto, che tiene A premuto per 28 frame). Appena la mossa inizia parte la richiesta successiva, mentre la mossa prosegue; c'è sempre una sola richiesta in corso. Prima della prima decisione Mario resta fermo con `noop`, cioè tutti i pulsanti rilasciati. Morte, completamento, limite di frame o limite reale terminano il tentativo; `--episodes` avvia tentativi indipendenti.

```powershell
# Giocare da tastiera
uv run main.py --mode manual

# Avviare la demo deterministica
uv run main.py --mode demo

# Due tentativi della demo, senza finestra
uv run main.py --mode demo --headless --episodes 2

# Breve sessione modello senza finestra
uv run main.py --headless --max-frames 120

# Conservare gli screenshot per ricostruire richieste e scelte
uv run main.py --save-screenshots

# Prova continua: budget reale e soglia di età delle osservazioni
uv run main.py --headless --max-episode-seconds 60 --max-decision-frames 120

# Solo screenshot, senza la scena letta dalla RAM (confronto della percezione)
uv run main.py --no-scene

# Gioco rallentato a 30 FPS per compensare la latenza del modello
uv run main.py --game-fps 30

# A turni: gioco fermo durante le richieste, nuova richiesta a fine mossa
uv run main.py --execution-mode paused --save-screenshots

# Modificare limite dell'episodio e seed
uv run main.py --max-frames 1800 --seed 123

# Selezionare esplicitamente modello e timeout totale della richiesta
uv run main.py --model gpt_luna --request-timeout 10

# È valido anche l'identificativo OpenRouter del modello configurato
uv run main.py --model openai/gpt-6-luna-decisions --request-timeout 10

# Tutte le opzioni
uv run main.py --help
```

Se l'accesso alla cache uv predefinita è limitato, usare `uv --cache-dir .uv-cache` al posto di `uv` nei comandi precedenti.

| Tasto | Comando |
| --- | --- |
| Frecce sinistra/destra | Movimento |
| Spazio | Salto, pulsante NES A |
| Shift sinistro/destro | Corsa, pulsante NES B, con una direzione |
| R | Reset del tentativo, anche dopo la fine |
| Esc o chiusura finestra | Arresto |
| Ctrl+C nel terminale | Arresto con codice di uscita 130 |

Le combinazioni sono consentite. Premere entrambe le direzioni annulla il movimento direzionale; il salto resta disponibile. Il rilascio dei tasti e la perdita del focus cancellano i pulsanti corrispondenti. Dopo la fine di un tentativo manuale il gioco attende R, senza avanzare.

Le impostazioni predefinite sono: modalità `model`, esecuzione `realtime`, modello `openai/gpt-6-luna-decisions`, timeout `10` secondi, seed `123`, `1` episodio, limite di `3600` frame e `60` secondi reali per episodio, età massima dell'osservazione `120` frame di gioco, scena dalla RAM attiva, gioco a `60` FPS e screenshot su disco disattivati. `--episodes` riguarda modello e demo; la tastiera aggiorna il comando a ogni frame. La demo esegue una sequenza fissa di mosse con lo stesso esecutore del modello. Le nuove opzioni di esecuzione e registrazione riguardano il modello; soglia di età e limite reale si applicano solo a `realtime`. `--mode manual --headless` viene rifiutato. La demo verifica il controllo, non è una strategia per completare il livello.

La finestra mostra modalità, mossa corrente con la fonte dei pulsanti (`move`, `release`, `tail` o `waiting`), frame, posizione, attesa, latenza dell'ultima richiesta, numero di mosse iniziate e risposte obsolete. L'indicazione dell'ultima risposta scartata, con età e soglia, rimane visibile durante l'attesa successiva fino all'arrivo di una nuova decisione. Dopo tre risposte obsolete consecutive il terminale stampa un avviso una sola volta per episodio; il conteggio consecutivo riparte con la prima decisione applicata. Il modello in `realtime` avanza a un massimo di 60 FPS anche senza finestra, senza recuperare ritardi in accelerazione. In `paused` il gioco si ferma durante le richieste; le mosse senza finestra procedono alla velocità disponibile. La tastiera conserva il comportamento precedente. Si contano i frame restituiti da `step`: il backend può saltare internamente transizioni e schermate di caricamento. La modalità con pause è identificata come debug nei risultati.

### Protocollo Decisions e risultati

Il client invia le richieste a `https://openrouter.ai/api/alpha/decisions` su connessioni HTTP persistenti, aperte all'inizio di ogni episodio, usando lo [schema OpenRouter](https://openrouter.ai/openapi.json). `state` è un array con una parte `text` (JSON compatto) e una parte `image_url` (screenshot PNG/base64 RGB originale 240×256). Il testo contiene solo ciò che serve a decidere:

| Campo | Contenuto |
| --- | --- |
| `mario` | `size` (small/big/fire), `on_ground`, `vertical` (rising/falling/none), `speed` in px/frame, `screen_x` nello screenshot e `jump_reach_px` (distanza in avanti coperta da salto corto e alto alla velocità attuale, interpolata fra le misure da fermo, camminando e correndo) |
| `progress` | `x`, `flag_x` (asta di 1-1, circa 3160) e `percent` |
| `nearby` | `enemies` (tipo, `dx`, `dy`, direzione e `speed` in px/frame), `obstacle_ahead` (primo muro entro 10 tile: tipo, `dx`, `height_tiles` sopra il terreno di Mario), `pit_ahead` (`dx`, `width_px`), `blocks` (blocchi ? e mattoni raggiungibili), `items` (fungo e altri power-up) |
| `move` | mossa corrente, fase (`committed`, `running`, `ended`, `none`), `ends` (`in N frames`, `at landing`, `ended`), `then` (pulsanti tenuti dopo la fine, per esempio `holds right+B`) e `your_move_starts_in_frames` (latenza mediana × FPS; 0 a turni) |
| `recent_moves` | ultime tre mosse con delta x |
| `warnings` | solo se servono: nemico vicino (al massimo due, testo neutro senza suggerire mosse), mancato progresso, tempo sotto 100 |

`dx` è il bordo sinistro dell'oggetto meno quello di Mario (positivo a destra, Mario è largo 16 px); `dy` è l'altezza del bordo inferiore dell'oggetto sopra i piedi di Mario. 16 px = 1 tile. In `realtime` nemici, oggetti, muro e buca hanno anche `dx_at_move_start`: la distanza prevista quando la mossa scelta partirà, a velocità costanti (`dx + (speed oggetto − speed Mario) × your_move_starts_in_frames`). Il prompt chiede di decidere su questo valore. A turni il gioco è fermo e il campo non c'è. Livello, vite, frame trascorsi, `y_pos` grezza e indici non vengono più inviati.

**Scena dalla RAM.** `app/scene.py` legge la RAM NES a ogni frame e la espone in `info["scene"]`: posizione e velocità di Mario e dei nemici, mappa dei tile visibili (tubi, scale, mattoni, blocchi ?, terreno) e slot del power-up. Riporta solo ciò che è sullo schermo; i blocchi nascosti non compaiono e i Goomba schiacciati vengono esclusi. Il modello riceve quindi misure esatte invece di doverle stimare dai pixel. Con `--no-scene` il runner rimuove la scena dall'osservazione e il prompt chiede di ricavare tutto dallo screenshot, per confrontare le due percezioni.

**Guida di gioco.** Le istruzioni riportano obiettivo e priorità (sopravvivere, avanzare, fungo, monete), effetto dei contatti per Mario piccolo e grande, come trattare Goomba, Koopa e gusci, buche, tubi e scale, cosa fanno blocchi ?, funghi e mattoni, e la legenda delle coordinate. Le descrizioni delle mosse includono la portata misurata: un salto alto copre circa 3 tile da fermo, 5 camminando e 9 in corsa, con 4–5 tile di altezza. Rispetto al prompt precedente lo state è più piccolo del 60% e il testo complessivo cresce di circa il 18% (≈130 token), poco rispetto all'immagine.

`questions.next_action` è di tipo `choice`, con un criterio per ogni mossa più `continue`. Il client valida `answers.next_action.type`, `choice` e le chiavi delle probabilità contro il catalogo prima di eseguire la mossa. Confidence e probabilità, quando presenti, vengono registrate senza applicare soglie.

**Mosse.** Il catalogo è in `app/moves.py` e viene copiato in `config.json`. Ogni mossa è una sequenza di segmenti (pulsanti, frame), eseguita un frame alla volta:

| Mossa | Copione |
| --- | --- |
| `wait` | Nessun pulsante per 10 frame |
| `walk_right` / `walk_left` | Direzione per 16 frame |
| `run_right` / `run_left` | Direzione + B per 16 frame |
| `short_jump_right` / `short_jump_left` | Direzione + A + B per 8 frame (committed), poi direzione + B fino all'atterraggio |
| `high_jump_right` / `high_jump_left` | Direzione + A + B per 28 frame (committed), poi direzione + B fino all'atterraggio |
| `double_jump_right` | Salto alto, atterraggio con A rilasciato, secondo salto alto: committed fino alla fine del secondo A |
| `high_jump_up` | A per 28 frame (committed), poi nessun pulsante fino all'atterraggio |
| `continue` | La mossa in corso prosegue; se è già finita viene ripetuta |

I frame sono stati calibrati sul livello 1-1: tenendo A per circa 25 frame Mario raggiunge l'altezza massima (64 px). Con la rincorsa, `high_jump_right` supera tutti e quattro i tubi del livello. L'atterraggio è letto dalla RAM NES (`0x001D`, stato di galleggiamento del giocatore) ed esposto in `info["on_ground"]`; un segmento "fino all'atterraggio" dura al massimo 60 frame. Quando una mossa con salto segue un frame con A premuto, l'esecutore rilascia A per un frame (`release`). Se Mario torna a terra prima della fine della parte committed (testa contro un blocco, atterraggio anticipato su un tubo o una scala), il salto è finito: la parte committed termina subito, A viene rilasciato e la mossa successiva può partire; nel doppio salto parte il secondo salto. Finito il copione, direzione e corsa dell'ultimo segmento restano premute senza A (`tail`) fino alla decisione successiva.

Una mossa nuova parte subito, salvo due casi: se la mossa corrente è in un segmento committed (la parte con A di un salto) attende la fine di quel segmento; se è un salto e Mario è in aria, attende l'atterraggio. L'evento `move_deferred` ne registra il motivo (`committed` o `airborne`). La richiesta successiva parte quando la decisione viene applicata, quindi nessuna chiamata parte durante l'attesa.

Il runner fornisce all'adapter il contesto `control` con `current_move`, `move_frames`, `move_finished`, `move_committed`, latenza recente e le ultime otto mosse, da cui l'adapter compone lo state. Dopo 120 frame con escursione orizzontale non superiore a 2 pixel e almeno 30 frame direzionali, segnala mancato progresso e suggerisce di cambiare strategia. Le coordinate mancanti rendono il rilevamento sconosciuto. Non vengono eseguite manovre automatiche.

È sempre in corso al massimo una richiesta. In `realtime` la richiesta parte all'inizio e subito dopo ogni decisione applicata, mentre la mossa è in corso; in `paused` parte quando la mossa è terminata e il gioco resta fermo fino alla risposta. In `realtime` una risposta viene scartata se, al momento della **ricezione**, il gioco è avanzato di più di `--max-decision-frames` frame dallo screenshot, anche quando la risposta era pronta ma il runner l'ha acquisita in ritardo. La soglia è in frame perché conta quanto è cambiata la scena: a 30 FPS il modello dispone del doppio del tempo reale. In `paused` il gioco non avanza e nessuna risposta è obsoleta. L'attesa di una mossa differita dietro un salto è voluta e non conta. Dopo lo scarto viene richiesto lo stato corrente e la mossa in corso prosegue. Il limite reale viene controllato fra le operazioni: preparazione, rendering e singoli step sincroni possono farlo superare fino al controllo successivo; non si interrompe uno step a metà.

La soglia iniziale di 500 ms è stata corretta a 2 secondi dopo due prove live del 7 ottobre 2026: tutte le 40 decisioni ricevute erano state scartate, con età fra 580 ms e 1,65 secondi, e Mario era rimasto a x=40. Il modello sceglieva movimenti, ma il filtro impediva l'esecuzione. La prova con backend reale e modello simulato a 650 ms riproduce lo stallo con soglia 0,5 secondi e conferma l'avanzamento con soglia 2 secondi. I comandi restavano di 6 frame (circa 100 ms) seguiti da `noop`: il movimento avveniva a impulsi.

**Previsione e fine della mossa (8 ottobre 2026).** Con la scena attiva, sei sessioni live hanno dato il primo livello completato (`runs/20261008T083026-d25c960d1587/`, 25 s, $0,0077) e tre morti con cause distinte. Senza scena entrambi i tentativi sono morti al primo Goomba.
- In `083058` il modello vedeva il Goomba a 69 px, ma la mossa partiva 16 frame dopo, con il Goomba a circa 11 px: da qui `dx_at_move_start`.
- In `083341`, durante un salto, ha risposto `continue` otto volte mentre la buca si avvicinava; all'atterraggio la coda (destra+B) l'ha portato nella buca. Da qui `move.ends`, `move.then` e la precisazione che `continue` non programma nulla: per saltare all'atterraggio va scelto il salto già in volo.
- In `083105` una risposta ha impiegato 1,15 s (p95 0,28 s) mentre la coda correva verso i nemici. Non c'è un limite automatico alla coda: non avrebbe evitato le morti osservate e sarebbe una manovra non scelta dal modello.

**Salti accorciati (8 ottobre 2026).** Sei sessioni successive (`runs/20261008T0850…`) sono finite senza vittorie. In 12 salti Mario era tornato a terra prima dei 28 frame committed, per un blocco sopra la testa o un atterraggio su un rialzo, ma l'esecutore continuava a tenere A: Mario non poteva risaltare e nessuna mossa poteva partire. Tre morti (contro il Koopa a x≈1675 dopo il mattone a x≈1616, e contro un Goomba a x≈2762) sono avvenute pochi frame dopo. Ora l'atterraggio chiude la parte committed. Con uno script guidato dalla scena, i frame con A premuto a terra passano da 11 a 0. Le altre due morti dipendevano da una risposta in 1,1 s e da un atterraggio accanto a un Goomba.

**Corsa e primo Goomba (8 ottobre 2026).** Sui 19 run disponibili il fattore decisivo al primo Goomba è la velocità di Mario quando il Goomba compare: camminando 7 run su 8 lo superano, correndo 2 su 9. Davanti a Mario sono visibili circa 128 px. Correndo, un nemico che compare sul bordo arriva in circa 35 frame (una decisione); camminando in circa 55 (tre decisioni). Il modello è passato dalla camminata alla corsa, probabilmente anche per un prompt che descriveva solo i vantaggi della corsa ("faster = longer"). Guida e descrizioni di `walk_right`/`run_right` ora riportano il costo in tempo di reazione, senza indicare quale mossa scegliere. Nello stesso periodo il provider ha avuto latenze mediane di 0,9–2,3 s: un episodio con mediana sopra 0,6 s è ora segnato `slow_provider` nel riepilogo e segnalato nel terminale come poco rappresentativo.

**Avviso di nemico vicino e portata dei salti (8 ottobre 2026).** Altri cinque run senza vittorie: tre morti al primo Goomba, ormai 5 su 14 dall'introduzione delle mosse. Nell'emulatore un salto supera il primo Goomba se parte quando il Goomba è fra 18 e 90 px. Nelle tre morti `dx_at_move_start` valeva 68, 85 e 49 alla richiesta decisiva, ma il modello ha continuato a correre. Lo state aggiunge ora un avviso neutro (`Attention: goomba close, dx 49 px when your move starts.`) per i nemici allo stesso livello di Mario entro 96 px dall'inizio della mossa; la scelta resta al modello. Una morte alle scale è arrivata saltando da fermo (portata circa 53 px) verso una buca che ne richiedeva circa 78: da qui `jump_reach_px`.

**Soglia in frame e retry (8 ottobre 2026).** Nella sessione a 30 FPS `runs/20261008T080404-d546c5fc2d2c/` il provider ha risposto in 5,2 e 2,7 secondi: con la soglia di 2 secondi reali entrambe le risposte sono state scartate, benché a 30 FPS 2,7 s siano solo 81 frame di gioco. Subito dopo un HTTP 504 ha chiuso la sessione. La soglia è ora in frame (default 120, cioè 2 s a 60 FPS) ed è previsto un solo nuovo tentativo per gli errori temporanei.

**Politica `hold` (7 ottobre 2026, sostituita dalle mosse).** Nella sessione live `runs/20261007T152829-0e88ff94e0db/` 1156 frame su 1288 erano `noop` d'attesa: il modello sceglieva `right_run` 21 volte di fila, ma Mario si fermava fra un comando e l'altro (x=163 in 24 secondi) e l'unico salto, durato 6 frame, era un saltello che non ha evitato il primo Goomba. In `paused` i comandi sono contigui e il movimento è fluido. Con `hold`, predefinita in `realtime`, la scelta resta premuta fino alla decisione successiva (al massimo `--max-hold-frames`, poi `noop`). Se il modello sceglie di nuovo un salto mentre A è già premuto e Mario è a terra (`y_pos` invariata negli ultimi tre frame), il runner rilascia A per un frame, così il salto riparte; in aria A resta premuto per non accorciare il salto. Una risposta obsoleta viene scartata senza fermare l'azione in corso. Il prompt descrive l'azione mantenuta e include `recent_latency_seconds`, la mediana delle ultime cinque latenze. Con emulatore reale e modello simulato a 850 ms che sceglie sempre `right_run`, `noop` arriva a x=72 in 360 frame, mentre `hold` raggiunge x=315 in 156 frame (fino al primo Goomba). `--game-fps` rallenta il gioco in modo esplicito e registrato, per studiare il rapporto fra latenza e controllo; `--waiting-policy noop` conserva la politica precedente per i confronti.

**Connessione persistente e richieste sfalsate (7 ottobre 2026, sostituite dalle mosse).** Le sessioni `hold` a 30 e 15 FPS hanno raggiunto x≈1520, con `request_seconds` mediana 0,55–0,58 s e minimo 0,52 s, e circa 1,4 decisioni al secondo. Ogni richiesta creava un nuovo event loop e un nuovo client HTTP: una HEAD senza credenziali verso l'endpoint richiede in mediana 378 ms con client nuovo e 26 ms su connessione persistente. Ora il worker usa un event loop persistente e il client riusa le connessioni. Con una richiesta alla volta la reazione media a un evento è circa 1,5 volte la latenza; con richieste sfalsate ogni 100 ms diventa circa latenza + 50 ms, e un errore viene corretto dalla decisione successiva entro 0,1 s. In `hold` non c'è più il minimo di `--frames-per-action` prima della sostituzione: ritardava le nuove decisioni fino a 400 ms a 15 FPS. Il costo cresce con le decisioni al secondo; con limiti di frequenza del provider ridurre `--max-in-flight` o aumentare `--decision-interval`.

**Mosse e ciclo singolo (8 ottobre 2026).** Le sessioni `hold` mostravano un limite strutturale: ogni scelta valeva solo fino alla risposta successiva (~290 ms, circa 10 frame a 30 FPS). In `runs/20261007T160657-38126d0b67f2/` il modello alternava `right_run_jump` e `right_run` davanti al tubo alto a x=722 per 4 secondi: ogni `right_run` rilasciava A a metà salto e il tubo non veniva superato. Con quattro richieste sfalsate era inoltre difficile capire quale risposta comandasse. Ora ogni decisione è una mossa completa con una sola richiesta in corso; hold, richieste sfalsate e le opzioni `--waiting-policy`, `--max-in-flight`, `--decision-interval`, `--max-hold-frames` e `--frames-per-action` sono state rimosse. I risultati passano alla versione `3` e non sono direttamente confrontabili con le sessioni precedenti.

Gli errori temporanei del provider (HTTP 5xx, timeout, errori di connessione) ottengono **un solo** nuovo tentativo: l'evento `request_failed` lo registra, `retried_requests` lo conta e parte subito una nuova richiesta con l'osservazione corrente, mentre la mossa in corso prosegue. Un secondo errore consecutivo arresta la sessione con codice `1`; errori 4xx (incluso 429), rifiuti e risposte invalide la arrestano subito. Il timeout comprende l'intera richiesta HTTP. Fine episodio, Esc, chiusura finestra e Ctrl+C annullano la richiesta in corso; una risposta già completata viene registrata e scartata. Nessuna risposta attraversa il reset. R serve soltanto in modalità manuale.

Ogni sessione modello crea una cartella distinta sotto `runs/`, esclusa da Git, con:

- `config.json`: configurazione (compresi `scene` e `max_decision_frames`), protocollo `openrouter-choice-scene-v4`, versione risultati `4`, modalità, FPS e catalogo delle mosse, senza credenziali.
- `screenshots/`: presente con `--save-screenshots`, contiene i PNG inviati, numerati per richiesta; altrimenti il riferimento screenshot negli eventi è `null`.
- `events.jsonl`: osservazioni, decisioni, mosse (`move_start`, `move_continued`, `move_deferred`, `move_end` con esito `completed`, `replaced` o `interrupted`), frame effettivi con fonte e `on_ground`, scarti con motivo (età in frame e secondi e `max_decision_frames` negli scarti per ritardo), errori temporanei ritentati, cancellazioni, errori ed esiti, collegati da episodio e indice di richiesta.
- `summary.json`: riepilogo della sessione e di ogni tentativo, compresi quelli interrotti; `slow_provider` segnala i tentativi con latenza mediana sopra 0,6 s.

Tutti i timestamp usano `perf_counter`, in secondi sullo stesso orologio monotono. Le distribuzioni riportano numero di campioni, mediana e p95 nearest-rank; senza campioni mediana e p95 sono `null`.

| Misura | Definizione |
| --- | --- |
| `request_seconds` | Dall'avvio effettivo nel worker alla risposta validata; include rete e servizio, esclude il polling del runner. Campioni sulle decisioni ricevute. |
| `preparation_seconds` | Codifica PNG, costruzione payload ed eventuale salvataggio screenshot. |
| `polling_seconds` | Dalla risposta validata all'acquisizione nel runner. |
| `observation_age_seconds` | Dall'osservazione all'avvio della mossa scelta, compresa l'eventuale attesa dietro un salto. |
| `deferred_seconds` | Per le mosse differite, dalla ricezione della decisione all'avvio della mossa. |
| `observation_to_first_frame_seconds` / `observation_to_last_frame_seconds` | Dall'osservazione al ritorno del primo/ultimo frame della mossa, anche per mosse sostituite o interrotte. |
| `decisions_per_second` / `moves_per_second` | Decisioni ricevute / mosse iniziate (comprese le ripetizioni con `continue`), divise per il tempo reale dei tentativi. |
| `effective_fps` | Frame effettivamente eseguiti divisi per il tempo reale dei tentativi. |

Il tempo reale di ciascun tentativo parte dall'osservazione iniziale dopo reset e termina al rilevamento dell'esito o dell'arresto; comprende preparazione e attese, esclude setup, reset e chiusura del worker. Il totale è la somma delle durate dei tentativi. Una mossa viene contata in `moves` quando inizia, anche `wait`. `continues` conta le risposte `continue` e `deferred_moves` le mosse differite. `waiting_frames` conta i frame prima della prima mossa, `tail_frames` quelli dopo la fine del copione e `jump_release_frames` i frame di rilascio di A. Decisioni ricevute, risposte scartate, richieste cancellate, richieste ritentate (`retried_requests`) ed errori hanno contatori distinti. Una risposta acquisita durante la chiusura viene conteggiata e scartata.

I riepiloghi includono reward, posizione iniziale/finale/massima, morte, completamento e motivo della fine. La sessione somma i reward e conta morti e tentativi completati; la posizione iniziale è quella del primo tentativo, la finale quella dell'ultimo e la massima è il massimo fra i tentativi. `known_cost` somma soltanto costi numerici validi restituiti dalle decisioni ricevute; resta `null` se assenti. `cost_known_requests` e `cost_missing_received_requests` ne indicano la copertura: richieste cancellate o fallite possono aver consumato credito non riportato. Queste misure non isolano l'inferenza e il tempo osservazione→azione non prova da solo la reazione a uno specifico ostacolo.

### Aggiungere un modello

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

Se il nuovo modello usa lo stesso protocollo Choice multimodale di GPT Luna,
il file può riutilizzarne l'adapter:

```python
from app.models.gpt_luna import Model as GptLunaModel


class Model(GptLunaModel):
    model_id = "provider/identificativo-del-modello"
```

Usare un identificativo realmente disponibile e verificare che supporti quel
protocollo e gli input immagine. Per input, prompt o risposte differenti,
implementare i metodi dell'adapter nel nuovo file; `decide` deve restituire
una `Decision` con `move` uguale a una mossa del catalogo oppure `continue`.
`build_request` riceve `observation`, `png` e gli argomenti nominati `frames`,
`previous_move`, `previous_position` e l'opzionale `control_context=None`; restituisce una `DecisionRequest`
con `payload` da inviare e `trace` da registrare, entrambi senza credenziali.
Gli adapter devono accettare `control_context`, che il runner fornisce con
`execution_mode`, `stuck` (booleano o `None`), `recent_moves` (ultime otto mosse,
indice, frame e delta x), `current_move`, `move_frames`, `move_finished`, `move_committed`,
`move_remaining_frames` (`None` se la mossa finisce all'atterraggio) e `tail_action`.
In `realtime` aggiunge `game_fps` e `recent_latency_seconds` (mediana delle ultime cinque latenze).
La scena, se attiva, è in `observation.info["scene"]`; con `--no-scene` il runner la rimuove prima
di chiamare l'adapter, che deve funzionare anche senza.
L'assenza del contesto nelle chiamate dirette a GPT Luna produce il prompt a turni.
Le prove continue devono spiegare al modello il ciclo: nuova richiesta all'inizio della mossa,
salti non interrompibili e `continue`. Gli adapter basati su `OpenRouterClient` riusano le connessioni; `prepare()` e `aclose()` sono chiamati dal worker se presenti.

```powershell
uv run main.py --model nuovo_modello
```

Sono accettati il nome del file senza `.py` e il `model_id` dell'adapter.
Un modello non configurato viene segnalato prima dell'avvio del gioco.

### Backend e riproducibilità

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

```powershell
uv run python -m unittest discover -s tests -v

# Include le verifiche della finestra: richiede un desktop con OpenGL
$env:SUPERMAIRIO_TEST_DISPLAY = '1'
uv run python -m unittest discover -s tests -v
Remove-Item Env:SUPERMAIRIO_TEST_DISPLAY
```

I test coprono mapping, durata, sostituzione e rilascio, input invalidi, fine episodio, reset, errori e chiusura. Sul backend reale verificano RGB, movimento, salto e limite dei frame. Le verifiche opzionali del display inviano eventi Pyglet per combinazioni, rilascio, perdita del focus, reset e arresto; salvano una cattura del rendering in `.local/verification/`. Sono verifiche degli eventi applicativi, non una prova di consegna dei tasti fisici da parte di Windows.

I test Decisions offline verificano PNG e payload, tutte le scelte, configurazione e credenziali, errori HTTP, timeout totale, pausa durante l'attesa, cancellazione, fine episodio e risultati salvati. I test dell'esecutore verificano copioni, segmenti committed, atterraggio e rilascio di A. I test della scena verificano le convenzioni su una RAM sintetica e, sul livello reale, Goomba, blocchi ?, tubi alti 2, 3 e 4 tile e la prima buca. I test continui usano clock e worker simulati per il ciclo a richiesta singola, `continue`, mosse differite dietro un salto o fino all'atterraggio, coda, modalità a turni, soglia in frame, retry singolo, `--no-scene`, pacing, scarti, budget reale, storico, blocco, metriche e costi. Due prove usano emulatore reale e modello simulato, una con salti e atterraggi; una verifica opzionale del display controlla l'avanzamento durante l'attesa e Esc. Non effettuano chiamate a pagamento.

Per verificare il provider reale, impostare la chiave e attivare esplicitamente i test live. Questi inviano prima due immagini di colore diverso per controllare che i pixel vengano interpretati, poi eseguono un tentativo di gioco di 12 frame. Consumano credito OpenRouter e salvano la sessione di gioco in `runs/`.

```powershell
$env:SUPERMAIRIO_TEST_OPENROUTER = '1'
uv run python -m unittest discover -s tests -p test_openrouter_live.py -v
Remove-Item Env:SUPERMAIRIO_TEST_OPENROUTER
```

Se il controllo dei colori fallisce, il test non avvia la sessione di gioco. La verifica live ha superato tutti i controlli il 7 ottobre 2026; può essere ripetuta per verificare cambiamenti del provider o del modello.
