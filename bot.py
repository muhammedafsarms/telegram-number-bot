import asyncio
import json
import os
import fcntl
from pathlib import Path

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

STATE_FILE = Path("/data/state.json") if Path("/data").is_dir() else Path("state.json")

state = {
    "chat_id": None,
    "position": 1,
    "multiplier": 1,
    "running": False,
    "paused": False,
    "history": [],
}

sequence_task = None
awaiting_set_position = set()


def save_state():
    temp_file = STATE_FILE.with_name(STATE_FILE.name + ".tmp")

    with open(temp_file, "w") as file:
        json.dump(state, file, indent=2)

    os.replace(temp_file, STATE_FILE)


def load_state():
    global state

    try:
        with open(STATE_FILE, "r") as file:
            state = json.load(file)

        state.setdefault("paused", False)
        state.setdefault("history", [])
        print("📂 State loaded:", state)

    except FileNotFoundError:
        if STATE_FILE != Path("state.json") and Path("state.json").exists():
            with open("state.json", "r") as file:
                state = json.load(file)

            save_state()
            print("📂 Existing state migrated to persistent storage:", state)
        else:
            print("📂 No saved state found. Starting fresh.")


def control_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Start", callback_data="start"),
            InlineKeyboardButton("⏸️ Pause", callback_data="pause"),
        ],
        [
            InlineKeyboardButton("▶️ Resume", callback_data="resume"),
            InlineKeyboardButton("⏹️ Stop", callback_data="stop"),
        ],
        [
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("🎯 Set Position", callback_data="set"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            InlineKeyboardButton("🏆 History", callback_data="history"),
        ],
        [
            InlineKeyboardButton("🔄 Reset", callback_data="reset"),
        ],
    ])


