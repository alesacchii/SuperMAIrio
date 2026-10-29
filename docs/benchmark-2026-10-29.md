# Benchmark modelli — 29 ottobre 2026

Livello 1-1, seed 123, scena letta dalla RAM, Decisions API OpenRouter. Quattro
modelli con lo stesso adapter `ChoiceModel`, quindi stesso stato, stesse
istruzioni e stesse scelte. Jev riceve lo screenshot con un bordo nero fino a
280×280 e una frase che lo spiega.

| Alias | Identificativo OpenRouter |
| --- | --- |
| `decider` | `perplexity/pplx-decider-v1.2` |
| `jev` | `typesafe/jev-1.14` |
| `d1` | `liquid/d1.1` |
| `gpt_luna` | `openai/gpt-6-luna-decisions` |

Le latenze comprendono rete e servizio OpenRouter e non sono il solo tempo di
inferenza. I costi sono quelli noti (`usage.cost`) delle richieste ricevute.

## 1. Qualità delle decisioni a turni

Una partita per modello con `--execution-mode paused --control-mode timed`. Il
gioco è fermo durante la decisione, quindi la latenza non influisce sull'esito.
Il modello sceglie pulsanti e durata con due chiamate in sequenza (prompt
`timed` revisione 1, identico a quello della vittoria del 29 ottobre).

| Modello | Esito | x max | Si ferma a | Frame | Decisioni | Frame per decisione | Quota di salti | Latenza mediana (2 chiamate) | Costo $ |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `decider` | **completato** | 3161 | bandiera | 1382 | 169 | 8,2 | 28% | 0,63 s | 0,0123 |
| `gpt_luna` | morte | 1435 | buca 2 (48 px) | 725 | 199 | 3,6 | 9% | 0,66 s | 0,0678 |
| `jev` | bloccato, fermato dopo 250 frame senza progresso | 594 | tubo 2 (3 tile) | 1012 | 44 | 23,0 | 80% | 0,44 s | 0,0081 |
| `d1` | morte | 288 | primo Goomba | 144 | 18 | 8,0 | 11% | 0,70 s | 0,0012 |

Sessioni: `runs/20261029T193332-479bf94e9d7d` (decider), `193341-545b3797c241`
(Luna), `193335-35ab3a5b87e6` (Jev), `193338-d075c5c8229b` (d1).

Come si comportano i modelli:

- **decider** alterna corsa da 8 frame (121 scelte su 169) e salti dosati: 8
  frame per i salti bassi, 28 per tubi e buche. Ripete la stessa vittoria in
  ogni episodio: è la quinta identica.
- **Luna** usa quasi solo durate di 2 frame (171 scelte su 199), con molte più
  decisioni e un costo 5 volte maggiore. Supera tubi e prima buca, poi sopra la
  seconda buca rilascia tutto (`noop_2` ripetuto) e ci cade. Due errori HTTP 503
  sono stati recuperati dal nuovo tentativo.
- **Jev** supera il primo Goomba e il primo tubo. Davanti al secondo sceglie solo
  salti da 28 frame senza mai rilasciare A: lo tiene premuto per 588 frame,
  nonostante l'avviso nello stato che così nessun salto può partire.
- **d1** rilascia i pulsanti (`noop_8`) accanto al primo Goomba e poi ci corre addosso.

Limiti di questa parte:

- È una partita per modello: modello ed emulatore sono deterministici e la
  ripetizione dà la stessa partita, quindi non è una frequenza di successo.
- Il prompt `timed` è stato corretto osservando soprattutto le partite di decider.
- È molto sensibile al testo. Cambiando solo la descrizione di un'opzione,
  decider è morto a x=1151, e con un'altra formulazione a x=2030.
- Con Luna il provider risponde HTTP 502 in alcuni stati quando la prima risposta
  è `noop`. Riformulare non lo ha eliminato in modo affidabile.

## 2. Dieci partite per modello a velocità normale

60 FPS, `realtime`, limite di 60 s reali per partita, due modelli in parallelo.
Gli FPS effettivi mediani sono 57,4–58,4 in tutte le sessioni. Tre configurazioni:

- **A**, attuale: `--control-mode buttons`, con screenshot;
- **B**, latenza ridotta: `--control-mode timed --no-image`, una sola chiamata
  con le 40 combinazioni pulsanti+durata;
- **C**: `--control-mode buttons --no-image`, per isolare l'effetto dell'immagine.

**Nessuna vittoria in 120 partite.**

