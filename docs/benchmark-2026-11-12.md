# Gemini Decision 1 — 12 novembre 2026

Dieci episodi reali con `google/gemini-decision-1` via OpenRouter, livello 1-1,
seed 123, 60 FPS, modalità predittiva, anteprime di 30 frame, due richieste
parallele e senza immagine. Configurazione e prompt sono quelli del
[benchmark del 30 ottobre](benchmark-2026-10-30.md): cambia il modello. Il
contesto è condiviso; le condizioni temporali e il carico del computer possono
variare tra sessioni.

```powershell
uv run main.py --model gemini_decision --execution-mode predictive --choice-preview 30 --parallel-requests 2 --no-image --headless --episodes 10
```

| Modello | Vittorie | Latenza mediana | Scelta ogni (mediana) | Costo noto medio / episodio |
| --- | ---: | ---: | ---: | ---: |
| Gemini Decision 1 | 0/10 | 0,234 s | 28 frame | 0,0099 $ |
| decider | 17/20 | 0,30 s | 42–49 frame | 0,0041 $ |
| d1 | 3/5 | 0,23 s | 40 frame | 0,0056 $ |
| GPT Luna | 2/3 | 0,43 s | 60 frame | 0,0242 $ |
| Jev | 1/5 | 0,21 s | 36 frame | 0,0070 $ |

Gemini è morto in tutti gli episodi, con posizione massima rispettivamente
2010, 1524, 683, 2469, 691, 304, 2006, 1129, 707 e 682; il traguardo è
intorno a x=3160. La latenza p95 è 0,330 s, comprensiva di rete e servizio,
non solo inferenza. La cadenza è la mediana di 207 intervalli fra scelte
applicate nello stesso episodio. Il gioco ha raggiunto 59,56 FPS complessivi;
il throughput iniziale dell'emulatore era 2478 frame/s. Una scelta su 217 è
arrivata in ritardo; nessun errore o retry è stato registrato.

Il costo noto totale è 0,0990456 $, incluse le copie parallele di cui è stato
riportato il costo. Tutte le 227 risposte principali ricevute riportano un
costo; eventuali richieste non contabilizzate dal provider possono aggiungere
costi. Il costo medio dipende anche dalla durata: gli episodi conclusi presto
costano meno. Con zero vittorie non è calcolabile un costo per vittoria.

La prova misura un solo seed e un solo livello; i campioni storici degli altri
modelli sono piccoli e provengono da sessioni precedenti. Non dimostra come
Gemini si comporti con immagini o altre configurazioni. I file locali originali
sono in `runs/20261112T112212-f6c3a65d7166/`; configurazione e riepilogo sono
conservati in [benchmark-data/2026-11-12/](benchmark-data/2026-11-12/).