def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("▶️ Start"),
                KeyboardButton("⏸️ Pause"),
            ],
            [
                KeyboardButton("▶️ Resume"),
                KeyboardButton("⏹️ Stop"),
            ],
            [
                KeyboardButton("📊 Status"),
                KeyboardButton("🎯 Set"),
            ],
            [
                KeyboardButton("⚙️ Settings"),
                KeyboardButton("🏆 History"),
            ],
            [
                KeyboardButton("🔄 Reset"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True
    )


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
    state["paused"] = False
    save_state()

    await update.message.reply_text(
        "▶️ Sequence started!\n\n"
        "Sending one number every 2 seconds.",
        reply_markup=control_keyboard()
    )

    sequence_task = asyncio.create_task(
        number_loop(context.application)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 NUMBER LOOP BOT\n\n"
        "▶️ /start - Start or resume sequence\n"
        "⏸️ /pause - Pause sequence\n"
        "▶️ /resume - Resume sequence\n"
        "⏹️ /stop - Stop sequence\n"
        "📊 /status - View progress\n"
        "🎯 /set <1-100> - Set position\n"
        "⚙️ /settings - View bot settings\n"
        "🏆 /history - View completed blocks\n"
        "🔄 /reset - Reset to ×1\n"
        "❓ /help - Show commands"
    )


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state["running"]:
        await update.message.reply_text("⏸️ Sequence is already stopped.")
        return

    state["paused"] = True
    save_state()

    await update.message.reply_text(
        "⏸️ Sequence paused!\n\n"
        f"📍 Position: {state['position']}/100\n"
        f"✖️ Multiplier: ×{state['multiplier']}\n\n"
        "Use /resume to continue.",
        reply_markup=main_keyboard()
    )


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sequence_task

    state["chat_id"] = update.effective_chat.id
    state["running"] = True
    state["paused"] = False
    save_state()

    if sequence_task is None or sequence_task.done():
        sequence_task = asyncio.create_task(
            number_loop(context.application)
        )

    await update.message.reply_text(
        "▶️ Sequence resumed!\n\n"
        f"➡️ Next number: {state['position'] * state['multiplier']}",
        reply_markup=main_keyboard()
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sequence_task

    state["running"] = False
    state["paused"] = False
    save_state()

    if sequence_task is not None and not sequence_task.done():
        sequence_task.cancel()
        try:
            await sequence_task
        except asyncio.CancelledError:
            pass

    sequence_task = None

    await update.message.reply_text("⏹️ Sequence stopped.", reply_markup=main_keyboard())


async def set_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🎯 Usage: /set <position>\n\n"
            "Example: /set 50"
        )
        return

    try:
        position = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Position must be a number from 1 to 100."
        )
        return

    if not 1 <= position <= 100:
        await update.message.reply_text(
            "❌ Position must be between 1 and 100."
        )
        return

    state["chat_id"] = update.effective_chat.id
    state["position"] = position
    state["running"] = False
    state["paused"] = False
    save_state()

    await update.message.reply_text(
        "🎯 Position updated!\n\n"
        f"📍 Position: {position}/100\n"
        f"✖️ Multiplier: ×{state['multiplier']}\n"
        f"➡️ Next number: {position * state['multiplier']}\n\n"
        "Use /start to begin."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    position = state["position"]
    multiplier = state["multiplier"]

    current = position * multiplier
    block_end = 100 * multiplier
    remaining = 100 - position

    status_text = (
        "⏸️ Paused" if state.get("paused", False)
        else "🟢 Running" if state["running"]
        else "🔴 Stopped"
    )

    await update.message.reply_text(
        "📊 NUMBER LOOP BOT\n\n"
        f"{status_text}\n\n"
        f"🔢 Current: {current}\n"
        f"✖️ Multiplier: ×{multiplier}\n"
        f"📦 Block: {position}/100\n"
        f"📈 Progress: {position}%\n"
        f"🎯 Block end: {block_end}\n"
        f"⏳ Remaining: {remaining}\n"
        f"➡️ Next: {current}\n\n"
        "⏱️ Speed: 1 number / 2 seconds",
        reply_markup=control_keyboard()
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_text = (
        "⏸️ Paused" if state.get("paused", False)
        else "🟢 Running" if state["running"]
        else "🔴 Stopped"
    )

    await update.message.reply_text(
        "⚙️ BOT SETTINGS\n\n"
        f"📌 Status: {status_text}\n"
        f"✖️ Multiplier: ×{state['multiplier']}\n"
        "📦 Block size: 100\n"
        "⏱️ Interval: 2 seconds\n"
        f"📍 Position: {state['position']}/100\n"
        f"📈 Progress: {state['position']}%\n"
        f"🏆 Completed blocks: {len(state.get('history', []))}"
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    completed = state.get("history", [])

    if not completed:
        await update.message.reply_text(
            "🏆 BLOCK HISTORY\n\nNo blocks completed yet."
        )
        return

    lines = ["🏆 BLOCK HISTORY", ""]

    for item in completed[-10:]:
        lines.append(
            f"×{item['multiplier']} → {item['value']} ✅"
        )

    await update.message.reply_text("\n".join(lines))


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
        "🔄 Reset complete!\n\n"
        "Next sequence starts from 1.",
        reply_markup=main_keyboard()
    )

async def number_loop(application):
    while True:
        if not state["running"] or state.get("paused", False) or not state["chat_id"]:
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
            save_state()

            if state["position"] > 100:
                completed_multiplier = state["multiplier"]
                completed_value = completed_multiplier * 100
                next_multiplier = completed_multiplier + 1

                state.setdefault("history", []).append({
                    "multiplier": completed_multiplier,
                    "value": completed_value,
                })

                state["history"] = state["history"][-50:]

                await application.bot.send_message(
                    chat_id=state["chat_id"],
                    text=(
                        "🎉 BLOCK COMPLETED!\n\n"
                        f"✖ Multiplier: ×{completed_multiplier}\n"
                        f"🎯 Reached: {completed_value}\n\n"
                        "📈 Progress: 100%\n\n"
                        f"🚀 Next block: ×{next_multiplier}\n"
                        f"➡️ Next number: {next_multiplier}"
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

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sequence_task

    query = update.callback_query
    await query.answer()

    action = query.data

    if action == "start":
        state["chat_id"] = query.message.chat_id
        state["running"] = True
        state["paused"] = False
        save_state()

        if sequence_task is None or sequence_task.done():
            sequence_task = asyncio.create_task(
                number_loop(context.application)
            )

        await query.edit_message_text(
            "▶️ Sequence started!\n\n"
            f"➡️ Next number: {state['position'] * state['multiplier']}",
            reply_markup=control_keyboard()
        )

    elif action == "pause":
        if not state["running"]:
            await query.edit_message_text(
                "⏸️ Sequence is stopped.",
                reply_markup=control_keyboard()
            )
            return

        state["paused"] = True
        save_state()

        await query.edit_message_text(
            "⏸️ Sequence paused!\n\n"
            f"📍 Position: {state['position']}/100\n"
            f"✖️ Multiplier: ×{state['multiplier']}\n\n"
            "Press ▶️ Resume to continue.",
            reply_markup=control_keyboard()
        )

    elif action == "resume":
        state["chat_id"] = query.message.chat_id
        state["running"] = True
        state["paused"] = False
        save_state()

        if sequence_task is None or sequence_task.done():
            sequence_task = asyncio.create_task(
                number_loop(context.application)
            )

        await query.edit_message_text(
            "▶️ Sequence resumed!\n\n"
            f"➡️ Next number: {state['position'] * state['multiplier']}",
            reply_markup=control_keyboard()
        )

    elif action == "stop":
        state["running"] = False
        state["paused"] = False
        save_state()

        if sequence_task is not None and not sequence_task.done():
            sequence_task.cancel()
            try:
                await sequence_task
            except asyncio.CancelledError:
                pass

        sequence_task = None

        await query.edit_message_text(
            "⏹️ Sequence stopped.",
            reply_markup=control_keyboard()
        )

    elif action == "status":
        position = state["position"]
        multiplier = state["multiplier"]
        current = position * multiplier
        remaining = 100 - position

        status_text = (
            "⏸️ Paused" if state.get("paused", False)
            else "🟢 Running" if state["running"]
            else "🔴 Stopped"
        )

        await query.edit_message_text(
            "📊 NUMBER LOOP BOT\n\n"
            f"{status_text}\n\n"
            f"🔢 Current: {current}\n"
            f"✖️ Multiplier: ×{multiplier}\n"
            f"📦 Block: {position}/100\n"
            f"📈 Progress: {position}%\n"
            f"⏳ Remaining: {remaining}\n"
            f"➡️ Next: {current}",
            reply_markup=control_keyboard()
        )

    elif action == "set":
        await query.answer(
            "Use /set 50 (replace 50 with your position)",
            show_alert=True
        )

    elif action == "settings":
        await query.edit_message_text(
            "⚙️ BOT SETTINGS\n\n"
            f"✖️ Multiplier: ×{state['multiplier']}\n"
            "📦 Block size: 100\n"
            "⏱️ Interval: 2 seconds\n"
            f"📍 Position: {state['position']}/100\n"
            f"📈 Progress: {state['position']}%\n"
            f"🏆 Completed blocks: {len(state.get('history', []))}",
            reply_markup=control_keyboard()
        )

    elif action == "history":
        completed = state.get("history", [])

        if not completed:
            message = "🏆 BLOCK HISTORY\n\nNo blocks completed yet."
        else:
            lines = ["🏆 BLOCK HISTORY", ""]
            for item in completed[-10:]:
                lines.append(
                    f"×{item['multiplier']} → {item['value']} ✅"
                )
            message = "\n".join(lines)

        await query.edit_message_text(
            message,
            reply_markup=control_keyboard()
        )

    elif action == "reset":
        if sequence_task is not None and not sequence_task.done():
            sequence_task.cancel()
            try:
                await sequence_task
            except asyncio.CancelledError:
                pass

        sequence_task = None

        state["chat_id"] = query.message.chat_id
        state["position"] = 1
        state["multiplier"] = 1
        state["running"] = False
        state["paused"] = False
        state["history"] = []
        save_state()

        await query.edit_message_text(
            "🔄 Reset complete!\n\n"
            "Next sequence starts from 1.",
            reply_markup=control_keyboard()
        )


async def keyboard_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sequence_task

    if not update.message or not update.message.text:
        return

    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "▶️ Start":
        state["chat_id"] = chat_id
        state["running"] = True
        state["paused"] = False
        save_state()

        if sequence_task is None or sequence_task.done():
            sequence_task = asyncio.create_task(
                number_loop(context.application)
            )

        await update.message.reply_text(
            "▶️ Sequence started!\\n\\n"
            f"➡️ Next number: {state['position'] * state['multiplier']}",
            reply_markup=main_keyboard()
        )

    elif text == "⏸️ Pause":
        state["paused"] = True
        save_state()
        await update.message.reply_text(
            "⏸️ Sequence paused.",
            reply_markup=main_keyboard()
        )

    elif text == "▶️ Resume":
        state["chat_id"] = chat_id
        state["running"] = True
        state["paused"] = False
        save_state()

        if sequence_task is None or sequence_task.done():
            sequence_task = asyncio.create_task(
                number_loop(context.application)
            )

        await update.message.reply_text(
            "▶️ Sequence resumed!",
            reply_markup=main_keyboard()
        )

    elif text == "⏹️ Stop":
        state["running"] = False
        state["paused"] = False
        save_state()

        if sequence_task is not None and not sequence_task.done():
            sequence_task.cancel()
            try:
                await sequence_task
            except asyncio.CancelledError:
                pass

        sequence_task = None

        await update.message.reply_text(
            "⏹️ Sequence stopped.",
            reply_markup=main_keyboard()
        )

    elif text == "📊 Status":
        position = state["position"]
        multiplier = state["multiplier"]
        current = position * multiplier
        remaining = 100 - position

        status_text = (
            "⏸️ Paused" if state.get("paused", False)
            else "🟢 Running" if state["running"]
            else "🔴 Stopped"
        )

        await update.message.reply_text(
            "📊 NUMBER LOOP BOT\\n\\n"
            f"{status_text}\\n\\n"
            f"🔢 Current: {current}\\n"
            f"✖️ Multiplier: ×{multiplier}\\n"
            f"📦 Block: {position}/100\\n"
            f"📈 Progress: {position}%\\n"
            f"⏳ Remaining: {remaining}\\n"
            f"➡️ Next: {current}",
            reply_markup=main_keyboard()
        )

    elif text == "🎯 Set":
        awaiting_set_position.add(chat_id)

        await update.message.reply_text(
            "🎯 Enter the position you want to set.\\n\\n"
            "Choose a number from 1 to 100.\\n\\n"
            "Example: 50"
        )

    elif chat_id in awaiting_set_position:
        try:
            position = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ Please enter a number from 1 to 100."
            )
            return

        if not 1 <= position <= 100:
            await update.message.reply_text(
                "❌ Position must be between 1 and 100."
            )
            return

        awaiting_set_position.discard(chat_id)

        state["chat_id"] = chat_id
        state["position"] = position
        state["running"] = False
        state["paused"] = False
        save_state()

        await update.message.reply_text(
            "🎯 Position updated!\\n\\n"
            f"📍 Position: {position}/100\\n"
            f"✖️ Multiplier: ×{state['multiplier']}\\n"
            f"➡️ Next number: {position * state['multiplier']}",
            reply_markup=main_keyboard()
        )

    elif text == "⚙️ Settings":
        await update.message.reply_text(
            "⚙️ BOT SETTINGS\\n\\n"
            f"✖️ Multiplier: ×{state['multiplier']}\\n"
            "📦 Block size: 100\\n"
            "⏱️ Interval: 2 seconds\\n"
            f"📍 Position: {state['position']}/100\\n"
            f"📈 Progress: {state['position']}%\\n"
            f"🏆 Completed blocks: {len(state.get('history', []))}",
            reply_markup=main_keyboard()
        )

    elif text == "🏆 History":
        completed = state.get("history", [])

        if not completed:
            message = "🏆 BLOCK HISTORY\\n\\nNo blocks completed yet."
        else:
            lines = ["🏆 BLOCK HISTORY", ""]
            for item in completed[-10:]:
                lines.append(
                    f"×{item['multiplier']} → {item['value']} ✅"
                )
            message = "\\n".join(lines)

        await update.message.reply_text(
            message,
            reply_markup=main_keyboard()
        )

    elif text == "🔄 Reset":
        if sequence_task is not None and not sequence_task.done():
            sequence_task.cancel()
            try:
                await sequence_task
            except asyncio.CancelledError:
                pass

        sequence_task = None

        state["chat_id"] = chat_id
        state["position"] = 1
        state["multiplier"] = 1
        state["running"] = False
        state["paused"] = False
        state["history"] = []
        save_state()

        await update.message.reply_text(
            "🔄 Reset complete!\\n\\n"
            "Next sequence starts from 1.",
            reply_markup=main_keyboard()
        )



async def post_init(application):
    global sequence_task

    load_state()

    # Automatically resume the sequence after a restart
    if state["running"] and state["chat_id"] and not state.get("paused", False):
        print("🔄 Auto-resuming number sequence...")
        sequence_task = asyncio.create_task(
            number_loop(application)
        )

def main():
    # Prevent multiple bot processes from running simultaneously.
    lock_file = open("bot.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("⚠️ Another bot instance is already running. Exiting.")
        return


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
        CommandHandler("pause", pause)
    )

    application.add_handler(
        CommandHandler("resume", resume)
    )

    application.add_handler(
        CommandHandler("stop", stop)
    )

    application.add_handler(
        CommandHandler("set", set_position)
    )

    application.add_handler(
        CommandHandler("status", status)
    )

    application.add_handler(
        CommandHandler("settings", settings)
    )

    application.add_handler(
        CommandHandler("history", history)
    )

    application.add_handler(
        CommandHandler("reset", reset)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, keyboard_message)
    )

    application.add_handler(
        CallbackQueryHandler(button_callback)
    )

    application.run_polling()


if __name__ == "__main__":
    main()
