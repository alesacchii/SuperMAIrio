# Confronto ripetuto: Joey, Decider e Gemini — 12 novembre 2026

Dopo la chiusura di alcune applicazioni, tre sessioni consecutive da 10 episodi
ciascuna: livello 1-1, seed 123, 60 FPS, modalità predittiva, anteprime di 30
frame, due copie parallele e senza immagine. Nessuna sessione è stata eseguita
contemporaneamente alle altre. `decider` è il modello standard, non Flash.

| Modello | Vittorie | Latenza mediana / p95 | Preparazione mediana | Scelte in ritardo | FPS | Throughput iniziale | Costo noto |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| Joey | 0/10 | 0,242 / 0,267 s | 0,200 s | 0/204 | 60,04 | 1732 frame/s | 0,00892848 $ |
| Decider | 6/10 | 0,352 / 0,404 s | 0,222 s | 8/355 | 59,98 | 2786 frame/s | 0,03084458 $ |
| Gemini | 1/10 | 0,280 / 0,389 s | 0,203 s | 2/291 | 60,03 | 2154 frame/s | 0,13443420 $ |

Tutte e tre le sessioni sono terminate regolarmente, senza errori o retry
registrati. Decider ha due richieste cancellate: eventuali costi non riportati
dal provider possono aggiungersi al costo noto. Le latenze comprendono rete e
servizio OpenRouter e sono misurate sulle risposte principali ricevute; le due
copie sono inviate per ogni richiesta. La preparazione locale è una misura
distinta dalla latenza della richiesta.

Le precedenti prove di Joey e Gemini avevano prodotto rispettivamente 1/10 con
932 frame/s e 0/10 con 2478 frame/s. Per Decider il benchmark storico ha dato
17/20, in due sessioni. Le differenze su campioni piccoli, un solo seed e
sessioni non contemporanee non dimostrano la causa delle sconfitte. Il
throughput iniziale di Joey rimane sotto la soglia consigliata di 2000 frame/s;
le condizioni locali non sono quindi equivalenti fra tutti e tre i modelli.
Le richieste valide e le latenze osservate non mostrano un guasto evidente
dell'API, ma non escludono cambiamenti del provider, differenze nel modello o
effetti della latenza. Le anteprime sono informazioni emulate fornite a tutti;
non si misura la capacità di prevedere autonomamente la fisica.

Riepiloghi e configurazioni sono in [benchmark-data/confronto-2026-11-12/](benchmark-data/confronto-2026-11-12/).
Log completi locali: `runs/20261112T120039-401cf21cbab4` (Joey),
`runs/20261112T120238-3eff48809492` (Decider),
`runs/20261112T120638-12f008fa1aaf` (Gemini).
