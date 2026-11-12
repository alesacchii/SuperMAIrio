# Nuovo benchmark uniforme — 12 novembre 2026

Nuove sessioni indipendenti, una alla volta: livello 1-1, seed 123, 60 FPS,
modalità predittiva, pulsanti, anteprime 30 frame, due copie parallele, senza
immagini e senza finestra, limite 3600 frame e 60 secondi. Ogni modello riceve
lo stesso formato di contesto e le stesse istruzioni e scelte; lo stato e le
anteprime dipendono dalla partita e dal momento in cui si applica la scelta.

```powershell
uv run main.py --model MODELLO --execution-mode predictive --control-mode buttons --seed 123 --choice-preview 30 --parallel-requests 2 --no-image --headless --episodes 10
```

| Modello | Vittorie | Altri esiti | Latenza mediana / p95 | Scelta ogni | Ritardi | FPS | Throughput iniziale | Costo noto totale |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| decider | 8/10 | 2 morti | 0,357 / 0,442 s | 35 frame | 7/415 | 59,89 | 2046 frame/s | 0,036799 $ |
| d1 | 5/10 | 4 morti, 1 limite | 0,288 / 0,464 s | 33 frame | 3/497 | 59,85 | 1857 frame/s | 0,043049 $ |
| jev | 3/10 | 7 morti | 0,211 / 0,251 s | 25 frame | 4/474 | 59,88 | 2325 frame/s | 0,098029 $ |
| gemini_decision | 1/10 | 9 morti | 0,359 / 0,932 s | 35 frame | 6/163 | 59,94 | 2071 frame/s | 0,075460 $ |
| decider_flash | 0/10 | 6 morti, 4 limiti | 0,215 / 0,259 s | 25 frame | 8/774 | 59,38 | 2553 frame/s | 0,033524 $ |
| joey | 0/10 | 10 morti | 0,243 / 0,286 s | 28 frame | 0/167 | 60,04 | 2209 frame/s | 0,007318 $ |
| gpt_luna | non valutato | 3 sessioni interrotte da HTTP 502, nessun episodio concluso | — | — | — | — | 2635, 2058, 1926 frame/s | incompleto |

Per Luna ogni sessione ha registrato un errore 502, un nuovo tentativo e un
secondo 502. Le sessioni interrotte non sono sconfitte. I rispettivi eventi
registrano 8, 72 e 15 risposte principali prima dell'errore, con costi principali
noti per almeno 0,0201773 $ complessivi; non è un costo totale, perché copie
parallele e richieste fallite possono aggiungere costi. Per queste sessioni il
`summary.json` riporta erroneamente zero decisioni e nessun episodio: usare gli
eventi per i risultati parziali. I log locali completi sono in `runs/`.

I costi in tabella sommano quelli noti, incluse le copie parallele contabilizzate;
richieste cancellate o fallite possono generare costi non riportati. La latenza
include rete e servizio, non è il solo tempo di inferenza. La cadenza è la
mediana degli intervalli fra scelte applicate nello stesso episodio.

Le impostazioni sono identiche, ma il carico locale e la rete non sono
controllabili perfettamente: il throughput di d1 è sotto la soglia consigliata
di 2000 frame/s. I campioni sono piccoli, su un livello e un seed; le anteprime
sono esiti emulati forniti al modello. I risultati non isolano le prestazioni
del provider o la capacità di prevedere la fisica autonomamente.

Configurazioni e riepiloghi sono in [benchmark-data/uniforme-2026-11-12/](benchmark-data/uniforme-2026-11-12/).
Log locali completi: `runs/20261112T132050-9910a454317e` (decider),
`runs/20261112T132524-c99c8fce00bb` (flash), `runs/20261112T133132-281471a99424` (d1),
`runs/20261112T133823-10e0f6a5cef8` (jev), `runs/20261112T134216-0cdafc31727c` (Gemini),
`runs/20261112T134437-5f7b447b5e1d` (Joey), `runs/20261112T133648-47d703ff6cab`,
`runs/20261112T133735-d807dd15c20d` e `runs/20261112T134643-2f8b0619e159` (Luna).
