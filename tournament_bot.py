"""
🎮 Tournament Randomizer Bot - Render.com uchun tayyor
Ishlatish: BOT_TOKEN=<token> REQUIRED_GROUP=@guruh python tournament_bot.py
"""

import os
import re
import random
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

# ── Sozlamalar ─────────────────────────────────────────────────────────────────
# REQUIRED_GROUP = guruh ID si (masalan: -1001234567890)
# Guruh ID sini bilish uchun: guruhga @userinfobot qo'shing va /start yozing
_raw_group = os.environ.get("REQUIRED_GROUP", "")
if _raw_group.lstrip("-").isdigit():
    REQUIRED_GROUP = int(_raw_group)   # raqam bo'lsa ID sifatida ishlatamiz
else:
    REQUIRED_GROUP = _raw_group        # aks holda username (@guruh)

# ── Ma'lumotlar ────────────────────────────────────────────────────────────────
sessions: dict = {}


def get_session(chat_id: int) -> dict:
    if chat_id not in sessions:
        sessions[chat_id] = {
            "players": [], "rounds": [],
            "current_round": 0, "round_winners": [], "stats": {},
        }
    if "stats" not in sessions[chat_id]:
        sessions[chat_id]["stats"] = {}
    return sessions[chat_id]


def ensure_player_stats(stats: dict, name: str) -> None:
    if name not in stats:
        stats[name] = {"wins": 0, "losses": 0, "titles": 0, "points": 0}
    if "points" not in stats[name]:
        stats[name]["points"] = 0


def update_stats(session: dict, winner: str, loser: str = None) -> None:
    stats = session["stats"]
    ensure_player_stats(stats, winner)
    stats[winner]["wins"] += 1
    if loser and loser != "bye":
        ensure_player_stats(stats, loser)
        stats[loser]["losses"] += 1


# ── Yordamchi funksiyalar ──────────────────────────────────────────────────────
def esc(text) -> str:
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(text))


def make_pairs(players: list) -> list:
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
        if b == "bye":
            lines.append(f"  {i}\\. 🎯 *{esc(a)}* — \\(bye, o'tib ketadi\\)")
        else:
            lines.append(f"  {i}\\. ⚔️  {esc(a)}  🆚  {esc(b)}")
    return "\n".join(lines)


def format_players(players: list) -> str:
    if not players:
        return "_\\(hali hech kim yo'q\\)_"
    return "\n".join(f"  {i+1}\\. {esc(p)}" for i, p in enumerate(players))


# ── Obuna tekshiruvi ───────────────────────────────────────────────────────────
async def check_subscription(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    if not REQUIRED_GROUP:
        return True

    user_id = update.effective_user.id
    username = update.effective_user.username or "no_username"

    # Guruh havolasini oldindan tayyorlaymiz (ID yoki username bo'lishi mumkin)
    if isinstance(REQUIRED_GROUP, int):
        # ID dan havola yasab bo'lmaydi, shuning uchun faqat tugma matni ko'rsatamiz
        group_link = None
    else:
        group_link = f"https://t.me/{REQUIRED_GROUP.lstrip('@')}"

    is_member = False
    try:
        member = await ctx.bot.get_chat_member(chat_id=REQUIRED_GROUP, user_id=user_id)
        print(f"[SUB CHECK] user={user_id} (@{username}) group={REQUIRED_GROUP} status={member.status}")

        if member.status not in ("left", "kicked", "banned"):
            return True  # a'zo

        print(f"[SUB] user={user_id} a'zo emas — bloklandi")

    except Exception as e:
        err = str(e).lower()
        print(f"[SUB ERROR] user={user_id} group={REQUIRED_GROUP} error={e}")
        # Faqat "bot admin emas" xatoligida o'tkazib yuborish
        if any(x in err for x in ["not enough rights", "bot was kicked", "chat not found", "forbidden"]):
            print("[SUB] Bot admin emas yoki guruh noto'g'ri — REQUIRED_GROUP ni tekshiring!")
            # Bu yerda bloklashni davom ettiramiz — xato konfiguratsiya, foydalanuvchini o'tkazmaymiz
        # Foydalanuvchi topilmadi = a'zo emas
        # Boshqa xatolarda ham bloklash

    # A'zo emas — xabar yuborish
    if group_link:
        keyboard = [[InlineKeyboardButton("✅ Guruhga qo'shilish", url=group_link)]]
        markup = InlineKeyboardMarkup(keyboard)
    else:
        keyboard = None
        markup = None

    await update.message.reply_text(
        "⛔ *Botdan foydalanish uchun guruhimizga a'zo bo'lish kerak\\!*\n\n"
        "👇 Guruhga qo'shiling va qaytadan urinib ko'ring\\.",
        parse_mode="MarkdownV2",
        reply_markup=markup,
    )
    return False


# ── Buyruqlar ──────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Tournament Randomizer Botga xush kelibsiz\\!*\n\n"
        "Bu bot o'yinchilarni random juftlarga ajratib turnir o'tkazishga yordam beradi\\.\n\n"
        "📋 *Buyruqlar:*\n"
        "  /newgame — yangi o'yin boshlash\n"
        "  /add Ism — o'yinchi qo'shish\n"
        "  /remove Ism — o'yinchini o'chirish\n"
        "  /players — o'yinchilar ro'yxati\n"
        "  /shuffle — random juftlash\n"
        "  /nextround — keyingi tur\n"
        "  /stats yoki /rating — reyting\n"
        "  /resetstats — statistikani tozalash\n"
        "  /status — joriy holat\n"
        "  /clear — o'yinni tozalash\n"
        "  /help — yordam"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, ctx)


