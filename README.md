# SuperMAIrio

SuperMAIrio è un progetto scientifico che utilizza Super Mario come ambiente sperimentale per esplorare le potenzialità dei **System One Model**: modelli orientati a decisioni rapide, con risposte essenziali che indicano quale azione compiere.

## Obiettivo del progetto

Il progetto vuole studiare quanto velocemente questi modelli riescano a prendere decisioni utili in una situazione dinamica. Super Mario rende osservabili le conseguenze di ogni scelta: avanzare, saltare o aspettare può permettere di superare un ostacolo oppure causare la perdita di una vita.

L'obiettivo è misurare sia la qualità delle decisioni sia la loro frequenza nel tempo. Vogliamo capire se la rapidità di questa categoria di modelli consente di effettuare molte decisioni in un breve intervallo e se questo vantaggio si traduce in un controllo efficace del gioco.

Il risultato atteso è una dimostrazione accompagnata da misure sperimentali: Mario controllato dal modello e dati che mostrino velocità, capacità di reazione e prestazioni.

## Modelli e accesso tramite OpenRouter

Oltre a Luna e Jev è disponibile l'adapter `decider`, identificativo
[`perplexity/pplx-decider-v1.2`](https://openrouter.ai/perplexity/pplx-decider-v1.2/).
Usa lo stesso prompt e controllo condivisi, senza regole specifiche di movimento.
Il 29 ottobre 2026 ha superato la verifica live delle immagini e una sessione
a turni di 12 frame. Un tentativo diretto a 10 FPS ha raggiunto x=2472 senza
completare il livello: è una prova rallentata, non una vittoria a velocità normale.

```powershell
uv run main.py --model decider --game-fps 10
```

È disponibile anche l'adapter `d1`, identificativo
[`liquid/d1.1`](https://openrouter.ai/liquid/d1.1) (Liquid AI, rilasciato il 27 ottobre 2026).
La scheda OpenRouter dichiara la Decisions API con input testo e immagini; usa lo stesso
prompt e controllo condivisi. Il supporto effettivo agli screenshot 256×240 non è ancora
stato verificato con il provider reale e non ci sono ancora risultati.

```powershell
uv run main.py --model d1 --execution-mode paused
```

Useremo modelli della categoria System One Model attraverso **OpenRouter**, con richieste orientate alla sola decisione: il modello dovrà scegliere l'azione da eseguire, senza produrre spiegazioni estese.

Il primo modello configurato è **GPT Luna**, identificativo OpenRouter [`openai/gpt-6-luna-decisions`](https://openrouter.ai/openai/gpt-6-luna-decisions). Il client usa la Decisions API OpenRouter con una domanda `Choice` sulle mosse disponibili, più `continue` quando una mossa è attiva. **Jev 1.14** è disponibile con `typesafe/jev-1.14` (alias `jev`), sempre tramite la Decisions API OpenRouter, con lo stesso contenuto di gioco, prompt di controllo e mosse di Luna. La [scheda OpenRouter](https://openrouter.ai/typesafe/jev-1.14) dichiara input testo e immagini; TypeSafe descrive la visione come sperimentale.

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

È disponibile anche il **controllo diretto dei pulsanti** (`--control-mode buttons`),
pensato per eliminare i rilasci fra mosse brevi durante l'attesa del modello.
Il modello sceglie una combinazione NES; l'harness la mantiene fino alla prossima
scelta. Non avvia salti, non frena, non cambia direzione e non reagisce agli
atterraggi autonomamente. Il controllo diretto è il default. Le mosse calibrate restano selezionabili con
`--control-mode moves` per riprodurre le prove precedenti. I due protocolli vanno confrontati separatamente.

Con `--control-mode timed --execution-mode paused` il modello sceglie pulsanti e durata con il gioco fermo. In questa modalità `decider` ha **completato il livello 1-1** in quattro episodi su quattro, senza frame eseguiti al di fuori delle sue scelte (vedere sotto).

La versione corrente usa pulsanti scelti dal modello, richiesta dopo il primo frame e log separati per decisioni e frame; le mosse interrompibili restano una modalità alternativa. Le [verifiche del 29 ottobre 2026](docs/harness-verification-2026-10-29.md) documentano test offline, emulatore reale e tredici prove live: la continuità e il timer sono migliorati, ma nessun modello ha ancora completato il livello.

Il primo livello dispone di tre controller: modello (predefinito), demo e tastiera. Il ciclo OpenRouter con screenshot, decisione e azione è implementato e verificato sia offline sia sul servizio reale. L'ambiente Python è gestito con **uv**.

La fase 4 introduce il gioco continuo a 60 FPS, il rilascio dei pulsanti durante le richieste, lo scarto delle osservazioni obsolete e misure per tentativo e sessione. Il controllo continuo è verificato con modello simulato e backend reale, anche con finestra; il precedente controllo live verifica il protocollo con pause.

Dall'8 ottobre 2026 il modello sceglie **mosse** complete (salto alto, doppio salto, corsa…) con una sola richiesta in corso, al posto dei pulsanti mantenuti e delle richieste sfalsate. Il ciclo è verificato offline e con emulatore reale. Nelle prime sessioni live a 60 FPS Mario ha raggiunto x≈1270–1410. Dalla stessa data il modello riceve anche una guida di gioco e una scena letta dalla RAM (nemici, muri, buche, blocchi, power-up); l'effetto sul provider deve ancora essere misurato.

Il 15 ottobre 2026 Jev 1.14, chiamato tramite OpenRouter, ha riconosciuto correttamente le immagini rossa e blu. Con il padding 280×280 richiesto dal provider, la prova a turni di 12 frame ha portato Mario da x=40 a x=47. Questa verifica conferma il protocollo multimodale e l'esecuzione delle mosse, senza dimostrare l'efficacia sul livello. Il primo tentativo realtime (`runs/20261015T081009-7094aec49acb/`) ha ricevuto 9 decisioni senza errori API, con latenza OpenRouter mediana di 296 ms (p95 596 ms), ed è terminato al primo Goomba, x=315, dopo 124 frame. FPS effettivi circa 38 con obiettivo 60: questa singola prova non permette un confronto prestazionale fra modelli.

Il 7 ottobre 2026 GPT Luna ha riconosciuto correttamente due immagini, rossa e blu, senza indicazioni testuali del colore. Il successivo tentativo live di 12 frame ha ricevuto ed eseguito due decisioni, facendo avanzare Mario da x=40 a x=44. Il formato multimodale `state` è quindi verificato su OpenRouter. Questa prova breve verifica il collegamento e non dimostra ancora il completamento del livello o l'efficacia del controllo in tempo reale.

## Installazione e avvio

Su Windows con Python 3.13 e uv, dalla cartella del progetto:

```powershell
uv sync --locked

# Impostare la chiave per la sessione PowerShell corrente
$env:OPENROUTER_API_KEY = 'la-tua-chiave-openrouter'

# Avvio con il modello configurato e finestra
uv run main.py
```

In alternativa, copiare `.env.example` in `.env` e compilare `OPENROUTER_API_KEY`. Il file `.env` viene letto dalla cartella del progetto; una variabile già presente nell'ambiente ha precedenza. La chiave non viene salvata nei risultati. Demo e tastiera non richiedono credenziali.

Il modello si sceglie con `OPENROUTER_MODEL`, nell'ambiente o nel file `.env`:

```dotenv
OPENROUTER_MODEL=typesafe/jev-1.14
```

Precedenza: `--model` > `OPENROUTER_MODEL` nell'ambiente > `.env` > GPT Luna.
Sono accettati gli alias `gpt_luna`, `jev`, `decider` e `d1` oppure i rispettivi identificativi OpenRouter
(`openai/gpt-6-luna-decisions`, `typesafe/jev-1.14`, `perplexity/pplx-decider-v1.2`, `liquid/d1.1`),
elencati anche come commento in `.env.example`.
Un identificativo sconosciuto viene rifiutato prima di aprire il gioco. `.env.example` propone Jev;
senza una scelta resta il fallback GPT Luna. Le istanze `Config()` create direttamente in Python
mantengono i default statici; usare `parse_config` per leggere ambiente e `.env`.

Il comando predefinito apre il livello **1-1** in modalità continua. Il ciclo è **decisione → un frame eseguito → nuova osservazione → richiesta successiva**. Durante la richiesta restano premuti gli ultimi pulsanti scelti dal modello, con una sola richiesta in corso. La nuova scelta sostituisce i pulsanti al primo tick utile. Con `--control-mode moves`, invece, vengono eseguite sequenze interrompibili che rilasciano i pulsanti al termine. Prima della prima decisione il gioco avanza con `noop`. Morte, completamento e limiti terminano il tentativo; `--episodes` avvia tentativi indipendenti.

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

# A turni: gioco fermo durante le richieste, un frame per scelta di pulsanti
uv run main.py --execution-mode paused --save-screenshots

# A turni, pulsanti e durata scelti dal modello (ha completato 1-1)
uv run main.py --model decider --execution-mode paused --control-mode timed

# Solo la scena dalla RAM, senza screenshot: richieste più leggere
uv run main.py --no-image

# Modificare limite dell'episodio e seed
uv run main.py --max-frames 1800 --seed 123

# Provare Jev tramite OpenRouter
uv run main.py --model jev

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

Le impostazioni predefinite sono: modalità `model`, esecuzione `realtime`, modello `openai/gpt-6-luna-decisions` se `OPENROUTER_MODEL` non è configurato, timeout `10` secondi, seed `123`, `1` episodio, limite di `3600` frame e `60` secondi reali per episodio, età massima dell'osservazione `120` frame di gioco, scena dalla RAM attiva, gioco a `60` FPS e screenshot su disco disattivati. `--episodes` riguarda modello e demo; la tastiera aggiorna il comando a ogni frame. La demo esegue una sequenza fissa di mosse con lo stesso esecutore del modello. Le nuove opzioni di esecuzione e registrazione riguardano il modello; soglia di età e limite reale si applicano solo a `realtime`. `--mode manual --headless` viene rifiutato. La demo verifica il controllo, non è una strategia per completare il livello.

La finestra mostra modalità, mossa corrente con la fonte dei pulsanti (`move`, `release` o `waiting`), frame, posizione, attesa, latenza dell'ultima richiesta, numero di mosse iniziate e risposte obsolete. L'indicazione dell'ultima risposta scartata, con età e soglia, rimane visibile durante l'attesa successiva fino all'arrivo di una nuova decisione. Dopo tre risposte obsolete consecutive il terminale stampa un avviso una sola volta per episodio; il conteggio consecutivo riparte con la prima decisione applicata. Il modello in `realtime` avanza a un massimo di 60 FPS anche senza finestra, senza recuperare ritardi in accelerazione. In `paused` il gioco si ferma durante le richieste; le mosse senza finestra procedono alla velocità disponibile. La tastiera conserva il comportamento precedente. Si contano i frame restituiti da `step`: il backend può saltare internamente transizioni e schermate di caricamento. La modalità con pause è identificata come debug nei risultati.

### Protocollo Decisions e risultati

#### Controllo diretto, indipendente dal modello

```powershell
# Controllo continuo: decide il modello ogni cambio dei pulsanti
uv run main.py --control-mode buttons

# Stesso harness con un altro adapter
uv run main.py --control-mode buttons --model gpt_luna
uv run main.py --control-mode buttons --model jev
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
`app/models/_choice.py`; Luna specifica l'identificativo, Jev aggiunge il proprio
padding. Un nuovo adapter Choice può estendere `ChoiceModel`; un protocollo diverso
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

#### Pulsanti con durata scelta dal modello (`--control-mode timed`)

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
[verifiche](docs/harness-verification-2026-10-29.md#protocollo-timed-a-turni).

#### Benchmark

Il [benchmark del 29 ottobre 2026](docs/benchmark-2026-10-29.md) confronta decider,
Jev, d1 e Luna. A turni solo decider completa 1-1. A 60 FPS nessun modello vince
in 120 partite (10 per modello e configurazione). `--no-image` invia solo la scena
dalla RAM: riduce la latenza di 8–128 ms, ma non porta vittorie. `--no-image`
richiede la scena; con `--no-scene` viene rifiutato.

#### Protocollo a mosse calibrate (`--control-mode moves`)

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

**Immagini Jev.** Il provider richiede almeno 256 px per lato e 78.400 pixel totali ([limiti TypeSafe](https://docs.typesafe.ai/images#limits)). L'adapter aggiunge 24 colonne nere a destra e 40 righe sotto, ottenendo 280×280 senza cambiare i pixel originali o le coordinate. Il prompt spiega di ignorare il bordo. La trasformazione compare nel trace `image_preprocessing`; gli screenshot salvati restano gli originali 256×240. Nei confronti considerare la diversa presentazione e il tempo di preparazione, incluso nelle misure.

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

### Note sperimentali storiche

Le note seguenti descrivono revisioni precedenti, inclusi latch, code e prosecuzione automatica; non il controllo della versione 6.

**Blocco dei salti (12 ottobre 2026).** Nella sessione `runs/20261012T160437-dae398ee4635/` (morte a x=2466) 29 mosse su 37 erano salti, 28 mosse sono state differite (20 `airborne`, 8 `committed`) e Mario era in aria in 993 frame su 1197. L'età dell'osservazione all'avvio della mossa aveva mediana 0,50 s e p95 1,04 s, contro una latenza mediana di 0,28 s. La morte: durante un salto alto il modello ha scelto `wait`, partito alla fine dei 28 frame committed; Mario è atterrato senza pulsanti al frame 1158 ed è scivolato nella buca al frame 1164. Il `high_jump_right` successivo è arrivato al frame 1165, a caduta iniziata, e non è mai partito. Il modello non sapeva quando sarebbe atterrato. Da qui il latch di A, `move.landing` e i contatori del blocco. Nel replay, al frame 1135 `move.landing` avrebbe indicato 34 frame e 102 px, cioè un atterraggio dentro la buca (dx 88, larga 32). Mario è atterrato prima, al frame 1158, su un gradino più alto: la stima vale per l'altezza di partenza.

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

### Registrazione e misure attuali

Gli errori temporanei del provider (HTTP 5xx, timeout, errori di connessione) ottengono **un solo** nuovo tentativo: l'evento `request_failed` lo registra, `retried_requests` lo conta e parte una nuova richiesta dopo il successivo frame, mentre la mossa in corso prosegue. Un secondo errore consecutivo arresta la sessione con codice `1`; errori 4xx (incluso 429), rifiuti e risposte invalide la arrestano subito. Il timeout comprende l'intera richiesta HTTP. Fine episodio, Esc, chiusura finestra e Ctrl+C annullano la richiesta in corso; una risposta già completata viene registrata e scartata. Nessuna risposta attraversa il reset. R serve soltanto in modalità manuale.

Ogni sessione modello crea una cartella distinta sotto `runs/`, esclusa da Git, con:

- `config.json`: configurazione (compresi `scene`, `control_mode` e `max_decision_frames`), protocollo `choice-buttons-v1` e `prompt_revision: 12` per il controllo diretto, oppure `openrouter-choice-scene-v5` e revisione 5 per le mosse; versione risultati `6`, modalità, FPS e catalogo, senza credenziali.
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

Per verificare il provider reale, impostare la chiave e attivare esplicitamente i test live. Usano il modello selezionato da `OPENROUTER_MODEL` (ambiente o `.env`, altrimenti Luna). Questi inviano prima due immagini di colore diverso per controllare che i pixel vengano interpretati, poi eseguono un tentativo di gioco di 12 frame. Consumano credito OpenRouter e salvano la sessione di gioco in `runs/`.

```powershell
$env:SUPERMAIRIO_TEST_OPENROUTER = '1'
uv run python -m unittest discover -s tests -p test_openrouter_live.py -v
Remove-Item Env:SUPERMAIRIO_TEST_OPENROUTER
```

Se il controllo dei colori fallisce, il test non avvia la sessione di gioco. La verifica live ha superato tutti i controlli con Luna il 7 ottobre 2026 e con Jev 1.14 il 15 ottobre 2026; può essere ripetuta per verificare cambiamenti del provider o del modello.
