# Deploy Ricreo su Coolify

Il docker-compose.yml principale costruisce backend e frontend dai sorgenti del fork.
Base verificata il 1 ottobre 2026: upstream/main 4a3ca3abc. Nessuna immagine UI
v1.0.42 e nessuna patch JavaScript applicata al bundle in produzione.

## Configurazione

- Repository: https://github.com/Vladricreo/skyvern, branch main, Compose /docker-compose.yml.
- API: https://api.skyvern.ricreo.app -> porta interna 8000 (host 18000).
- UI: https://skyvern.ricreo.app -> porta interna 8080 (host 18080).
- PostgreSQL: /var/lib/skyvern-postgres-production, fuori dalla directory di checkout che Coolify cambia di proprietario.
- Mantenere la stessa risorsa Coolify: gli altri volumi relativi restano nel suo
  project directory. Per una nuova risorsa migrare prima tutti i volumi, incluso
  credential_vault, browser_sessions e .skyvern.
- Runtime .env gestito da Coolify: conservare le chiavi e i segreti esistenti.
  LLM_KEY=OPENAI_GPT5_6_SOL, ENABLE_OPENAI=true e OPENAI_API_KEY esistente.
- La UI usa SKYVERN_API_BASE_URL=http://skyvern:8000/api/v1 per emettere sessioni
  temporanee; la chiave organizzazione resta sul server (SKYVERN_API_KEY o file
  .skyvern/credentials.toml condiviso). Il fallback VITE_SKYVERN_API_KEY legacy
  resta supportato dall'entrypoint upstream. Non salvare chiavi nel repository.
- Clerk non e richiesto: la UI OSS usa la propria autenticazione. Il Compose
  imposta VITE_CLERK_PUBLISHABLE_KEY vuoto e VITE_ENVIRONMENT=local.

## Passaggio dal deploy precedente

1. Pubblicare le modifiche del fork e selezionare il fork nella risorsa Coolify.
2. Conservare variabili, domini, volumi e configurazione del proxy esistenti.
   Prima del primo deploy arrestare i container e copiare il postgres-data originale
   in /var/lib/skyvern-postgres-production, preservando i dati e assegnando UID/GID
   70:70 (postgres:14-alpine). Non avviare con una directory database vuota.
3. Svuotare Docker Compose Custom Start Command (e gli eventuali vecchi comandi
   custom di build). Usare build/avvio Compose standard di Coolify.
4. Fare un redeploy con build. Non serve prepare.sh, sed o un'immagine UI locale.
5. Verificare UI, /ui-session, creazione da prompt e una sessione browser.

L'accesso alla diagnostica interna resta limitato a localhost. Solo il suo esatto
403 viene mostrato come indisponibilita della diagnostica remota; gli errori reali
401/403 delle API restano visibili. Mantenere i controlli di accesso di rete esistenti.

Per tornare indietro conservare la precedente configurazione Coolify e un backup
del database prima del primo deploy: un backend aggiornato puo eseguire migrazioni.
Il repository non esegue automaticamente push o deploy.

Per GPT-6 Astra impostare LLM_KEY=OPENAI_GPT6_ASTRA e
GPT6_ASTRA_REASONING_EFFORT=low (oppure medium, high, xhigh, max) nelle variabili
runtime di Coolify, salvare e fare Redeploy. Il default resta xhigh; il valore
si applica alle configurazioni Astra dirette e ai router. Non modifica altri modelli.

## Jev sperimentale

Jev interviene solo in `RealSkyvernPageAi.ai_click` per scegliere un link o pulsante
ordinario quando non servono payload o contesto aggiuntivo. Non sostituisce il
modello principale, l'estrazione o il ciclo del Browser Task 1.0. Non aspettarsi
accelerazioni nei workflow che non percorrono questo ramo.

In Coolify, variabili runtime del backend (lette da `.env`):

```env
ENABLE_JEV_CLICK=true
TYPESAFE_API_KEY=<inserire solo su Coolify>
JEV_MODEL=jev-latest
JEV_ALLOWED_HOSTS=["example.com"]
JEV_MIN_CONFIDENCE=0.9
JEV_TIMEOUT_SECONDS=2
```

Salvare, Reload compose e Redeploy. Il default e disattivato e la lista host vuota.
Prima di aggiungere un dominio aziendale, verificare quali dati si inviano a
TypeSafe: istruzione del click ed etichette dei link/pulsanti possono contenere dati
riservati. Non vengono inviati screenshot, HTML completo, URL o valori dei campi.
Non abilitare Aruba per il primo test. Serve una chiave dalla console ufficiale:
https://console.typesafe.ai ; API: https://docs.typesafe.ai/introduction/quickstart .

