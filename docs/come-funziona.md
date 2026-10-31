# Come funziona

Che cosa riceve il modello, che cosa può scegliere e quando la scelta ha effetto.
Le specifiche di ogni protocollo sono in [protocolli.md](protocolli.md).

## Modelli e accesso tramite OpenRouter

Il progetto usa modelli della categoria System One Model attraverso **OpenRouter**,
con la [Decisions API](https://openrouter.ai/api/alpha/decisions): una domanda
`Choice` con le opzioni ammesse, a cui il modello risponde con una sola scelta
(più, se il provider le fornisce, confidenza e probabilità), senza spiegazioni.

| Alias | Identificativo OpenRouter | Note |
| --- | --- | --- |
| `decider` (default) | [`perplexity/pplx-decider-v1.2`](https://openrouter.ai/perplexity/pplx-decider-v1.2/) | Il più affidabile nelle prove |
| `d1` | [`liquid/d1.1`](https://openrouter.ai/liquid/d1.1) | Rilasciato il 27 ottobre 2026 |
| `gpt_luna` | [`openai/gpt-6-luna-decisions`](https://openrouter.ai/openai/gpt-6-luna-decisions) | Primo modello configurato; latenza mediana ~0,4 s |
| `jev` | [`typesafe/jev-1.14`](https://openrouter.ai/typesafe/jev-1.14) | Il più rapido (~0,21 s); richiede immagini di almeno 280×280 |

Tutti usano lo stesso adapter `ChoiceModel` (`app/models/_choice.py`) e ricevono
**esattamente lo stesso contesto**: stesse istruzioni, stesso stato, stesse opzioni
con le stesse descrizioni e la stessa immagine. Nella richiesta cambia solo
l'identificativo del modello. Il modello si può cambiare mantenendo identiche
le condizioni sperimentali.

## Il ciclo

1. Il programma legge lo stato del gioco (screenshot e RAM della NES).
2. Costruisce una richiesta: istruzioni, stato, eventuale screenshot e l'elenco
   delle opzioni ammesse, ciascuna con la sua descrizione.
3. Il modello risponde con **una** delle opzioni.
4. Il programma controlla che l'opzione fosse fra quelle offerte (altrimenti
   arresta la sessione) e la traduce nei pulsanti NES A, B, sinistra, destra.
5. Il gioco avanza; si ripete dal punto 1.

Il modello non vede la propria storia di conversazione: ogni richiesta è
indipendente e contiene tutto ciò che serve a decidere.

## Che cosa riceve il modello

**Istruzioni.** Un testo fisso per ciascuna modalità: obiettivo (raggiungere la
bandiera; priorità: sopravvivere, avanzare, prendere il fungo), come funzionano i
comandi (quando A avvia un salto, quanto tenere A per un salto basso o alto,
B per correre), quando la scelta avrà effetto e per quanto resterà attiva,
legenda delle coordinate e una guida di gioco (Goomba, Koopa e gusci, buche,
tubi, scalinate, blocchi ?, funghi, inerzia di Mario, limite di visuale).
Non indica mai quale opzione scegliere.

**Stato** (JSON compatto, letto dalla RAM; con `--no-scene` resta solo taglia,
contatto con il terreno e x di Mario):

| Campo | Contenuto |
| --- | --- |
| `mario` | taglia, `on_ground`, `vertical` (sale/scende), `speed` in px/frame, posizione nello schermo; a terra `jump_reach_px`, la portata misurata di un salto basso e alto alla velocità attuale |
| `progress` | `x`, posizione della bandiera e percentuale del livello |
| `nearby.enemies` | tipo, `dx`/`dy` rispetto a Mario, direzione e velocità; con alcuni protocolli `contact_in_frames` (frame prima del contatto a velocità costanti) o `dx_at_response` (distanza stimata quando arriverà la risposta) |
| `nearby.obstacle_ahead` | primo muro davanti (tubo, gradino, blocco) e la sua altezza in tile |
| `nearby.pit_ahead` | prima buca sotto o davanti a Mario: distanza, larghezza visibile, bordi visibili |
| `nearby.blocks`, `items`, `surfaces` | blocchi ? e mattoni raggiungibili, power-up, superfici solide visibili su cui si può atterrare |
| `move` | input in corso, da quanti frame, quando finisce e cosa succede dopo; in predittiva `hold_frames`, per quanti frame la scelta resterà attiva |
| `input` | pulsanti effettivamente premuti e da quanti frame |
| `jump_observation` | in aria: velocità e durata della pressione di A del salto in corso |
| `warnings` | solo se servono: nemico vicino, blocco sopra un salto che partirebbe ora, nessun avanzamento da N frame, tempo quasi scaduto |

Le distanze sono in pixel (16 px = un tile): `dx` è il bordo sinistro dell'oggetto
meno quello di Mario, `dy` l'altezza del fondo dell'oggetto sopra i piedi di Mario.
Lo stato riporta solo ciò che è visibile sullo schermo (niente blocchi nascosti).

**Screenshot** (nella configurazione predefinita non viene inviato; si attiva con
`--image`, ed è attivo in `realtime` e `paused`): l'immagine 256×240 del gioco con un bordo
nero fino a 280×280, il minimo richiesto da Jev, applicato a tutti i modelli.

**Opzioni**: nomi e descrizioni delle scelte ammesse in quel momento. In
modalità predittiva con `--choice-preview` ogni descrizione termina con
l'esito emulato di quell'opzione, per esempio
`Preview: Mario dies after 21 frames.` oppure
`Preview: alive after 43 frames, 90 px right, on the ground.`

## Che cosa può scegliere: i protocolli di controllo (`--control-mode`)

| Protocollo | Opzioni | Cosa succede dopo la scelta |
| --- | --- | --- |
| `buttons` (default) | 10 combinazioni NES: `noop`, `jump`, `left`, `left_jump`, `left_run`, `left_run_jump`, `right`, `right_jump`, `right_run`, `right_run_jump` | I pulsanti restano premuti esattamente così fino alla scelta successiva. Ripetere la stessa scelta non rilascia A: per un nuovo salto serve prima una scelta senza A. |
| `timed` | Pulsanti **e durata**: con A 2, 4, 8, 16 o 28 frame (l'altezza del salto), senza A 2, 4 o 8 frame, per esempio `right_run_jump_28` | I pulsanti restano premuti per quei frame, poi vengono rilasciati se non è arrivata una nuova scelta. A turni il modello sceglie con due domande in sequenza (prima i pulsanti, poi la durata); a velocità reale con una sola domanda. |
| `moves` | Mosse calibrate: `wait`, `walk_right`, `run_right`, `short_jump_right`, `high_jump_right`, `double_jump_right`, `high_jump_up` e le versioni a sinistra, più `continue` | Ogni mossa è una sequenza interrompibile (per esempio A per 28 frame, poi destra+B fino all'atterraggio); a fine sequenza tutti i pulsanti vengono rilasciati. |
| predittiva | 10 scelte (`PREDICTIVE_MOVES`): `noop`, `left`, `left_run`, `right`, `right_run`, `right_jump`, `right_run_jump`, `right_hop`, `right_run_hop`, `right_run_then_jump` | Usata automaticamente con `--execution-mode predictive`. Ogni scelta resta attiva fino alla successiva. `*_hop` è un salto corto: A per 8 frame, poi tutti i pulsanti rilasciati. `right_run_then_jump` è un salto con rincorsa: destra+B per 4 frame, poi destra+B+A. Un input con A scelto a terra mentre A è già premuto inizia con un frame senza A, così il salto parte; in aria A resta premuto. |

## Quando sceglie: le modalità di esecuzione (`--execution-mode`)

| Modalità | Il gioco durante la richiesta | Lo stato inviato descrive | Quando si applica la scelta |
| --- | --- | --- | --- |
| `realtime` | Continua a `--game-fps`, con i pulsanti dell'ultima scelta | Il frame in cui è partita la richiesta: quando la risposta arriva è già vecchio di 13–26 frame | Al primo frame dopo l'arrivo; una sola richiesta alla volta, la successiva parte dopo un frame |
| `paused` | Fermo | Esattamente l'istante in cui la scelta partirà | Subito; in `buttons` ogni scelta esegue un solo frame, in `timed` e `moves` la durata o la sequenza scelta. È un modo a turni, per misurare la qualità delle scelte senza latenza |
| `predictive` (default) | Continua a `--game-fps` e **non si ferma mai** | L'istante futuro in cui la scelta avrà effetto, calcolato da un emulatore ombra che rigioca gli input già scelti | Esattamente nel frame mostrato al modello; se la risposta arriva in ritardo, appena arriva (e le previsioni successive vengono rifatte dallo stato reale) |

In `predictive` la distanza fra due scelte (`hold_frames`, di solito 36–60 frame)
è calcolata dalla latenza misurata del modello e dal tempo di preparazione delle
richieste, così che la risposta arrivi prima del frame previsto. Dettagli nella
sezione [Modalità predittiva](protocolli.md#modalità-predittiva---execution-mode-predictive).

## Che cosa il programma non fa mai

Ogni input deriva da una scelta del modello. Il programma non salta, non frena,
non cambia direzione, non rilascia pulsanti e non reagisce ad atterraggi o
pericoli di sua iniziativa. Le uniche sequenze fisse sono quelle **dentro**
un'opzione scelta dal modello e dichiarate nella sua descrizione: le mosse di
`moves`, la durata di `timed`, i salti corti e con rincorsa e il frame senza A
che rende possibile un nuovo salto nel catalogo predittivo. Prima della prima
scelta di un episodio Mario resta fermo. Anteprime, avvisi e distanze sono
informazioni: non scartano opzioni e non indicano quale scegliere.