| Config | Modello | Vittorie | Morti / limite 60 s | x mediano | x medio | x migliore | Latenza mediana | Età osservazione (frame) | Decisioni | Costo $ |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | decider | 0/10 | 7 / 3 | 434 | 658 | 1797 | 0,321 s | 19,0 | 589 | 0,0153 |
| A | jev | 0/10 | 10 / 0 | 312 | 478 | 1138 | 0,223 s | 13,3 | 284 | 0,0206 |
| A | d1 | 0/10 | 10 / 0 | 315 | 401 | 823 | 0,264 s | 15,3 | 118 | 0,0028 |
| A | gpt_luna | 0/10 | 10 / 0 | 315 | 511 | 1128 | 0,449 s | 26,0 | 149 | 0,0184 |
| B | decider | 0/10 | 10 / 0 | 260 | 443 | 1400 | 0,322 s | 18,5 | 207 | 0,0123 |
| B | jev | 0/10 | 7 / 3 | 714 | 603 | 835 | 0,214 s | 12,0 | 1180 | 0,1751 |
| B | d1 | 0/10 | 8 / 2 | 151 | 169 | 247 | 0,243 s | 14,0 | 1472 | 0,0734 |
| B | gpt_luna | 0/10 | 10 / 0 | 258 | 513 | 1130 | 0,362 s | 20,8 | 326 | 0,0932 |
| C | decider | 0/10 | 9 / 1 | 710 | 744 | 1526 | 0,292 s | 16,5 | 354 | 0,0089 |
| C | jev | 0/10 | 10 / 0 | 315 | 395 | 1124 | 0,215 s | 12,3 | 142 | 0,0086 |
| C | d1 | 0/10 | 10 / 0 | 314 | 388 | 692 | 0,225 s | 13,0 | 110 | 0,0024 |
| C | gpt_luna | 0/10 | 9 / 1 | 315 | 507 | 898 | 0,321 s | 18,5 | 431 | 0,0538 |

Latenza ed età sono le mediane per partita, poi la mediana delle dieci partite.
L'età è in frame di gioco dall'osservazione all'avvio della scelta. "Limite 60 s"
indica Mario vivo ma fermo o lento.

Dove finiscono le morti, stimate dalla x massima:

| Zona | A | B | C |
| --- | ---: | ---: | ---: |
| Primo Goomba (x≈320) | 26 | 25 | 24 |
| Tubi 3–4 (x≈736–912) | 6 | 6 | 12 |
| Prima buca (x≈1104) | 3 | 3 | 1 |
| Zona centrale (x≈1376–2144) | 2 | 1 | 1 |

Sessioni: A `194031` (d1), `193639` (decider), `194033` (Luna), `193641` (Jev);
B `194644`, `194150`, `194646`, `194152`; C `195604`, `195353`, `195607`, `195355`
(tutte `runs/20261029T…`).

## 3. Prove per ridurre la latenza

Stessa richiesta reale (Mario in corsa davanti al primo Goomba), 8 invii per
modello e variante, connessione persistente:

| Modello | buttons + immagine | buttons, no immagine | timed + immagine | timed, no immagine |
| --- | ---: | ---: | ---: | ---: |
| decider | 0,582 s | 0,316 s | 0,371 s | 0,332 s |
| jev | 0,222 s | 0,235 s | 0,236 s | 0,212 s |
| d1 | 0,324 s | 0,292 s | 0,269 s | 0,278 s |
| gpt_luna | 0,356 s | 0,336 s | 0,363 s | 0,310 s |

Nelle partite, togliere l'immagine (A → C) ha ridotto latenza ed età
dell'osservazione per tutti, poco per Jev e di più per Luna:

| Modello | Latenza A → C | Età A → C (frame) |
| --- | --- | --- |
| decider | 0,321 → 0,292 s | 19,0 → 16,5 |
| jev | 0,223 → 0,215 s | 13,3 → 12,3 |
| d1 | 0,264 → 0,225 s | 15,3 → 13,0 |
| gpt_luna | 0,449 → 0,321 s | 26,0 → 18,5 |

Il costo per richiesta resta quasi invariato: lo screenshot pesa poco. La
lunghezza del prompt (`timed` ha 40 opzioni) non aumenta in modo visibile la
latenza. Il minimo resta 0,21–0,33 s, cioè 13–20 frame a 60 FPS: dipende dal
servizio, non dalla preparazione locale (circa 4 ms).

## Conclusioni

1. **A turni la differenza fra i modelli è netta.** Solo decider completa il
   livello; Luna arriva al 45%, Jev e d1 non superano i primi ostacoli. Il
   risultato di decider dipende però da un prompt rifinito sulle sue partite e
   sensibile a piccole modifiche.
2. **A velocità normale nessun modello vince**, in nessuna configurazione.
   Circa due terzi delle morti avvengono al primo Goomba: con 13–26 frame di
   ritardo i modelli non anticipano dove sarà il nemico.
3. **Togliere l'immagine riduce la latenza di 8–128 ms** e l'età dell'osservazione
   di 1–7,5 frame, ma non porta vittorie. Il miglioramento di decider in C (x
   mediano 710 contro 434) è compatibile con la variabilità su 10 partite.
4. **Il protocollo `timed` a chiamata singola non aiuta in tempo reale**, tranne
   per Jev, che ha x mediano 714 contro 312 ma il costo più alto (0,18 $).
   Con d1 produce molte scelte brevi senza progresso.
5. Per vincere a velocità normale non basta ridurre la latenza: servirebbe
   compensarla, per esempio con lo stato proiettato al momento in cui la scelta
   ha effetto, che però cambia che cosa misura l'esperimento.

## Riproduzione

```powershell
# Qualità a turni, una partita per modello
uv run main.py --model decider --execution-mode paused --control-mode timed --headless

# Tempo reale, dieci partite: A, B e C
uv run main.py --model decider --headless --episodes 10 --control-mode buttons
uv run main.py --model decider --headless --episodes 10 --control-mode timed --no-image
uv run main.py --model decider --headless --episodes 10 --control-mode buttons --no-image
```

Costo noto di queste prove: circa 0,65 $, più circa 0,01 $ delle 128 richieste
di misura della latenza. Le richieste cancellate a fine partita possono avere
un costo non riportato.
