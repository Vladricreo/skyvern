# Deploy Ricreo su Coolify

Il docker-compose.yml principale costruisce backend e frontend dai sorgenti del fork.
Base verificata il 1 ottobre 2026: upstream/main 4a3ca3abc. Nessuna immagine UI
v1.0.42 e nessuna patch JavaScript applicata al bundle in produzione.

## Configurazione

- Repository: https://github.com/Vladricreo/skyvern, branch main, Compose /docker-compose.yml.
- API: https://api.skyvern.ricreo.app -> porta interna 8000 (host 18000).
- UI: https://skyvern.ricreo.app -> porta interna 8080 (host 18080).
- PostgreSQL: mantenere /var/lib/skyvern-postgres, gia usato in produzione.
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
