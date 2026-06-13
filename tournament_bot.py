"""
🎮 Tournament Randomizer Bot
Render.com uchun tayyor

O'rnatish:
  pip install python-telegram-bot

Ishlatish:
  BOT_TOKEN=<tokeningiz> python tournament_bot.py

Render deploy:
  - Start command: python tournament_bot.py
  - Environment variable: BOT_TOKEN
"""

import os
import re
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ─── Har bir chat uchun ma'lumotlar ────────────────────────────────────────────
# {chat_id: {"players": [...], "rounds": [[...]], "current_round": 0,
#            "round_winners": [...]}}
sessions: dict = {}


# ─── Yordamchi funksiyalar ──────────────────────────────────────────────────────

def get_session(chat_id: int) -> dict:
    if chat_id not in sessions:
        sessions[chat_id] = {
            "players": [],
            "rounds": [],
            "current_round": 0,
            "round_winners": [],   # FIX #3: har tur g'oliblari bir marta saqlanadi
        }
    return sessions[chat_id]


def escape_md(text: str) -> str:
    """FIX #1: Markdown v1 maxsus belgilaridan himoya."""
    # Telegram Markdown v1 da: * _ ` [ ] ( ) ~ > # + - = | { } . !
    return re.sub(r'([*_`\[\]()~>#+=|{}.!\\-])', r'\\\1', text)


def make_pairs(players: list) -> list:
    """O'yinchilarni random juftlarga ajratadi. Toq bo'lsa oxirgisi bye oladi."""
    shuffled = players[:]
    random.shuffle(shuffled)
    pairs = []
    for i in range(0, len(shuffled) - 1, 2):
        pairs.append((shuffled[i], shuffled[i + 1]))
    if len(shuffled) % 2 == 1:
        pairs.append((shuffled[-1], "bye"))
    return pairs


def format_bracket(pairs: list, round_num: int) -> str:
    lines = [f"🏆 *{round_num}\\-tur juftliklari:*\n"]
    for i, (a, b) in enumerate(pairs, 1):
        ea, eb = escape_md(a), escape_md(b)
        if b == "bye":
            lines.append(f"  {i}\\. 🎯 *{ea}* — \\(bye, o'tib ketadi\\)")
        else:
            lines.append(f"  {i}\\. ⚔️  {ea}  🆚  {eb}")
    return "\n".join(lines)


def format_players(players: list) -> str:
    if not players:
        return "_(hali hech kim yo'q)_"
    return "\n".join(f"  {i+1}\\. {escape_md(p)}" for i, p in enumerate(players))


# ─── Command handlers ──────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Tournament Randomizer Botga xush kelibsiz\\!*\n\n"
        "Bu bot o'yinchilarni random juftlarga ajratib, turnir o'tkazishga yordam beradi\\.\n\n"
        "📋 *Buyruqlar:*\n"
        "  /newgame — yangi o'yin boshlash\n"
        "  /add `Ism` — o'yinchi qo'shish\n"
        "  /remove `Ism` — o'yinchini o'chirish\n"
        "  /players — o'yinchilar ro'yxati\n"
        "  /shuffle — random juftlash & tur boshlash\n"
        "  /nextround — keyingi turni boshlash\n"
        "  /status — joriy holat\n"
        "  /clear — hamma narsani tozalash\n"
        "  /help — yordam"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, ctx)


async def newgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    sessions[chat_id] = {
        "players": [],
        "rounds": [],
        "current_round": 0,
        "round_winners": [],
    }
    await update.message.reply_text(
        "✅ Yangi o'yin boshlandi\\!\n\n"
        "O'yinchilarni qo'shish uchun:\n"
        "  `/add Sardor`\n"
        "  `/add Jasur`\n"
        "\\.\\.\\. va hokazo\n\n"
        "Keyin `/shuffle` buyrug'ini bering\\.",
        parse_mode="MarkdownV2",
    )


