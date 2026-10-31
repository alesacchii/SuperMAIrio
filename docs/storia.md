# Storia del progetto

Domanda di ricerca, cronologia e note sperimentali. Queste pagine raccontano come
si è arrivati al risultato: alcune sezioni descrivono piani iniziali o revisioni
superate e citano sessioni in `runs/`, una cartella locale non versionata. Il
comportamento attuale è in [come-funziona.md](come-funziona.md).

## Obiettivo

Il progetto vuole studiare quanto velocemente questi modelli riescano a prendere decisioni utili in una situazione dinamica. Super Mario rende osservabili le conseguenze di ogni scelta: avanzare, saltare o aspettare può permettere di superare un ostacolo oppure causare la perdita di una vita.

L'obiettivo è misurare sia la qualità delle decisioni sia la loro frequenza nel tempo. Vogliamo capire se la rapidità di questa categoria di modelli consente di effettuare molte decisioni in un breve intervallo e se questo vantaggio si traduce in un controllo efficace del gioco.

Il risultato atteso è una dimostrazione accompagnata da misure sperimentali: Mario controllato dal modello e dati che mostrino velocità, capacità di reazione e prestazioni.

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

## Cronologia

- 7 ottobre 2026: GPT Luna riconosce due immagini di colore diverso e muove
  Mario: il formato multimodale `state` è verificato su OpenRouter.
- 8 ottobre: il modello sceglie mosse complete (salti, corsa) con una sola
  richiesta in corso; si aggiungono la scena letta dalla RAM e la guida di gioco.
  A 60 FPS Mario arriva a x≈1270–1410.
- 15 ottobre: Jev 1.14 supera la verifica delle immagini (con il bordo 280×280).
- 29 ottobre: controllo diretto dei pulsanti (`buttons`, ora default) e pulsanti
  con durata (`timed`). A turni decider completa 1-1 in quattro episodi su
  quattro; in tempo reale nessun modello vince in 120 partite
  ([verifiche](harness-verification-2026-10-29.md),
  [benchmark](benchmark-2026-10-29.md)).
- 30 ottobre: modalità predittiva, anteprime delle opzioni, richieste parallele,
  contesto identico per tutti i modelli; prime vittorie a 60 FPS.

## Note sperimentali

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
