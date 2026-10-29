# Verifica harness — 29 ottobre 2026

Il controllo diretto è ora il default (`--control-mode buttons`). Ogni cambio
dei pulsanti proviene da una decisione del modello. Il codice non aggiunge salti,
frenate, rilasci di A o reazioni all'atterraggio. `--control-mode moves` conserva
le sequenze calibrate precedenti. Luna e Jev condividono `ChoiceModel`, senza
dipendere l'uno dall'altro; il runner fornisce le scelte ammesse a ogni adapter.

## Verifiche deterministiche

- Con identiche risposte simulate distanti 600 ms, il protocollo a mosse produce
  oltre 20 frame di attesa dopo la prima scelta; il controllo diretto ne produce zero.
- Ripetere un comando con A non crea un rilascio; il contatore della pressione
  resta continuo. Solo una scelta senza A lo rilascia.
- Atterraggi e retry non modificano i pulsanti. Un reset elimina lo stato e
  cancella la richiesta del tentativo precedente.
- A turni ogni scelta esegue un frame; realtime avanza durante la richiesta.
- L'emulatore reale con un modello simulato mantiene il comando oltre i 16 frame
  delle vecchie mosse e avanza senza attendere la risposta successiva.
- Scelte non offerte, risposte obsolete, errori e chiusura conservano i controlli
  e la registrazione degli esiti parziali.

## Temporizzazione Windows

Una misura locale di attese richieste da 12 ms ha dato mediane di 15,261 ms per
`Event.wait` e 12,565 ms per `sleep`. Nel ciclo completo la vecchia attesa produceva
intervalli mediani fra frame di circa 30,7 ms con obiettivo 16,7 ms.

Il worker usa ora, su Windows, sospensioni di massimo 2 ms fino alla scadenza o
alla notifica della risposta. Non esegue attesa attiva e non modifica il timer
di sistema. La prova live a 60 FPS successiva ha registrato 17,2 ms mediani e
57,3 FPS effettivi. La preparazione delle richieste e il resto del lavoro locale
restano inclusi nei tempi: non si garantiscono 60 FPS su ogni macchina.

## Prove live autorizzate

Tutte headless, seed 123, scena RAM e screenshot attivi. Una sessione per riga;
nessuna ha completato il livello. Le latenze includono rete e servizio OpenRouter,
non rappresentano il solo tempo di inferenza. Le righe differiscono per protocollo,
prompt e velocità: non sono un confronto statistico della qualità dei modelli.

| Sessione in `runs/` | Modello | Controllo / prompt | FPS richiesti → effettivi | x massimo | Decisioni | Latenza mediana ms | Frame di attesa dopo la prima scelta |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| `20261029T101703-730dbd9ff449` | Luna | buttons / 6 | 60 → 33,4 | 688 | 24 | 494 | 0 |
| `20261029T101818-9f68a76dece1` | Luna | moves / 5 | 60 → 34,2 | 865 | 53 | 374 | 160 |
| `20261029T101918-097063a939d9` | Jev | buttons / 6 | 60 → 35,0 | 898 | 82 | 215 | 0 |
| `20261029T102206-6db803c9c79a` | Luna | buttons / 6 | 60 → 57,3 | 312 | 3 | 634 | 0 |
| `20261029T102316-7440d43a9974` | Luna | buttons / 6 | 30 → 29,3 | 1126 | 83 | 338 | 0 |
| `20261029T102441-7fe08d89c8a9` | Jev | buttons / 7 | 30 → 28,2 | 1138 | 137 | 223 | 0 |
| `20261029T102630-e5536293f8a8` | Luna | buttons / 7 | 15 → 14,8 | 853 | 92 | 422 | 0 |
| `20261029T102909-2ca40d40ce8a` | Luna | buttons / 8 | 30 → 29,2 | 315 | 3 | 494 | 0 |
| `20261029T102944-e23c2b4fb548` | Jev | buttons / 8 | 30 → 29,5 | 296 | 20 | 240 | 0 |
| `20261029T103125-eeb75f410d8a` | Luna | buttons / 8 | 10 → 9,9 | 306 | 62 | 331 | 0 |
| `20261029T113934-080c37aa12af` | Jev | buttons / 9 | 30 → 28,0 | 312 | 13 | 235 | 0 |
| `20261029T114053-df6258602b0a` | Jev | buttons / 9 | 15 → 14,4 | 706 | 105 | 212 | 0 |
| `20261029T114353-bea2f59f4459` | Jev | buttons / 10 | 15 → 14,8 | 286 | 42 | 212 | 0 |

La correzione del timer è presente dalla quarta riga. Il prompt 7 aggiunge lo stato
dei pulsanti e i frame consecutivi di pressione. Il prompt 8 esplicita nelle
opzioni l'effetto dei comandi, i pulsanti NES e il requisito di rilascio di A.
Non è stato dimostrato che queste revisioni migliorino l'efficacia dei modelli.

