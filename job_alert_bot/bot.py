from __future__ import annotations

import asyncio
import html
import logging
from datetime import timedelta

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from .config import AppConfig
from .models import JobOpportunity
from .storage import Storage
from .tracker import JobTracker


LOGGER = logging.getLogger(__name__)


def chunked_messages(header: str, jobs: list[JobOpportunity], max_length: int = 3500) -> list[str]:
    blocks: list[str] = []
    current = header

    for index, job in enumerate(jobs, start=1):
        meta = " | ".join(part for part in [job.source.upper(), job.job_type or "unspecified", job.location or "remote"] if part)
        reasons = "; ".join(html.escape(reason) for reason in job.reasons[:3])
        block = (
            f"\n\n<b>{index}. {html.escape(job.title)}</b>\n"
            f"{html.escape(job.company)}\n"
            f"<i>{html.escape(meta)}</i>\n"
            f"Score: <b>{job.score}</b>\n"
            f"Why: {reasons}\n"
            f"<a href=\"{html.escape(job.url, quote=True)}\">Apply here</a>"
        )
        if len(current) + len(block) > max_length and current != header:
            blocks.append(current)
            current = header + block
        else:
            current += block

    blocks.append(current)
    return blocks


class TelegramJobAlertBot:
    def __init__(self, config: AppConfig, storage: Storage, tracker: JobTracker) -> None:
        self.config = config
        self.storage = storage
        self.tracker = tracker
        self.scan_lock = asyncio.Lock()
        self.application: Application | None = None

    def build_application(self) -> Application:
        application = ApplicationBuilder().token(self.config.telegram_bot_token).post_init(self._post_init).build()
        self.application = application
        application.bot_data["service"] = self

        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("status", self.status))
        application.add_handler(CommandHandler("run_now", self.run_now))
        application.add_handler(CommandHandler("profile", self.profile))
        application.add_handler(CommandHandler("unsubscribe", self.unsubscribe))
        return application

    async def _post_init(self, application: Application) -> None:
        await self.storage.init()
        commands = [
            BotCommand("start", "Subscribe this chat to job alerts"),
            BotCommand("status", "Show tracker status"),
            BotCommand("run_now", "Fetch a fresh job digest now"),
            BotCommand("profile", "Show the active job matching profile"),
            BotCommand("unsubscribe", "Stop alerts for this chat"),
            BotCommand("help", "Show help"),
        ]
        await application.bot.set_my_commands(commands)
        if application.job_queue is None:
            raise RuntimeError("JobQueue is not available. Install python-telegram-bot with the job-queue extra.")

        application.job_queue.run_repeating(
            self._scheduled_scan,
            interval=timedelta(minutes=self.config.profile.poll_interval_minutes),
            first=15,
            name="scheduled-job-scan",
        )

    def _is_allowed(self, user_id: int) -> bool:
        return not self.config.allowed_user_ids or user_id in self.config.allowed_user_ids

    async def _guard(self, update: Update) -> bool:
        user = update.effective_user
        if user is None or not self._is_allowed(user.id):
            if update.effective_message:
                await update.effective_message.reply_text("This bot is restricted. Add your Telegram user id to ALLOWED_USER_IDS first.")
            return False
        return True

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return

        user = update.effective_user
        chat = update.effective_chat
        if user is None or chat is None or update.effective_message is None:
            return

        await self.storage.subscribe(chat.id, user.id, user.username, user.first_name)
        await update.effective_message.reply_text(
            "Alerts are enabled for this chat.\n"
            "The scheduled scan runs every "
            f"{self.config.profile.poll_interval_minutes} minutes.\n"
            "Use /run_now for an immediate digest."
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        await update.effective_message.reply_text(
            "/start - subscribe this chat\n"
            "/status - tracker status and last scan\n"
            "/run_now - fetch a fresh digest right now\n"
            "/profile - show current matching filters\n"
            "/unsubscribe - stop alerts"
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update) or update.effective_message is None:
            return
        latest = await self.storage.latest_scan()
        subscribers = await self.storage.active_subscriber_count()
        if latest is None:
            text = "No scans have completed yet."
        else:
            text = (
                f"Last scan: {latest.completed_at}\n"
                f"Matched jobs: {latest.matched_jobs}\n"
                f"New jobs: {latest.new_jobs}\n"
                f"Warmup mode: {'yes' if latest.warmup_mode else 'no'}\n"
                f"Subscribers: {subscribers}"
            )
        await update.effective_message.reply_text(text)

    async def profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update) or update.effective_message is None:
            return
        profile = self.config.profile
        await update.effective_message.reply_text(
            "Current profile\n"
            f"Roles: {', '.join(profile.title_keywords[:8])}\n"
            f"Core skills: {', '.join(profile.skill_keywords[:10])}\n"
            f"Preferred job types: {', '.join(profile.preferred_job_types)}\n"
            f"Minimum score: {profile.minimum_score}"
        )

    async def unsubscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        chat = update.effective_chat
        if chat is None or update.effective_message is None:
            return
        await self.storage.unsubscribe(chat.id)
        await update.effective_message.reply_text("Alerts are disabled for this chat.")

    async def run_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update) or update.effective_message is None:
            return

        await update.effective_message.reply_text("Checking current matches now...")
        async with self.scan_lock:
            jobs = await self.tracker.preview()

        if not jobs:
            await update.effective_message.reply_text("No strong matches found right now.")
            return

        header = f"<b>Live job digest</b>\nTop {len(jobs)} current matches for your profile:"
        for message in chunked_messages(header, jobs):
            await update.effective_message.reply_text(message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    async def _scheduled_scan(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.storage.active_chat_ids():
            LOGGER.info("No active subscribers. Skipping scheduled scan.")
            return

        async with self.scan_lock:
            summary = await self.tracker.scan_for_alerts()

        if summary.warmup_mode:
            await self._broadcast(
                "Tracker warm-up completed.\n"
                "Current matches were cached so future alerts contain only new opportunities.\n"
                "Use /run_now any time for a live digest."
            )
            return

        if not summary.new_jobs:
            LOGGER.info("Scheduled scan completed with no new matches.")
            return

        jobs = summary.new_jobs
        header = f"<b>{len(summary.new_jobs)} new job match(es)</b>\nBest opportunities found in the latest scan:"
        for message in chunked_messages(header, jobs):
            await self._broadcast(message)

    async def _broadcast(self, text: str) -> None:
        chat_ids = await self.storage.active_chat_ids()
        for chat_id in chat_ids:
            try:
                await asyncio.sleep(0.1)
                await self._send_message(chat_id, text)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to send message to chat %s: %s", chat_id, exc)

    async def _send_message(self, chat_id: int, text: str) -> None:
        if self.application is None:
            raise RuntimeError("Application is not initialized.")
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
