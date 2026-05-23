# Telegram Job Alert Bot

A VPS-friendly Telegram bot that scans remote job sources every hour, filters openings for your profile, and sends alerts only for new matches.

## What it does

- Polls job sources on a schedule
- Matches jobs against your AI / Python backend profile
- Deduplicates alerts with SQLite
- Sends hourly Telegram alerts only for new opportunities
- Supports on-demand commands like `/run_now` and `/status`

## Included sources

- Mostaql freelance projects
- Remote OK API
- Remotive API
- Jobicy API

Tune the matching rules in `profile.yaml`.

## Docker quick start

1. Create a Telegram bot with [@BotFather](https://core.telegram.org/bots#how-do-i-create-a-bot).
2. Copy `.env.example` to `.env`, then set `TELEGRAM_BOT_TOKEN` and optionally `ALLOWED_USER_IDS`.
3. Edit `profile.yaml` for your preferred roles, skills, and locations.
4. Start the bot:

```bash
docker compose up -d --build
```

5. Watch logs until the bot is ready:

```bash
docker compose logs -f job-alert-bot
```

6. Open the bot in Telegram and send `/start`.

The database is stored in the Docker volume `job-alert-data`, so the bot keeps its state across container restarts. No ports are exposed because the bot uses Telegram long polling.

The default profile now targets remote and freelance work across AI, backend, fullstack web, and desktop-application roles.

## Useful Docker commands

```bash
docker compose ps
docker compose restart job-alert-bot
docker compose down
docker compose run --rm job-alert-bot python -m job_alert_bot --preview
```

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m job_alert_bot
```

Optional but recommended: set `ALLOWED_USER_IDS` in `.env` to your Telegram numeric user id.

## Dry-run before Telegram

You can verify the matcher without sending Telegram messages:

```bash
python -m job_alert_bot --preview
```

## Linux VPS with systemd

If you prefer running directly on the host instead of Docker, an example unit file is available at `systemd/job-alert-bot.service`.

```bash
sudo cp systemd/job-alert-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now job-alert-bot
sudo systemctl status job-alert-bot
```

## Notes

- The first scheduled scan can warm up the database without sending old jobs if `warmup_without_alerts: true`.
- `/run_now` always gives you a live digest even if jobs were seen before.
- Edit `profile.yaml` to tighten or relax matching.
- Freelance coverage currently includes Mostaql in the bot runtime. The old Upwork browser automation was not carried over because Upwork is currently serving an anti-bot challenge to lightweight VPS requests.