Il prompt 9 abbrevia le istruzioni e distingue esplicitamente la scelta della
prossima azione dalla descrizione del movimento corrente; omette lo storico
`recent_moves`, mantenendo il contesto dei pulsanti realmente premuti. Il prompt
10 aggiunge `dx_at_response` anche ai blocchi, già disponibile per altri oggetti.

Un confronto diagnostico sulla richiesta 135 della sessione
`20261029T102441-7fe08d89c8a9` ha mantenuto la stessa scena davanti alla prima buca.
Luna ha scelto `right_run_jump` con il prompt originale, con quello breve e con
quello breve senza immagine. Jev ha scelto `right` con l'originale, `right_jump`
nelle due varianti brevi. Sono sei decisioni su una sola scena, non una misura
della probabilità di completare il livello. I tre tentativi successivi sono
riportati sopra e non hanno ottenuto una vittoria.

Il costo noto cumulativo dei tredici episodi è **0,070353610** (campo `known_cost`),
più **0,000495168** per le sei decisioni diagnostiche sulla scena salvata.
Le tredici richieste cancellate alla fine degli episodi possono avere un costo non
riportato: questa cifra non è il costo totale certo. Un tentativo preliminare
senza accesso di rete (`20261029T101210-e1868f7680e6`) non ha ricevuto decisioni
ed è escluso dalla tabella.

## Limite aperto

I rilasci introdotti dall'harness sono eliminati e la temporizzazione è migliorata.
La vittoria del modello non è ancora ottenuta. Nei log compaiono scelte che
mantengono il movimento verso un pericolo e richieste con ritardi variabili.
Anche rallentare il gioco non ha garantito un esito positivo. Il codice non
compensa questi errori scegliendo al posto del modello.

## Protocollo timed a turni

Diagnosi del ritardo: in realtime lo screenshot ha mediana 17,5 frame (p95 30)
all'avvio della scelta (`20261029T163436-a767de7d098d`, Luna a 60 FPS). La
preparazione della richiesta richiede 3,8 ms in mediana e il polling 8,4 ms;
il resto è latenza OpenRouter. L'immagine corrisponde al frame della richiesta,
ma la scelta agisce su una scena successiva.

A turni con un frame per scelta (`20261029T165434-51c6aebfd852`, decider) Mario
ha superato il primo Goomba. Davanti al tubo a x≈594, però, il modello teneva A
per 1–8 frame e faceva solo saltelli: 500 frame, x=834. `--control-mode timed`
fa scegliere al modello anche la durata. Le revisioni successive, provate dal vivo:

- una sola domanda con 50 opzioni: probabilità disperse fra le durate e durate
  massime scelte senza poter reagire (morti a x≈684);
- guida di gioco e `contact_in_frames` nel contesto: x=2473;
- due domande indipendenti: la durata non conosceva i pulsanti e Luna combinava
  il salto con 2–4 frame, bloccandosi al tubo;
- due domande in sequenza, con i pulsanti scelti nello stato, altezze dei salti
  misurate per durata, durate senza A limitate a 2/4/8 frame e avviso `Ceiling`.

| Sessione in `runs/` | Modello | Episodi | Esito | Frame | Decisioni | Costo noto $ |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| `20261029T174114-fc4cdb1bca6a` | decider | 1 | completato, x=3161 | 1382 | 169 | 0,0123 |
| `20261029T174438-ad54abd24e6a` | decider | 3 | 3 completati, identici | 1382 ciascuno | 507 | 0,0368 |
| `20261029T174111-e4a461b64f9a` | Luna | 1 | morte, x=1435 | 725 | 199 | 0,0678 |

Nella sessione vincente i 1382 frame provengono tutti da scelte del modello
(`source: move`, nessun frame `waiting`), senza errori né nuovi tentativi.
La latenza mediana delle due chiamate è di 0,68 s (p95 1,06 s), irrilevante a turni.
Rigiocando nell'emulatore i pulsanti registrati si riottiene `flag_get` a x=3161.
La GIF locale è in `.local/verification/mario-vince-1-1.gif`.

Limiti: la vittoria è a turni, non in tempo reale. Modello ed emulatore sono
deterministici, quindi i quattro episodi uguali dimostrano la riproducibilità,
non una frequenza di successo su scene diverse. In 1-1 il prompt `timed` è stato
corretto osservando le morti; alcuni avvisi (scalinate, blocco sopra il salto)
descrivono situazioni di questo livello. Il contesto non indica mai una mossa.
Con Luna il provider ha risposto HTTP 502 in modo deterministico quando la
seconda domanda conteneva "noop (no buttons)" nelle istruzioni: la scelta viaggia
ora in `state.chosen_buttons`. Due sessioni Luna bloccate a un tubo
(`20261029T171043-ff26ccab4b9a` e `20261029T172136-36cbae67f2b2`, la seconda
interrotta) sono costate 0,33 e 0,12 $. Il costo noto delle prove di questa
sezione è di circa 0,78 $, più alcune richieste diagnostiche isolate.
