# Joey 1 — 12 novembre 2026

Dieci episodi reali con `baseten/joey-1` via OpenRouter, livello 1-1, seed 123,
gioco a 60 FPS, modalità predittiva, anteprime di 30 frame, due richieste
parallele e senza immagine. La configurazione e il prompt sono gli stessi del
[benchmark del 30 ottobre](benchmark-2026-10-30.md) e della
[prova Gemini](benchmark-2026-11-12.md); le condizioni di esecuzione possono variare.

```powershell
uv run main.py --model joey --execution-mode predictive --choice-preview 30 --parallel-requests 2 --no-image --headless --episodes 10
```

| Modello | Vittorie | Latenza mediana | Scelta ogni (mediana) | Costo noto medio / episodio |
| --- | ---: | ---: | ---: | ---: |
| Joey 1 | 1/10 | 0,240 s | 28 frame | 0,000746 $ |
| Gemini Decision 1 | 0/10 | 0,234 s | 28 frame | 0,0099 $ |
| decider | 17/20 | 0,30 s | 42–49 frame | 0,0041 $ |
| d1 | 3/5 | 0,23 s | 40 frame | 0,0056 $ |
| GPT Luna | 2/3 | 0,43 s | 60 frame | 0,0242 $ |
| Jev | 1/5 | 0,21 s | 36 frame | 0,0070 $ |

**Limite del confronto:** il controllo iniziale ha misurato 932 frame/s di
emulazione, sotto la soglia di 2000 del programma e sotto i circa 2900 del
benchmark originale e i 2478 della prova Gemini. Il carico della CPU può
cambiare la preparazione e la cadenza delle scelte, rendendo la prova poco
rappresentativa. I campioni sono piccoli, su un solo livello e un solo seed.

Joey ha vinto il quarto episodio in 1586 frame; gli altri sono terminati per
morte. Le posizioni massime sono 1434, 314, 1506, 3161, 1528, 710, 698,
701, 812 e 314. La latenza p95 è 0,264 s e comprende rete e servizio, non solo
inferenza. La mediana di 28 frame è calcolata su 160 intervalli fra scelte
applicate nello stesso episodio. FPS effettivi complessivi: 59,18; una scelta
in ritardo su 170, nessun errore o retry.

Il costo noto totale è 0,00745904 $, incluse le copie parallele contabilizzate;
180 risposte principali riportano un costo. Eventuali richieste non contabilizzate
dal provider possono aggiungere costi. Una sconfitta precoce costa meno di una
partita lunga; costo per vittoria osservato: 0,00745904 $ su una sola vittoria.
Il benchmark non verifica l'input immagine.

I log locali sono in `runs/20261112T114334-13799c2fc03b/`; configurazione e
riepilogo sono conservati in [benchmark-data/joey-2026-11-12/](benchmark-data/joey-2026-11-12/).