async def newgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription(update, ctx):
        return
    chat_id = update.effective_chat.id
    old_stats = get_session(chat_id).get("stats", {})
    sessions[chat_id] = {
        "players": [], "rounds": [],
        "current_round": 0, "round_winners": [], "stats": old_stats,
    }
    await update.message.reply_text(
        "✅ *Yangi o'yin boshlandi\\!*\n\n"
        "O'yinchilarni qo'shish uchun `/add Ism` buyrug'ini bering\\.\n"
        "Tayyor bo'lgach `/shuffle` bering\\.",
        parse_mode="MarkdownV2",
    )


async def add_player(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription(update, ctx):
        return
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not ctx.args:
        await update.message.reply_text("❗ Ism kiriting: `/add Sardor`", parse_mode="MarkdownV2")
        return

    name = " ".join(ctx.args).strip()
    if not name:
        await update.message.reply_text("❗ Ism bo'sh bo'lmasin\\.", parse_mode="MarkdownV2")
        return
    if len(name) > 50:
        await update.message.reply_text("❗ Ism juda uzun \\(max 50 belgi\\)\\.", parse_mode="MarkdownV2")
        return
    if name.lower() in [p.lower() for p in session["players"]]:
        await update.message.reply_text(
            f"⚠️ *{esc(name)}* allaqachon ro'yxatda\\!", parse_mode="MarkdownV2"
        )
        return
    if len(session["players"]) >= 64:
        await update.message.reply_text("❗ Maksimal 64 ta o'yinchi\\.", parse_mode="MarkdownV2")
        return

    session["players"].append(name)
    count = len(session["players"])
    await update.message.reply_text(
        f"✅ *{esc(name)}* qo'shildi\\! Jami: *{count}* ta o'yinchi\\.\n"
        f"Tayyor bo'lgach `/shuffle` bering\\.",
        parse_mode="MarkdownV2",
    )


async def remove_player(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription(update, ctx):
        return
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if not ctx.args:
        await update.message.reply_text("❗ Ism kiriting: `/remove Sardor`", parse_mode="MarkdownV2")
        return

    if session["rounds"]:
        await update.message.reply_text(
            "⚠️ Turnir davom etmoqda\\! O'chirish uchun avval `/clear` bering\\.",
            parse_mode="MarkdownV2",
        )
        return

    name = " ".join(ctx.args).strip()
    matches = [p for p in session["players"] if p.lower() == name.lower()]
    if not matches:
        await update.message.reply_text(f"❗ *{esc(name)}* topilmadi\\.", parse_mode="MarkdownV2")
        return

    session["players"].remove(matches[0])
    await update.message.reply_text(
        f"🗑 *{esc(matches[0])}* o'chirildi\\. Qoldi: *{len(session['players'])}* ta\\.",
        parse_mode="MarkdownV2",
    )


async def list_players(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription(update, ctx):
        return
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    players_text = format_players(session["players"])
    await update.message.reply_text(
        f"👥 *O'yinchilar ro'yxati \\({len(session['players'])} ta\\):*\n{players_text}",
        parse_mode="MarkdownV2",
    )


async def shuffle(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription(update, ctx):
        return
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if len(session["players"]) < 2:
        await update.message.reply_text(
            "❗ Kamida 2 ta o'yinchi kerak\\! `/add Ism` bilan qo'shing\\.",
            parse_mode="MarkdownV2",
        )
        return

    pairs = make_pairs(session["players"])
    session["rounds"] = [pairs]
    session["current_round"] = 1
    session["round_winners"] = []

    bracket_text = format_bracket(pairs, 1)
    keyboard = [[InlineKeyboardButton("🔀 Qayta aralashtir", callback_data="reshuffle")]]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(bracket_text, parse_mode="MarkdownV2", reply_markup=markup)


async def ask_next_winner(chat_id: int, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    session = get_session(chat_id)
    current_pairs = session["rounds"][-1]
    confirmed = session["round_winners"]

    for a, b in current_pairs:
        if b == "bye" and a not in confirmed:
            confirmed.append(a)

    pending = [
        (a, b) for a, b in current_pairs
        if a not in confirmed and b not in confirmed and b != "bye"
    ]

    if not pending:
        winners = confirmed[:]

        if len(winners) < 2:
            winner_name = winners[0] if winners else "???"
            stats = session["stats"]
            ensure_player_stats(stats, winner_name)
            stats[winner_name]["titles"] += 1
            stats[winner_name]["points"] += 3

            last_pairs = session["rounds"][-1] if session["rounds"] else []
            finalist_name = None
            for a, b in last_pairs:
                if a == winner_name and b != "bye":
                    finalist_name = b
                    break
                elif b == winner_name and a != "bye":
                    finalist_name = a
                    break
            if finalist_name:
                ensure_player_stats(stats, finalist_name)
                stats[finalist_name]["points"] += 1

            session["rounds"] = []
            session["current_round"] = 0
            session["round_winners"] = []

            finalist_line = (
                f"🥈 Finalist: *{esc(finalist_name)}* \\+1 ball\n\n"
                if finalist_name else ""
            )
            wow = (
                "🎊🎊🎊🎊🎊🎊🎊🎊🎊🎊\n\n"
                "🏆 *TURNIR YAKUNLANDI\\!* 🏆\n\n"
                f"👑 *CHEMPION:*\n"
                f"🌟 *{esc(winner_name)}* 🌟 \\+3 ball\n\n"
                + finalist_line
                + "🥇🎖 Tabriklaymiz\\! 🎖🥇\n\n"
                "🎊🎊🎊🎊🎊🎊🎊🎊🎊🎊\n\n"
                "_Yangi turnir uchun_ /newgame"
            )
            await ctx.bot.send_message(chat_id, wow, parse_mode="MarkdownV2")
            return

        new_pairs = make_pairs(winners)
        session["rounds"].append(new_pairs)
        session["current_round"] += 1
        session["round_winners"] = []

        winners_text = "\n".join(f"  🏅 {esc(w)}" for w in winners)
        bracket_text = format_bracket(new_pairs, session["current_round"])

        await ctx.bot.send_message(
            chat_id,
            f"🔥 *{esc(session['current_round'] - 1)}\\-tur yakunlandi\\!*\n\n"
            f"*G'oliblar:*\n{winners_text}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{bracket_text}\n\n"
            f"▶️ Davom etish uchun /nextround bering\\.",
            parse_mode="MarkdownV2",
        )
        return

    pair_index = len(current_pairs) - len(pending)
    a, b = pending[0]

    keyboard = [[
        InlineKeyboardButton(f"🏅 {a}", callback_data=f"winner:{a}"),
        InlineKeyboardButton(f"🏅 {b}", callback_data=f"winner:{b}"),
    ]]
    markup = InlineKeyboardMarkup(keyboard)

    await ctx.bot.send_message(
        chat_id,
        f"⚔️ *{esc(pair_index + 1)}\\-jang g'olibi kim?*\n\n"
        f"  🔵 *{esc(a)}*\n"
        f"  🔴 *{esc(b)}*",
        parse_mode="MarkdownV2",
        reply_markup=markup,
    )


async def next_round(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription(update, ctx):
        return
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
    if not await check_subscription(update, ctx):
        return
    chat_id = update.effective_chat.id
    old_stats = get_session(chat_id).get("stats", {})
    sessions[chat_id] = {
        "players": [], "rounds": [],
        "current_round": 0, "round_winners": [], "stats": old_stats,
    }
    await update.message.reply_text(
        "🗑 O'yin tozalandi \\(statistika saqlanib qoldi\\)\\.\n"
        "Yangi o'yin uchun `/newgame` bering\\.",
        parse_mode="MarkdownV2",
    )


async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription(update, ctx):
        return
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    stats = session["stats"]

    if not stats:
        await update.message.reply_text(
            "📊 Hali statistika yo'q\\. Turnir o'tkazing\\!",
            parse_mode="MarkdownV2",
        )
        return

    sorted_players = sorted(
        stats.items(),
        key=lambda x: (x[1].get("points", 0), x[1]["titles"], x[1]["wins"]),
        reverse=True,
    )

    rows = []
    for i, (name, s) in enumerate(sorted_players):
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "  "
        title_str = str(s["titles"]) + "x" if s["titles"] > 0 else "-"
        pts = s.get("points", 0)
        row = (
            medal + " "
            + name[:10].ljust(10) + " "
            + str(pts).rjust(4) + " "
            + str(s["wins"]).rjust(4) + " "
            + str(s["losses"]).rjust(4) + " "
            + title_str.rjust(4)
        )
        rows.append(row)

    header = "   " + "Ism".ljust(10) + " " + "Ball".rjust(4) + " " + "G".rjust(4) + " " + "M".rjust(4) + " " + "Unvon".rjust(5)
    divider = "-" * 33
    table = "\n".join([header, divider] + rows)

    msg = (
        "📊 *GURUH REYTINGI*\n\n"
        "`" + table + "`\n\n"
        "_Ball: 🥇Chempion\\=3  🥈Finalist\\=1_"
    )
    await update.message.reply_text(msg, parse_mode="MarkdownV2")


async def resetstats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription(update, ctx):
        return
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    session["stats"] = {}
    await update.message.reply_text("🗑 Statistika tozalandi\\.", parse_mode="MarkdownV2")


async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription(update, ctx):
        return
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    lines = ["📊 *Joriy holat:*\n"]
    lines.append(f"👥 O'yinchilar: *{esc(len(session['players']))}* ta")
    lines.append(f"🔄 Tugallangan turlar: *{esc(session['current_round'])}*")

    if session["rounds"]:
        last = session["rounds"][-1]
        active = [(a, b) for a, b in last if b != "bye"]
        pending = [
            (a, b) for a, b in active
            if a not in session["round_winners"] and b not in session["round_winners"]
        ]
        lines.append(f"⚔️ Joriy turdagi juftliklar: *{esc(len(active))}* ta")
        lines.append(f"⏳ Kutilayotgan janlar: *{esc(len(pending))}* ta")

    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


# ── Inline tugmalar ────────────────────────────────────────────────────────────
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

        if winner_name in session["round_winners"]:
            return

        medals = ["🥇", "🏅", "⭐", "💪", "🔥", "👑", "🎯", "💥"]
        medal = random.choice(medals)
        await query.edit_message_text(
            f"{medal} *{esc(winner_name)}* g'olib\\! {medal}",
            parse_mode="MarkdownV2",
        )

        session["round_winners"].append(winner_name)

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

        await ask_next_winner(chat_id, ctx)


async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "❓ Noma'lum buyruq\\. Yordam uchun /help bering\\.",
        parse_mode="MarkdownV2",
    )


# ── Render Health Check ────────────────────────────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Tournament Bot is running")

    def log_message(self, format, *args):
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server {port}-portda ishga tushdi")
    server.serve_forever()


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN topilmadi! Render > Environment > BOT_TOKEN qo'shing.")

    if REQUIRED_GROUP:
        print(f"Obuna tekshiruvi yoqilgan: {REQUIRED_GROUP}")
    else:
        print("Obuna tekshiruvi o'chirilgan (REQUIRED_GROUP o'rnatilmagan)")

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
    app.add_handler(CommandHandler("rating", stats_cmd))
    app.add_handler(CommandHandler("resetstats", resetstats_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Bot ishga tushdi!")

    async def run():
        async with app:
            await app.initialize()
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
