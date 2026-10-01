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