La selezione incerta, i controlli non supportati, errori e timeout ritornano al
modello originale. I normali controlli di esecuzione Skyvern restano attivi.
Un errore di esecuzione dopo la scelta segue il recupero standard di Skyvern,
non ripete automaticamente il click via GPT. La confidenza non garantisce correttezza.

Test trasporto offline: `python -m unittest discover -s tests/jev -v`.
Per il confronto live usare un workflow con `ai_click` su una pagina di prova,
eseguire prima con flag false e poi true, confrontando esiti e tempi totali.
I log `jev_click_selected`/`jev_click_fallback` contengono solo la latenza;
un test su example.com senza click non misura questa integrazione.
Senza API key non e possibile verificare compatibilita live o guadagni di velocita.

## Miglioramento dei workflow (prima versione a regole)

Il Compose Ricreo abilita `ENABLE_WORKFLOW_LEARNING=true`. Il default del codice
upstream-style e false. Non richiede Jev o una nuova chiave e non chiama un LLM:
analizza gli esiti e propone istruzioni aggiuntive deterministiche. Non comprende
semanticamente le cause degli errori e non riscrive liberamente i prompt.

Prima di usarlo fare Reload compose e Redeploy. Il volume
`./workflow_learning:/data/workflow_learning` conserva il database SQLite locale.
Includerlo nei backup; non e un database condiviso per repliche su host diversi.

Ad ogni esecuzione viene registrato l'hash della definizione all'avvio; alla fine
si raccolgono stato, durata, crediti e stato dei blocchi. Dopo almeno tre run
completi della stessa definizione (`WORKFLOW_LEARNING_MIN_RUNS`, minimo 3), vengono
salvate proposte immutabili per i blocchi con navigation_goal. Gli originali e i
placeholder restano intatti; viene aggiunta solo una guida da revisionare.
Le proposte non vengono applicate automaticamente. Le righe del database locale
non contengono prompt, credenziali, output o motivi di errore testuali.

Non contare come prove i test Studio di blocchi isolati, i run figli o quelli
ancora in retry. Lo storico importato senza snapshot iniziale compare nel report,
ma non determina proposte o promozioni. I retry di invio della telemetria sono
idempotenti. `Completed` non equivale a un risultato verificato.

### Consultazione e revisione

Le API autenticate sono sotto `/v1/workflows/{wpid}/learning`. Si possono usare
anche da `/docs` se la documentazione API e disponibile; non c'e ancora un pannello
nell'editor Skyvern. CLI nel repository (API key solo in variabile d'ambiente):

```sh
# SKYVERN_API_BASE_URL=https://api.skyvern.ricreo.app/v1
# SKYVERN_API_KEY=<chiave API esistente, non inserirla nel repository>
python scripts/workflow_learning.py wpid_... report
python scripts/workflow_learning.py wpid_... analyze
python scripts/workflow_learning.py wpid_... candidate BASELINE_HASH
python scripts/workflow_learning.py wpid_... verify wr_... success --case invoices10 --benchmark aruba-v1
python scripts/workflow_learning.py wpid_... compare BASELINE_HASH CANDIDATE_HASH --benchmark aruba-v1
```

`analyze` importa al massimo gli ultimi 30 run. `candidate` esporta JSON con una
workflow_definition candidata e la proposta: revisionare i prompt, conservare la
versione originale e applicare manualmente tramite gli strumenti workflow normali.
Non importare automaticamente il risultato nel workflow delle fatture. Se nel
frattempo il workflow cambia, l'esportazione viene rifiutata (409).

Per una prova usare lo stesso workflow permanente, dataset, sito, modello e
configurazione, prima con la versione originale e poi con quella candidata.
Registrare il risultato esterno con `verify`: per le fatture controllare file,
formato e contenuto richiesto. Non inserire dati personali in case/benchmark.
Il confronto richiede almeno tre risultati verificati per versione, uguali casi
con uguale frequenza e configurazione registrata. Suggerisce la revisione per
promozione solo con 100% di successi verificati nella candidata, nessuna regressione,
mediana inferiore e crediti non aumentati. Non e una garanzia statistica e i crediti
Skyvern non misurano necessariamente i costi del provider. Nessuna promozione o
esecuzione di benchmark automatica: il ripristino resta sulla versione precedente.

Il sistema esistente di adaptive caching/self-healing resta separato e invariato.
Questa funzione non attiva automaticamente la conversione in Playwright e non
promette guadagni prima di un confronto reale. Test offline:
`python -m unittest discover -s tests/workflow_learning -v`.
