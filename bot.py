import asyncio
import json
import os
from pathlib import Path

from telegram import Update
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

    # Don't automatically start after a restart
    state["running"] = False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sequence_task

    if sequence_task is not None and not sequence_task.done():
        await update.message.reply_text(
            "⚠️ Sequence is already running!\n\n"
            "Use /stop first if you want to restart it."
        )
        return

    state["chat_id"] = update.effective_chat.id
    state["running"] = True
    save_state()

    await update.message.reply_text(
        "▶️ Sequence started!\n\n"
        "Sending one number every second."
    )

    sequence_task = asyncio.create_task(
        number_loop(context.application)
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state["running"] = False
    save_state()

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
    state["chat_id"] = update.effective_chat.id
    state["position"] = 1
    state["multiplier"] = 1
    state["running"] = False

    save_state()

    await update.message.reply_text(
        "🔄 Reset complete!\n\n"
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
                        "🎉 BLOCK COMPLETED!\n\n"
                        f"✖️ Multiplier: ×{completed_multiplier}\n"
                        f"🎯 Reached: {completed_value}\n\n"
                        f"🚀 Next block: ×{next_multiplier}"
                    )
                )

                state["position"] = 1
                state["multiplier"] += 1

            save_state()

            # ~1 message per second
            await asyncio.sleep(1.05)

        except Exception as error:
            print("Sending error:", error)
            await asyncio.sleep(5)


async def post_init(application):
    load_state()


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

    application.run_polling()


if __name__ == "__main__":
    main()
