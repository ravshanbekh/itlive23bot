# ITLIVE CRM Web

React frontend + Node.js API + PostgreSQL. The existing Python Telegram bot remains running and unchanged. The CRM reads its SQLite database every 10 seconds to import new leads and validate the bot's existing one-time Telegram web sessions. The same SQLite database stores bot content and staff, so edits made in this CRM immediately apply to the bot. Sales stages, assignments, notes and reports are stored in PostgreSQL.

## Architecture

- Existing bot: `/opt/itlive23bot`, SQLite at `/opt/itlive23bot/data/itlive.sqlite3`.
- New CRM: `/opt/itlive-crm-web`, Node.js 24, PostgreSQL 17, React/Vite.
- Public path: `https://itlive.144-91-125-185.sslip.io/crm/` through the existing Caddy proxy.
- Admin login: send `/admin` to the existing bot and open the one-time link. Sellers log in at `/crm/seller/login` with an account created by an admin. Seller accounts exist only in PostgreSQL, so the bot does not send every new lead notification to them. Routes and API permissions are role-specific.
- No duplicate polling bot is started. The CRM's sync is a database reader, not a Telegram bot client.

## Local checks

```sh
npm ci
npm --prefix client ci
npm test
npm run build
```

The Node API requires `DATABASE_URL` and `BOT_SQLITE_PATH`; run it in the Compose environment. The built React app is served by Node under `/crm/`.

## Server deployment

Create `/opt/itlive-crm-web/.env` containing only `POSTGRES_PASSWORD` as a strong random value, mode `600`. Run `docker compose up -d --build`. The new Compose project joins the existing `itlive23bot_default` network for Caddy routing. Add the routes in `Caddyfile.snippet` to the existing Caddy site, then restart only the proxy. Confirm `/crm/health` and the role-specific UI. Keep both Compose projects on the same host so the CRM can access the bot's SQLite data.

PostgreSQL is persistent in the `postgres_data` volume. Install `deploy/itlive-crm-backup.service` and `.timer` into `/etc/systemd/system`, run `systemctl daemon-reload`, then `systemctl enable --now itlive-crm-backup.timer`. Backups run daily at 22:00 UTC (03:00 Toshkent) and stay on the same server; arrange an offsite copy separately. Existing bot SQLite backups do not include website statuses, assignments or notes. Do not copy a live SQLite file directly; use its existing online backup process.

## Business rules

The seven CRM stages are `Yangi lead`, `Bog‘lanildi`, `Bog‘lanib bo‘lmadi`, `Ma’lumot berildi`, `Tashrifga keldi`, `Sotib oldi`, `Sotib olmadi`. Follow-up deadlines are separate from stages. New leads go to the active seller with the fewest open leads; equal loads rotate. Existing assignments stay fixed until an admin changes them. If there are no active sellers, new leads remain unassigned for an admin to review.

The legacy bot's old statuses are mapped to the new seven-stage pipeline during import. Site stage changes do not rewrite the bot's historical lead records. Bot lead identity and contact corrections are synchronized to PostgreSQL, while website sales activity remains in PostgreSQL. Seller passwords are salted with scrypt and never stored in SQLite or sent to the bot.

## Owner agent and sales tasks

The bot's owner sees **🤖 AI nazorat** in its private chat. **📊 Hozirgi holat** requests a current report; **📝 Vazifa berish** accepts a task in natural language when an AI API key is configured. `/report` and `/task seller_login | task text` also work. The direct syntax works without an AI key. A seller must be named explicitly, and an ambiguous task is returned to the owner for correction. Tasks appear in the seller's **Vazifalar** page and can be marked complete there. The owner can also queue a report from **AI nazorat** on the website.

Reports are queued for the owner at 12:00 and 17:00 **Asia/Tashkent** and after pressing the report button. They include current lead stages, seller workload, overdue follow-ups and tasks. The monitor checks every five minutes and queues at most one alert per issue type per day. SQLite queue tables make report delivery survive bot and CRM restarts; the existing bot sends the queued Telegram messages. The scheduler uses a unique daily slot to avoid duplicate reports. Both services must remain on this host with the shared SQLite volume.

To enable AI interpretation and a short AI insight in each report, set one or more of `GROQ_API_KEY`, `OPENAI_API_KEY`, and `GEMINI_API_KEY` in `/opt/itlive-crm-web/.env`, then rebuild the CRM container. `AI_PROVIDER=auto` tries configured services in the order Groq → OpenAI → Gemini and falls back when one fails. Set `AI_PROVIDER=groq`, `openai`, or `gemini` to put that service first. Default models are `openai/gpt-oss-20b`, `gpt-4.1-mini`, and `gemini-3.8-flash`; override with `GROQ_MODEL`, `OPENAI_MODEL`, or `GEMINI_MODEL`. Keys are optional; factual scheduled and on-demand reports, alerts, and explicit `/task login | text` commands work without them. Keys are never stored in Git. Task creation only selects an active seller; it cannot change lead stages or delete data. If a task names a lead assigned to someone else, the owner must reassign that lead in CRM first.
