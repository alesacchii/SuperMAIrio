# Comandi e opzioni

## Avvio

Servono [uv](https://docs.astral.sh/uv/getting-started/installation/) e, per far
giocare un modello, una [chiave OpenRouter](https://openrouter.ai/keys). Dalla
cartella del progetto:

```powershell
# Una volta sola: copiare il modello e inserire la chiave in OPENROUTER_API_KEY
copy .env.example .env

uv run main.py
```

Il comando apre il livello **1-1** con la configurazione che ha dato i risultati
migliori: `decider`, modalità predittiva, anteprime di 30 frame, due copie di ogni
richiesta, senza screenshot. Equivale a:

```powershell
uv run main.py --model decider --execution-mode predictive --control-mode buttons --choice-preview 30 --parallel-requests 2 --no-image
```

In alternativa a `.env`, la chiave si può impostare per la sessione corrente:

```powershell
$env:OPENROUTER_API_KEY = 'la-tua-chiave-openrouter'
```

Il file `.env` viene letto dalla cartella del progetto; una variabile già presente
nell'ambiente ha precedenza. La chiave non viene salvata nei risultati. Demo e
tastiera non richiedono credenziali.

Morte, completamento e limiti terminano il tentativo; `--episodes` avvia tentativi
indipendenti.

## Scegliere il modello

Il modello si sceglie con `--model` oppure con `OPENROUTER_MODEL`, nell'ambiente o
nel file `.env`:

```dotenv
OPENROUTER_MODEL=typesafe/jev-1.14
```

Precedenza: `--model` > `OPENROUTER_MODEL` nell'ambiente > `.env` > `decider`.
Sono accettati gli alias `decider`, `d1`, `gpt_luna` e `jev` oppure i rispettivi
identificativi OpenRouter (`perplexity/pplx-decider-v1.2`, `liquid/d1.1`,
`openai/gpt-6-luna-decisions`, `typesafe/jev-1.14`), elencati anche in
`.env.example`. Un identificativo sconosciuto viene rifiutato prima di aprire il
gioco. Le istanze `Config()` create direttamente in Python mantengono i default
statici (`realtime`, screenshot attivi, nessuna anteprima); la configurazione
migliore si applica con `parse_config`, cioè dalla riga di comando.

## Esempi

```powershell
# Giocare da tastiera
uv run main.py --mode manual

# Avviare la demo deterministica
uv run main.py --mode demo

# Due tentativi della demo, senza finestra
uv run main.py --mode demo --headless --episodes 2

# Benchmark: 10 partite senza finestra
uv run main.py --episodes 10 --headless

# Un altro modello, con le stesse condizioni
uv run main.py --model jev
uv run main.py --model gpt_luna --request-timeout 10
uv run main.py --model openai/gpt-6-luna-decisions --request-timeout 10

# Conservare gli screenshot per ricostruire richieste e scelte
uv run main.py --save-screenshots

# Solo screenshot, senza la scena letta dalla RAM (confronto della percezione)
uv run main.py --no-scene

# Tempo reale senza previsione: budget reale e soglia di età delle osservazioni
uv run main.py --execution-mode realtime --headless --max-episode-seconds 60 --max-decision-frames 120

# Gioco rallentato a 30 FPS per compensare la latenza del modello
uv run main.py --execution-mode realtime --game-fps 30

# A turni: gioco fermo durante le richieste, un frame per scelta di pulsanti
uv run main.py --execution-mode paused --save-screenshots

# A turni, pulsanti e durata scelti dal modello
uv run main.py --execution-mode paused --control-mode timed

# Modificare limite dell'episodio e seed
uv run main.py --max-frames 1800 --seed 123

# Tutte le opzioni
uv run main.py --help
```

Se l'accesso alla cache uv predefinita è limitato, usare `uv --cache-dir .uv-cache`
al posto di `uv`.

## Tastiera

| Tasto | Comando |
| --- | --- |
| Frecce sinistra/destra | Movimento |
| Spazio | Salto, pulsante NES A |
| Shift sinistro/destro | Corsa, pulsante NES B, con una direzione |
| R | Reset del tentativo, anche dopo la fine |
| Esc o chiusura finestra | Arresto |
| Ctrl+C nel terminale | Arresto con codice di uscita 130 |

Le combinazioni sono consentite. Premere entrambe le direzioni annulla il movimento
direzionale; il salto resta disponibile. Il rilascio dei tasti e la perdita del
focus cancellano i pulsanti corrispondenti. Dopo la fine di un tentativo manuale il
gioco attende R, senza avanzare.

## Finestra e terminale

In modalità predittiva il titolo della finestra mostra episodio, pulsanti in corso,
numero di scelte, frame fra due scelte, frame e posizione. Il terminale riporta
l'esito e il costo noto di ogni episodio e, alla fine, il totale della sessione.

Con `--execution-mode realtime` o `paused` la finestra mostra modalità, mossa
corrente con la fonte dei pulsanti (`move`, `release` o `waiting`), frame, posizione,
attesa, latenza dell'ultima richiesta, numero di mosse iniziate e risposte obsolete.
L'indicazione dell'ultima risposta scartata, con età e soglia, rimane visibile
durante l'attesa successiva fino all'arrivo di una nuova decisione. Dopo tre
risposte obsolete consecutive il terminale stampa un avviso una sola volta per
episodio; il conteggio consecutivo riparte con la prima decisione applicata.

Il modello in `realtime` e `predictive` avanza a un massimo di 60 FPS anche senza
finestra, senza recuperare ritardi in accelerazione. In `paused` il gioco si ferma
durante le richieste; le mosse senza finestra procedono alla velocità disponibile.
Si contano i frame restituiti da `step`: il backend può saltare internamente
transizioni e schermate di caricamento. La modalità con pause è identificata come
debug nei risultati.

## Opzioni

`uv run main.py --help` elenca le stesse opzioni. Le opzioni incompatibili con la
modalità scelta vengono rifiutate prima di aprire il gioco.

**Generali**

| Opzione | Default | Effetto |
| --- | --- | --- |
| `--mode {model,demo,manual}` | `model` | `model`: gioca il modello. `demo`: una sequenza fissa di mosse che verifica i comandi (non è una strategia per vincere). `manual`: tastiera, richiede la finestra |
| `--headless` | finestra visibile | Nessuna finestra (modello e demo). In `realtime` e `predictive` il gioco mantiene comunque la velocità configurata; a turni procede alla velocità disponibile |
| `--episodes N` | `1` | Numero di tentativi indipendenti (modello e demo) |
| `--seed N` | `123` | Seed del reset dell'ambiente |
| `--max-frames N` | `3600` | Frame massimi per tentativo (a 60 FPS, un minuto di gioco) |
| `--max-episode-seconds S` | `60` | Secondi reali massimi per tentativo (`realtime` e `predictive`) |
| `--save-screenshots` | no | Salva in `runs/<sessione>/screenshots/` le immagini inviate al modello; in `predictive` attiva anche `--image` |

**Modello e richieste**

| Opzione | Default | Effetto |
| --- | --- | --- |
| `--model NOME` | `OPENROUTER_MODEL` oppure `decider` | Alias (`decider`, `d1`, `gpt_luna`, `jev`) o identificativo OpenRouter |
| `--request-timeout S` | `10` | Tempo massimo per una richiesta intera (connessione, invio e risposta, anche con due domande in sequenza) |
| `--execution-mode {realtime,paused,predictive}` | `predictive` (`realtime` con `--control-mode timed` o `moves`) | Vedi [Quando sceglie](come-funziona.md#quando-sceglie-le-modalità-di-esecuzione---execution-mode) |
| `--control-mode {buttons,timed,moves}` | `buttons` | Vedi [Che cosa può scegliere](come-funziona.md#che-cosa-può-scegliere-i-protocolli-di-controllo---control-mode). `predictive` richiede `buttons` e usa il proprio catalogo |
| `--game-fps N` | `60` | Velocità del gioco (`realtime` e `predictive`), massimo 60. Valori bassi lasciano più tempo al modello ma non sono "velocità normale" |

**Che cosa vede il modello**

| Opzione | Default | Effetto |
| --- | --- | --- |
| `--scene` / `--no-scene` | attiva | Invia lo stato letto dalla RAM. Senza, il modello deve ricavare tutto dallo screenshot, che viene quindi attivato anche in `predictive` |
| `--image` / `--no-image` | spenta in `predictive`, attiva altrimenti | Invia lo screenshot; in `predictive` si attiva da sola con `--no-scene` o `--save-screenshots`. Senza, resta solo lo stato: richieste più leggere e latenza più bassa. Non si può togliere anche la scena |

**Solo `realtime`**

| Opzione | Default | Effetto |
| --- | --- | --- |
| `--max-decision-frames N` | `120` | Una risposta arrivata quando il gioco è avanzato di più di N frame dallo screenshot viene scartata come obsoleta |

**Solo `predictive`**

| Opzione | Default | Effetto |
| --- | --- | --- |
| `--choice-preview N` | `30` | Per ogni opzione emula l'esito tenendola per almeno N frame (comunque per tutta la durata prevista della scelta più 10, e finché Mario è in aria o sopra una buca) e lo scrive nella sua descrizione. Usa un emulatore per opzione in parallelo. `0` spegne le anteprime |
| `--parallel-requests N` | `2` | Invia N copie identiche di ogni richiesta e usa la prima risposta: elimina gli stalli occasionali del provider e accorcia la latenza nei casi peggiori. Il costo si moltiplica per N |
| `--decision-frames N` | `0` (minimo 8) | Durata minima di una scelta in frame. La durata reale si allunga quando la latenza misurata lo richiede |
| `--speculative-width N` | `0` | Sperimentale. Mentre la risposta è in volo, invia una richiesta anticipata per ciascuna delle N risposte più frequenti, con il proprio stato previsto; alla risposta tiene quella giusta. Scelte ogni 8–18 frame, ma costo N volte maggiore e poco utile insieme alle anteprime |

La modalità predittiva usa intensamente la CPU locale: all'avvio misura la velocità
di emulazione e avvisa se è sotto 2000 frame/s.
