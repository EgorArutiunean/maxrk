# maxrk

`maxrk` is a one-way bridge that reposts posts from a Telegram channel into a MAX chat.

## What it does

- Reads `channel_post` updates from Telegram via long polling.
- Filters posts from one configured Telegram source channel.
- Forwards text and supported attachments into one configured MAX chat.
- Groups Telegram media albums before sending them to MAX.

## Configuration

Create `.env` from `.env.example` and set:

- `TELEGRAM_BOT_TOKEN`
- `MAX_BOT_TOKEN`
- `SOURCE_TG_CHAT`
- `TARGET_MAX_CHAT`
- `INSTANCE_NAME`

`SOURCE_TG_CHAT` can be a numeric chat id, `@username`, or Telegram link.

`TARGET_MAX_CHAT` can be a numeric chat id, `@username`, or MAX link.

Use a unique `INSTANCE_NAME` and `STATE_FILE` for each bridge instance so logs and Telegram offsets do not overlap.

## Run with Docker

```bash
docker compose up -d --build
```

Local `docker compose` will automatically read variables from `.env`.

## Run locally

```bash
python -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python app.py
```

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python app.py
```

## Deployment

See `VM_SETUP.md`.

## Deploy to Coolify

Use a Docker Compose deployment for this project. It is a background worker with persistent state and no public HTTP port.

In Coolify:

1. Create a new resource from the `maxrk` GitHub repository.
2. Select the `Docker Compose` deployment type.
3. Use `compose.yaml` from the repository.
4. Do not configure a domain or exposed port for this service.
5. Set these environment variables in Coolify:
   `TELEGRAM_BOT_TOKEN`, `MAX_BOT_TOKEN`, `SOURCE_TG_CHAT`, `TARGET_MAX_CHAT`, `INSTANCE_NAME`, `STATE_FILE`.
6. Leave `STATE_FILE` as `/app/data/maxrk-state.json` unless you have a reason to change it.
7. Deploy and verify logs contain `[maxrk] Telegram -> MAX bridge started`.
