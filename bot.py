import asyncio
import json
import os
from pathlib import Path

from telegram import Update
from telegram.error import RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

STATE_FILE = Path("state.json")

state = {
    "chat_id": None,
    "position": 1,
    "multiplier": 1,
    "running": False,
}

sequence_task = None


def save_state():
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_state():
    global state

    if STATE_FILE.exists():
        try:
            saved = json.loads(STATE_FILE.read_text())
            state.update(saved)
        except Exception:
            pass

    # Preserve the saved running state for automatic resume


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sequence_task

    # Cancel any existing sequence before starting a new one
    if sequence_task is not None and not sequence_task.done():
        sequence_task.cancel()
        try:
            await sequence_task
        except asyncio.CancelledError:
            pass

    state["chat_id"] = update.effective_chat.id
    state["running"] = True
    save_state()

    await update.message.reply_text(
        "▶️ Sequence started!\\n\\n"
        "Sending one number every 2 seconds."
    )

    sequence_task = asyncio.create_task(
        number_loop(context.application)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 NUMBER LOOP BOT\\n\\n"
        "▶️ /start - Start sequence\\n"
        "⏹️ /stop - Stop sequence\\n"
        "📊 /status - View progress\\n"
        "🔄 /reset - Reset to ×1\\n"
        "❓ /help - Show commands"
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sequence_task

    state["running"] = False
    save_state()

    if sequence_task is not None and not sequence_task.done():
        sequence_task.cancel()
        sequence_task = None

    await update.message.reply_text("⏸️ Sequence stopped.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    position = state["position"]
    multiplier = state["multiplier"]

    current = position * multiplier
    block_end = 100 * multiplier
    remaining = 100 - position

    status_text = "🟢 Running" if state["running"] else "🔴 Stopped"

    await update.message.reply_text(
        "📊 NUMBER BOT\n\n"
        f"{status_text}\n\n"
        f"🔢 Current: {current}\n"
        f"✖️ Multiplier: ×{multiplier}\n"
        f"📦 Block: {position}/100\n"
        f"🎯 Block end: {block_end}\n"
        f"⏳ Remaining: {remaining}\n"
        f"➡️ Next: {(position + 1) * multiplier}"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sequence_task

    # Cancel the existing sequence task
    if sequence_task is not None and not sequence_task.done():
        sequence_task.cancel()
        try:
            await sequence_task
        except asyncio.CancelledError:
            pass

    sequence_task = None

    state["chat_id"] = update.effective_chat.id
    state["position"] = 1
    state["multiplier"] = 1
    state["running"] = False

    save_state()

    await update.message.reply_text(
        "🔄 Reset complete!\\n\\n"
        "Next sequence starts from 1."
    )

async def number_loop(application):
    while True:
        if not state["running"] or not state["chat_id"]:
            await asyncio.sleep(1)
            continue

        try:
            position = state["position"]
            multiplier = state["multiplier"]

            number = position * multiplier

            await application.bot.send_message(
                chat_id=state["chat_id"],
                text=str(number)
            )

            state["position"] += 1

            if state["position"] > 100:
                completed_multiplier = state["multiplier"]
                completed_value = completed_multiplier * 100
                next_multiplier = completed_multiplier + 1

                await application.bot.send_message(
                    chat_id=state["chat_id"],
                    text=(
                        "🎉 BLOCK COMPLETED!\\n\\n"
                        f"✖ Multiplier: ×{completed_multiplier}\\n"
                        f"🎯 Reached: {completed_value}\\n\\n"
                        f"🚀 Next block: ×{next_multiplier}"
                    )
                )

                state["position"] = 1
                state["multiplier"] += 1
                save_state()

            await asyncio.sleep(2.0)

        except RetryAfter as error:
            print(f"⚠️ Telegram flood control. Waiting {error.retry_after + 1} seconds...")
            await asyncio.sleep(error.retry_after + 1)

        except asyncio.CancelledError:
            print("⏹️ Number loop cancelled")
            raise

        except Exception as error:
            print("Sending error:", error)
            await asyncio.sleep(5)

async def post_init(application):
    global sequence_task

    load_state()

    # Automatically resume the sequence after a restart
    if state["running"] and state["chat_id"]:
        print("🔄 Auto-resuming number sequence...")
        sequence_task = asyncio.create_task(
            number_loop(application)
        )

def main():

    application = (
        Application.builder()
        .token(os.environ["BOT_TOKEN"])
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("stop", stop)
    )

    application.add_handler(
        CommandHandler("status", status)
    )

    application.add_handler(
        CommandHandler("reset", reset)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.run_polling()


if __name__ == "__main__":
    main()
