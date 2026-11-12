# Decider Flash V1.2 — 12 novembre 2026

Dieci episodi reali con `perplexity/pplx-decider-flash-v1.2` via OpenRouter,
livello 1-1, seed 123, 60 FPS, modalità predittiva, anteprime di 30 frame,
due richieste parallele e senza immagine. Configurazione e prompt sono quelli
del [benchmark del 30 ottobre](benchmark-2026-10-30.md), della
[prova Gemini](benchmark-2026-11-12.md) e della [prova Joey](benchmark-joey-2026-11-12.md).

```powershell
uv run main.py --model decider_flash --execution-mode predictive --choice-preview 30 --parallel-requests 2 --no-image --headless --episodes 10
```

| Modello | Vittorie | Latenza mediana | Scelta ogni (mediana) | Costo noto medio / episodio |
| --- | ---: | ---: | ---: | ---: |
| Decider Flash | 0/10 | 0,211 s | 26 frame | 0,00332 $ |
| decider | 17/20 | 0,30 s | 42–49 frame | 0,0041 $ |
| d1 | 3/5 | 0,23 s | 40 frame | 0,0056 $ |
| GPT Luna | 2/3 | 0,43 s | 60 frame | 0,0242 $ |
| Jev | 1/5 | 0,21 s | 36 frame | 0,0070 $ |
| Gemini Decision 1 | 0/10 | 0,234 s | 28 frame | 0,0099 $ |
| Joey 1 | 1/10 | 0,240 s | 28 frame | 0,000746 $ |

**Limite del confronto:** il controllo iniziale ha misurato 1319 frame/s di
emulazione, sotto la soglia di 2000 del programma, rispetto ai circa 2900 del
benchmark originale, 2478 di Gemini e 932 di Joey. Il carico della CPU può
modificare la preparazione e la cadenza delle scelte. I campioni sono piccoli,
su un solo livello e un solo seed, in sessioni diverse.

Flash non ha vinto: sei episodi sono terminati per morte e quattro al limite di
60 secondi. Le posizioni massime sono 2402, 2178, 722, 2226, 2179, 899,
1434, 1778, 315 e 1954. La latenza p95 è 0,245 s e comprende rete e servizio,
non solo inferenza. La cadenza è la mediana di 765 intervalli fra scelte
applicate nello stesso episodio. FPS effettivi complessivi: 59,53; 11 scelte
in ritardo su 775, nessun errore o retry.

Il costo noto totale è 0,03316846 $, incluse le copie parallele contabilizzate;
781 risposte principali riportano un costo. Eventuali richieste non contabilizzate
dal provider possono aggiungere costi. Il costo medio dipende dalla durata degli
episodi; senza vittorie non è calcolabile il costo per vittoria. Il benchmark
non verifica l'input immagine.

I log locali sono in `runs/20261112T115155-ce09e7c3b24e/`; configurazione e
riepilogo sono conservati in [benchmark-data/decider-flash-2026-11-12/](benchmark-data/decider-flash-2026-11-12/).
