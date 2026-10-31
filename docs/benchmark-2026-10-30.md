# Vittorie a velocità normale — 30 ottobre 2026

Livello 1-1, seed 123, gioco a 60 FPS che non si ferma mai durante le richieste.
Tutti i modelli usano lo stesso adapter `ChoiceModel` e ricevono **lo stesso
contesto**: stesso stato, stesse istruzioni, stesse scelte con le stesse
anteprime. Cambia solo l'identificativo del modello nella richiesta.

Questa configurazione è ora quella predefinita: `uv run main.py --episodes 10 --headless`
equivale al comando usato per il benchmark:

```powershell
uv run main.py --model decider --execution-mode predictive --choice-preview 30 --parallel-requests 2 --no-image --headless --episodes 10
```

## Risultati

| Modello | Vittorie | x massimo per episodio | Frame per vincere | Frame fra due scelte (mediana) | Latenza mediana / p95 | Costo noto $ |
| --- | ---: | --- | --- | ---: | --- | ---: |
| `decider` | **8/10** | 3161 ×8, 1792, 1964 | 1567–1831 | 49 | 0,299 / 0,332 s | 0,0383 |
| `d1` | **3/5** | 3161 ×3, 1438, 2404 | 1822–2415 | 40 | 0,232 / 0,256 s | 0,0280 |
| `gpt_luna` | **2/3** | 3161 ×2, 1603 | 2881–3405 | 60 | 0,428 / 0,634 s | 0,0726 |
| `jev` | **1/5** | 3161, 315, 1522, 1435, 2469 | 1776 | 36 | 0,209 / 0,235 s | 0,0350 |

