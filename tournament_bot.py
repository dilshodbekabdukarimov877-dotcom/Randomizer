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
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram.error import Conflict
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
            "round_winners": [],
            "stats": {},  # {ism: {"wins": 0, "losses": 0, "titles": 0}}
        }
    if "stats" not in sessions[chat_id]:
        sessions[chat_id]["stats"] = {}
    return sessions[chat_id]


def update_stats(session: dict, winner: str, loser: str = None) -> None:
    """G'olib va yutqazganga statistika yozadi."""
    stats = session["stats"]
    if winner not in stats:
        stats[winner] = {"wins": 0, "losses": 0, "titles": 0}
    stats[winner]["wins"] += 1
    if loser and loser != "bye":
        if loser not in stats:
            stats[loser] = {"wins": 0, "losses": 0, "titles": 0}
        stats[loser]["losses"] += 1


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
        "  /stats — statistika (g'alabalar, mag'lubiyatlar)\n"
        "  /resetstats — statistikani tozalash\n"
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


async def ask_next_winner(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Navbatdagi juftlik uchun g'olib so'raydi."""
    session = get_session(chat_id)
    current_pairs = session["rounds"][-1]
    confirmed = session["round_winners"]       # shu turda tasdiqlangan g'oliblar
    pending_pairs = [                          # hali hal qilinmagan juftliklar
        (a, b) for a, b in current_pairs
        if a not in confirmed and b not in confirmed and b != "bye"
    ]

    # bye o'yinchilarni avtomatik qo'shish
    for a, b in current_pairs:
        if b == "bye" and a not in confirmed:
            confirmed.append(a)

    if not pending_pairs:
        # Barcha juftliklar hal bo'ldi — keyingi turni boshlash
        winners = confirmed[:]
        if len(winners) < 2:
            winner_name = winners[0] if winners else "???"
            session["rounds"] = []
            session["current_round"] = 0
            session["round_winners"] = []

            # Chempionlik unvonini statistikaga qo'shish
            stats = session["stats"]
            if winner_name not in stats:
                stats[winner_name] = {"wins": 0, "losses": 0, "titles": 0}
            stats[winner_name]["titles"] += 1

            # 🎊 WOW — turnir g'olibi tantanali e'lon
            wow_lines = [
                "🎊🎊🎊🎊🎊🎊🎊🎊🎊🎊",
                "",
                "⠀🏆 *TURNIR YAKUNLANDI\\!* 🏆",
                "",
                f"👑 *CHEMPION:*",
                f"🌟 *{escape_md(winner_name)}* 🌟",
                "",
                "🥇🎖 Tabriklaymiz\\! 🎖🥇",
                "",
                "🎊🎊🎊🎊🎊🎊🎊🎊🎊🎊",
                "",
                "_Yangi turnir uchun_ `/newgame`",
            ]
            await ctx.bot.send_message(
                chat_id,
                "\n".join(wow_lines),
                parse_mode="MarkdownV2",
            )
            return

        new_pairs = make_pairs(winners)
        session["rounds"].append(new_pairs)
        session["current_round"] += 1
        session["round_winners"] = []

        winners_text = "\n".join(f"  🏅 {escape_md(w)}" for w in winners)
        bracket_text = format_bracket(new_pairs, session["current_round"])

        # 🎯 Tur yakunlandi — keyingi tur e'loni
        await ctx.bot.send_message(
            chat_id,
            f"🔥 *{session['current_round'] - 1}\\-tur yakunlandi\\!*\n\n"
            f"*G'oliblar:*\n{winners_text}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{bracket_text}\n\n"
            f"▶️ Davom etish uchun `/nextround` bering\\.",
            parse_mode="MarkdownV2",
        )
        return

    # Navbatdagi hal qilinmagan juftlikni so'rash
    pair_index = len(current_pairs) - len(pending_pairs)
    a, b = pending_pairs[0]
    ea, eb = escape_md(a), escape_md(b)

    keyboard = [[
        InlineKeyboardButton(f"🏅 {a}", callback_data=f"winner:{a}"),
        InlineKeyboardButton(f"🏅 {b}", callback_data=f"winner:{b}"),
    ]]
    markup = InlineKeyboardMarkup(keyboard)

    await ctx.bot.send_message(
        chat_id,
        f"⚔️ *{pair_index + 1}\\-jang g'olibi kim?*\n\n"
        f"  🔵 *{ea}*\n"
        f"  🔴 *{eb}*",
        parse_mode="MarkdownV2",
        reply_markup=markup,
    )


async def next_round(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not session["rounds"]:
        await update.message.reply_text(
            "❗ Avval `/shuffle` buyrug'ini bering\\.", parse_mode="MarkdownV2"
        )
        return

    if not session["rounds"][-1]:
        await update.message.reply_text(
            "❗ Joriy turda juftliklar yo'q\\. `/newgame` bilan qayta boshlang\\.",
            parse_mode="MarkdownV2",
        )
        return

    await ask_next_winner(chat_id, ctx)


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


async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    stats = session["stats"]

    if not stats:
        await update.message.reply_text(
            "📊 Hali statistika yo'q\\. Turnir o'tkazing\\!",
            parse_mode="MarkdownV2",
        )
        return

    # Saralash: avval unvon, keyin g'alabalar soni bo'yicha
    sorted_players = sorted(
        stats.items(),
        key=lambda x: (x[1]["titles"], x[1]["wins"]),
        reverse=True,
    )

    rows = []
    for i, (name, s) in enumerate(sorted_players):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "  "
        title_str = str(s['titles']) + "x" if s['titles'] > 0 else "-"
        rows.append(medal + " " + name[:12].ljust(12) + " " + str(s['wins']).rjust(5) + " " + str(s['losses']).rjust(5) + " " + title_str.rjust(5))

    col_header = "   " + "O'yinchi".ljust(12) + " " + "G".rjust(5) + " " + "M".rjust(5) + " " + "Unvon".rjust(5)
    divider = "-" * 36
    table_body = "\n".join([col_header, divider] + rows)
    msg = (
        "📊 *STATISTIKA*\n\n"
        "`" + table_body + "`\n\n"
        "_G \\= Galaba \\| M \\= Maghlubiyat \\| Unvon \\= Chempionlik_"
    )
    await update.message.reply_text(msg, parse_mode="MarkdownV2")


async def resetstats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    session["stats"] = {}
    await update.message.reply_text(
        "🗑 Statistika tozalandi\\.", parse_mode="MarkdownV2"
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

    elif query.data.startswith("winner:"):
        winner_name = query.data[len("winner:"):]

        # 🎊 Jang g'olibi — kichik wow e'lon
        medals = ["🥇", "🏅", "⭐", "💪", "🔥", "👑", "🎯", "💥"]
        medal = random.choice(medals)
        await query.edit_message_text(
            f"{medal} *{escape_md(winner_name)}* g'olib\\! {medal}",
            parse_mode="MarkdownV2",
        )

        # G'olibni saqlaymiz (duplicate bo'lmasin)
        if winner_name not in session["round_winners"]:
            session["round_winners"].append(winner_name)
            # Raqibni topib statistika yangilaymiz
            current_pairs = session["rounds"][-1] if session["rounds"] else []
            loser = None
            for a, b in current_pairs:
                if a == winner_name:
                    loser = b
                    break
                elif b == winner_name:
                    loser = a
                    break
            update_stats(session, winner_name, loser)

        # Keyingi juftlikni so'rash yoki tur yakunlash
        await ask_next_winner(chat_id, ctx)


# ─── Noma'lum buyruq ────────────────────────────────────────────────────────────

async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "❓ Noma'lum buyruq\\. Yordam uchun /help bering\\.",
        parse_mode="MarkdownV2",
    )


# ─── Render uchun Health Check HTTP server ─────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # HTTP loglarni o'chirish


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"✅ Health server {port}-portda ishga tushdi")
    server.serve_forever()


# ─── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError(
            "❌ BOT_TOKEN topilmadi!\n"
            "Render.com → Environment → BOT_TOKEN qo'shing.\n"
            "Yoki: export BOT_TOKEN=<tokeningiz>"
        )

    # Render Web Service: HTTP server alohida threadda
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()

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
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("resetstats", resetstats_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("✅ Bot ishga tushdi!")

    async def run():
        async with app:
            await app.initialize()
            # Oldingi sessiyalarni tozalash (conflict oldini olish)
            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )
            await app.start()
            await asyncio.Event().wait()

    asyncio.run(run())


if __name__ == "__main__":
    main()
