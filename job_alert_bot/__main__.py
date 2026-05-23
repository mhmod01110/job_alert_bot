from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .bot import TelegramJobAlertBot
from .config import load_config
from .storage import Storage
from .tracker import JobTracker


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def configure_stdout() -> None:
    stream = getattr(sys, "stdout", None)
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


async def preview_matches(base_dir: Path) -> None:
    config = load_config(base_dir)
    configure_logging(config.log_level)
    tracker = JobTracker(config=config, storage=Storage(config.database_path))
    jobs = await tracker.preview()
    if not jobs:
        print("No strong matches found.")
        return
    for index, job in enumerate(jobs, start=1):
        print(f"{index}. {job.title} | {job.company} | {job.source} | score={job.score}")
        print(f"   {job.url}")
        print(f"   why: {', '.join(job.reasons)}")


def main() -> None:
    configure_stdout()
    parser = argparse.ArgumentParser(description="Telegram job alert bot")
    parser.add_argument("--preview", action="store_true", help="Fetch current matches and print them without using Telegram")
    args = parser.parse_args()

    base_dir = Path.cwd()
    if args.preview:
        asyncio.run(preview_matches(base_dir))
        return

    config = load_config(base_dir)
    configure_logging(config.log_level)

    if not config.telegram_bot_token or config.telegram_bot_token == "replace-with-your-bot-token":
        raise SystemExit("Please set TELEGRAM_BOT_TOKEN in .env before running the bot.")

    storage = Storage(config.database_path)
    tracker = JobTracker(config=config, storage=storage)
    bot = TelegramJobAlertBot(config=config, storage=storage, tracker=tracker)
    application = bot.build_application()
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