Conferma con il codice finale (anticipo limitato, un thread per anteprima, stima
iniziale dal throughput, hook di passo nell'ombra), CPU libera (2326 frame/s
misurati all'avvio): **decider 9/10**, x 3161 ×9 e 2461, 1465–2234 frame per
vincere, una scelta ogni 42 frame (mediana), preparazione 0,21 s, 14 scelte in
ritardo su ~500, costo noto 0,0435 $ (`runs/20261030T101917-593605629b87`).

Prova del comando predefinito con la finestra (`uv run main.py --episodes 3`):
**decider 3/3**, 1578–2278 frame per vincere, 57,4–59,9 FPS, 3 scelte in ritardo su
154, 1414 frame/s misurati all'avvio, costo noto 0,0134 $, cioè 0,0045 $ a partita
(`runs/20261030T105025-c62219c67f62`). Il vsync bloccava il ciclo di gioco per
12 ms a frame e portava la finestra a 52 FPS nella prova precedente: ora è spento.

Costo medio a partita, vinte e perse, nelle sessioni della tabella: decider
0,0041 $ (20 partite, conferma inclusa), d1 0,0056 $, Jev 0,0070 $, Luna 0,0242 $.

Sessioni: `runs/20261030T091000-f9f06a85507f` (decider),
`runs/20261030T091616-391ee14b9988` (d1), `runs/20261030T091915-bd037d0b5ab9`
(Luna), `runs/20261030T091448-4def380c8ac0` (Jev). `runs/` non è versionata:
`config.json` e `summary.json` di queste sessioni, della conferma e della prova
con la finestra sono in [benchmark-data/2026-10-30/](benchmark-data/2026-10-30/).

- FPS effettivi fra 59,1 e 60,3 in tutti gli episodi.
- Dopo la prima scelta, ogni frame proviene da una scelta del modello
  (`source: "move"`); prima della prima scelta Mario resta fermo (`waiting`).
- Previsioni verificate: quando una scelta arriva in tempo, la posizione reale
  coincide con quella mostrata al modello, salvo 2 casi su ~440 scelte (Jev e
  d1) con 1–2 px di scarto. Causa misurata: lo snapshot nativo di nes_py non
  trasferisce tutto lo stato fra due istanze dell'emulatore (il byte RAM `0x705`,
  forza orizzontale sub-pixel, diverge dal primo frame dopo il caricamento in
  un'altra istanza, non nella stessa). Il runner rileva lo scarto e rifà le
  previsioni dallo stato reale. Rigiocando gli input registrati si ottengono
  esattamente le posizioni registrate.
- Scelte in ritardo: 11 su ~440 per decider, 0–3 per gli altri. Una scelta in
  ritardo si applica appena arriva; le previsioni successive vengono rifatte
  dallo stato reale (`resync`).
- La latenza comprende rete e servizio OpenRouter, non è il solo tempo di
  inferenza. Il costo è la somma di `usage.cost` delle risposte ricevute,
  incluse le copie parallele non usate; le richieste cancellate a fine episodio
  possono avere un costo non riportato.

Confronto con il [benchmark del 29 ottobre](benchmark-2026-10-29.md): con il
gioco a 60 FPS nessun modello aveva vinto in 120 partite; il miglior x era 1797.

## Che cosa è cambiato

### 1. Il modello vede l'istante in cui la sua scelta avrà effetto

In realtime lo screenshot inviato era vecchio di 13–26 frame quando la scelta
partiva. Ora, mentre la richiesta è in volo, il gioco continua con i pulsanti
già scelti; poiché sono noti, un **emulatore ombra** li riproduce da uno
snapshot (`MarioGame.snapshot` / `simulate`) fino al frame in cui la prossima
scelta sarà applicata. Il modello riceve stato (e, se attivo, screenshot) di
quel frame. Una risposta che arriva prima aspetta il suo frame; una in ritardo
si applica subito. L'emulatore nativo rilascia il GIL, quindi l'ombra gira in
thread separati senza rallentare i 60 FPS.

Solo questo, senza anteprime, ha portato decider a x 1434–1524 nelle prime
due partite (contro un x mediano di 434 il 29 ottobre), senza vittorie, con una
scelta ogni ~26 frame.

### 2. Anteprima emulata di ogni scelta

Per ciascuna scelta offerta l'emulatore ombra simula che cosa succede tenendola
per la durata prevista più 10 frame, prolungando finché Mario è in aria o sopra
una buca. Il risultato è scritto in fondo alla descrizione dell'opzione:
`Preview: Mario dies after 21 frames.` oppure
`Preview: alive after 43 frames, 90 px right, on the ground.` È informazione: il
programma non sceglie, non scarta opzioni e non suggerisce mosse.

Collocare l'anteprima nella descrizione dell'opzione (e non in un campo dello
stato) ha ridotto le scelte di opzioni segnate "dies" quando esistevano
alternative vive.

### 3. Scelte che rendono esprimibili i salti necessari

Con una scelta ogni ~40–50 frame, "tieni i pulsanti fino alla prossima scelta"
non permette alcune manovre. Il catalogo predittivo (`PREDICTIVE_MOVES`) ha 10
scelte, tutte selezionate dal modello come sequenze fisse:

- i pulsanti tenuti fino alla prossima scelta (`noop`, `left`, `left_run`,
  `right`, `right_run`, `right_jump`, `right_run_jump`);
- `right_hop`, `right_run_hop`: A per 8 frame, poi tutti i pulsanti rilasciati
  (salire su un gradino e fermarsi);
- `right_run_then_jump`: right+B per 4 frame, poi right+B+A.

Un input con A scelto a terra mentre A è già premuto inizia con un frame senza
A, perché il NES veda una nuova pressione: fa parte del salto scelto, in aria A
resta premuto. Sono stati tolti il salto verticale e i salti verso sinistra,
rari in 1-1, perché ogni scelta costa un'anteprima per richiesta.

Misura che ha motivato `right_run_then_jump`: dal gradino più alto prima della
buca fra le due scalinate, un salto da fermo cade nella buca; 4 frame di corsa
prima di A bastano per superarla. Prima di questa scelta 4 morti su 5 avvenivano
lì (x≈2470) o Mario restava fermo fino al limite di frame.

### 4. Copie parallele della stessa richiesta

`--parallel-requests 2` invia due copie identiche; vale la prima risposta.
Elimina gli stalli del provider (una risposta arrivata dopo 1,45 s aveva fatto
correre Mario contro un Goomba) e abbassa il p95 della latenza di decider da
~0,5–0,6 s a 0,32–0,34 s. Il costo raddoppia (circa 0,004 $ per episodio con
decider).

### Altri segnali, uguali per tutti

- `No forward progress for N frames`, dopo 90 frame senza nuovo massimo di x;
- una frase di guida: un salto da fermo copre poco, prima di una buca larga
  avvicinarsi al bordo o prendere la rincorsa.

## Approcci valutati e scartati

- **Rami speculativi** (`--speculative-width`): mentre la risposta n è in volo,
  si invia una richiesta n+1 per ogni risposta possibile. Funziona (37/37 rami
  corretti, una scelta ogni 8–18 frame a 60 FPS), ma senza anteprime decider
  arrivava a x 300–1430. Con le anteprime il costo di emulazione diventa
  insostenibile: ~10 rami × 10 anteprime × ~50 frame per decisione, a ~2800
  frame/s su 8 thread. Resta disponibile come opzione sperimentale.
- **Cadenza minima fissa** di 16 frame senza speculazione: ogni scelta arrivava
  in ritardo. `--decision-frames` è ora un minimo, allungato dalla latenza.
- **Anteprime più corte della durata della scelta** (40 frame contro 45–56):
  mostravano "alive" per scelte che uccidevano subito dopo. L'orizzonte ora
  copre sempre la durata stimata più 10 frame.
- **15 scelte** (salti corti anche a sinistra e verticali): più tempo di
  anteprima, cadenza ~52 frame, risultati peggiori.

## Limiti

- 23 episodi in tutto sul solo livello 1-1 e un solo seed. Il modello ed
  emulatore sono quasi deterministici: gli episodi differiscono per la latenza,
  che cambia i frame in cui le scelte cadono.
- Le anteprime sono calcolate dall'emulatore: il modello non deve prevedere la
  fisica, ma scegliere fra esiti dichiarati. È un ambiente diverso dal
  realtime puro del 29 ottobre e va confrontato separatamente.
- Il prompt è stato corretto osservando le morti di decider in 1-1; alcune
  scelte (`right_run_then_jump`) e frasi descrivono situazioni di questo livello.
- Senza immagine (`--no-image`): lo stato dalla RAM descrive solo ciò che è
  sullo schermo. Con l'immagine attiva la preparazione delle richieste resta
  identica per tutti i modelli (screenshot 280×280 con bordo nero).
- La modalità dipende dalla CPU locale (qui un i5-1145G7, 4 core/8 thread). Le
  partite del benchmark sono state giocate con ~2900 frame/s di emulazione su 8
  thread e anteprime pronte in ~0,25 s. Più tardi, con altre applicazioni attive,
  il throughput è sceso a 950–1700 frame/s: preparazione 0,7–1,6 s, scelte ogni
  86–90 frame e quasi tutte in ritardo, 0 vittorie in 14 episodi di decider
  (sessioni `runs/20261030T094234-…`, `094519-…`, `094640-…`, `095738-…`).
  Da allora il runner misura il throughput all'avvio (`emulation_throughput`
  in `events.jsonl`) e avvisa sotto 2000 frame/s; sotto carico non anticipa più
  le proiezioni (troppo costose) e accetta durate fino a 90 frame invece di
  arrivare in ritardo. Con queste correzioni, a 1263 e 1314 frame/s decider ha
  fatto 3/5 e 1/5 (`101418-…`, `101708-…`). Tutte le sessioni di decider dal
  benchmark in poi, comprese quelle sotto carico, sommano 25 vittorie su 48.
- Luna: nella prima prova della modalità il provider ha risposto due volte
  HTTP 502 alla stessa richiesta, arrestando la sessione.

Costo noto di tutte le prove live del 30 ottobre: circa 0,65 $, incluse le prove
di sviluppo e quelle sotto carico.