async def add_player(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not ctx.args:
        await update.message.reply_text(
            "❗ Ism kiriting: `/add Sardor`", parse_mode="MarkdownV2"
        )
        return

    name = " ".join(ctx.args).strip()

    # FIX #2: bo'sh yoki faqat bo'sh joy tekshiruvi
    if not name:
        await update.message.reply_text("❗ Ism bo'sh bo'lmasin\\.", parse_mode="MarkdownV2")
        return

    if len(name) > 50:
        await update.message.reply_text("❗ Ism juda uzun \\(max 50 ta belgi\\)\\.", parse_mode="MarkdownV2")
        return

    if name.lower() in [p.lower() for p in session["players"]]:
        await update.message.reply_text(
            f"⚠️ *{escape_md(name)}* allaqachon ro'yxatda\\!", parse_mode="MarkdownV2"
        )
        return

    if len(session["players"]) >= 64:
        await update.message.reply_text("❗ Maksimal 64 ta o'yinchi\\.", parse_mode="MarkdownV2")
        return

    session["players"].append(name)
    count = len(session["players"])
    await update.message.reply_text(
        f"✅ *{escape_md(name)}* qo'shildi\\! Jami: {count} ta o'yinchi\\.\n"
        f"Tayyor bo'lgach `/shuffle` bering\\.",
        parse_mode="MarkdownV2",
    )


async def remove_player(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not ctx.args:
        await update.message.reply_text(
            "❗ Ism kiriting: `/remove Sardor`", parse_mode="MarkdownV2"
        )
        return

    name = " ".join(ctx.args).strip()
    matches = [p for p in session["players"] if p.lower() == name.lower()]
    if not matches:
        await update.message.reply_text(
            f"❗ *{escape_md(name)}* topilmadi\\.", parse_mode="MarkdownV2"
        )
        return

    session["players"].remove(matches[0])
    await update.message.reply_text(
        f"🗑 *{escape_md(matches[0])}* o'chirildi\\. Qoldi: {len(session['players'])} ta\\.",
        parse_mode="MarkdownV2",
    )


async def list_players(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    players_text = format_players(session["players"])
    await update.message.reply_text(
        f"👥 *O'yinchilar ro'yxati \\({len(session['players'])} ta\\):*\n{players_text}",
        parse_mode="MarkdownV2",
    )


async def shuffle(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if len(session["players"]) < 2:
        await update.message.reply_text(
            "❗ Kamida 2 ta o'yinchi kerak\\!\n`/add Ism` buyrug'i bilan qo'shing\\.",
            parse_mode="MarkdownV2",
        )
        return

    pairs = make_pairs(session["players"])
    session["rounds"] = [pairs]
    session["current_round"] = 1
    session["round_winners"] = []   # FIX #3: reset

    bracket_text = format_bracket(pairs, 1)
    keyboard = [[InlineKeyboardButton("🔀 Qayta aralashtir", callback_data="reshuffle")]]
    markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(bracket_text, parse_mode="MarkdownV2", reply_markup=markup)


async def next_round(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session["rounds"]:
        await update.message.reply_text(
            "❗ Avval `/shuffle` buyrug'ini bering\\.", parse_mode="MarkdownV2"
        )
        return

    # FIX #3: g'oliblar allaqachon tanlangan bo'lsa qayta tanlamasin
    if session["round_winners"]:
        winners = session["round_winners"]
        await update.message.reply_text(
            "⚠️ Bu tur g'oliblari allaqachon tanlangan\\!\n"
            "Keyingi turga o'tish uchun `/nextround` ni yana bir marta bosing yoki "
            "yangi o'yin uchun `/newgame`\\.",
            parse_mode="MarkdownV2",
        )
        return

    current_pairs = session["rounds"][-1]

    # FIX #4: bo'sh pairs holati
    if not current_pairs:
        await update.message.reply_text(
            "❗ Joriy turda juftliklar yo'q\\. `/newgame` bilan qayta boshlang\\.",
            parse_mode="MarkdownV2",
        )
        return

    winners = []
    for a, b in current_pairs:
        if b == "bye":
            winners.append(a)
        else:
            winners.append(random.choice([a, b]))

    # FIX #4: winners bo'sh bo'lsa himoya
    if not winners:
        await update.message.reply_text(
            "❗ G'oliblar aniqlanmadi\\. `/newgame` bilan qayta boshlang\\.",
            parse_mode="MarkdownV2",
        )
        return

    if len(winners) < 2:
        winner_name = winners[0]
        # Turnir tugadi - sessiyani tozalaymiz
        session["rounds"] = []
        session["current_round"] = 0
        session["round_winners"] = []
        await update.message.reply_text(
            f"🏆 *Turnir tugadi\\!*\n\n🥇 G'olib: *{escape_md(winner_name)}* 🎉\n\n"
            f"Yangi turnir uchun `/newgame` bering\\.",
            parse_mode="MarkdownV2",
        )
        return

    # FIX #3: g'oliblarni saqlaymiz (qayta /nextround bosishdan himoya)
    session["round_winners"] = winners

    new_pairs = make_pairs(winners)
    session["rounds"].append(new_pairs)
    session["current_round"] += 1
    session["round_winners"] = []   # yangi tur uchun tozalash

    winners_text = "\n".join(f"  ✅ {escape_md(w)}" for w in winners)
    bracket_text = format_bracket(new_pairs, session["current_round"])

    await update.message.reply_text(
        f"🎯 *{session['current_round'] - 1}\\-tur g'oliblari \\(random tanlandi\\):*\n"
        f"{winners_text}\n\n{bracket_text}",
        parse_mode="MarkdownV2",
    )


async def clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    sessions[chat_id] = {
        "players": [],
        "rounds": [],
        "current_round": 0,
        "round_winners": [],
    }
    await update.message.reply_text(
        "🗑 Hamma narsa tozalandi\\. Yangi o'yin uchun `/newgame` bering\\.",
        parse_mode="MarkdownV2",
    )


async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    lines = ["📊 *Joriy holat:*\n"]
    lines.append(f"👥 O'yinchilar: {len(session['players'])} ta")
    lines.append(f"🔄 Tugallangan turlar: {session['current_round']}")

    if session["rounds"]:
        last = session["rounds"][-1]
        active = [(a, b) for a, b in last if b != "bye"]
        lines.append(f"⚔️  Joriy turdagi juftliklar: {len(active)} ta")

    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


# ─── Inline button handler ─────────────────────────────────────────────────────

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    session = get_session(chat_id)

    if query.data == "reshuffle":
        if len(session["players"]) < 2:
            await query.edit_message_text("❗ O'yinchilar yo'q\\.", parse_mode="MarkdownV2")
            return
        pairs = make_pairs(session["players"])
        session["rounds"] = [pairs]
        session["current_round"] = 1
        session["round_winners"] = []
        bracket_text = format_bracket(pairs, 1)
        keyboard = [[InlineKeyboardButton("🔀 Qayta aralashtir", callback_data="reshuffle")]]
        markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(bracket_text, parse_mode="MarkdownV2", reply_markup=markup)


# ─── Noma'lum buyruq ────────────────────────────────────────────────────────────

async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "❓ Noma'lum buyruq\\. Yordam uchun /help bering\\.",
        parse_mode="MarkdownV2",
    )


# ─── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError(
            "❌ BOT_TOKEN topilmadi!\n"
            "Render.com → Environment → BOT_TOKEN qo'shing.\n"
            "Yoki: export BOT_TOKEN=<tokeningiz>"
        )

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("newgame", newgame))
    app.add_handler(CommandHandler("add", add_player))
    app.add_handler(CommandHandler("remove", remove_player))
    app.add_handler(CommandHandler("players", list_players))
    app.add_handler(CommandHandler("shuffle", shuffle))
    app.add_handler(CommandHandler("nextround", next_round))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("✅ Bot ishga tushdi! Ctrl+C bilan to'xtatish mumkin.")

    async def run():
        async with app:
            await app.initialize()
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            await app.start()
            await asyncio.Event().wait()

    asyncio.run(run())


if __name__ == "__main__":
    main()
