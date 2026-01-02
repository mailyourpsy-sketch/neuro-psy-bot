import os
import sqlite3
import logging
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from openai import OpenAI

# -----------------------------
# Config
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("bot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# Railway public domain, e.g. https://your-app.up.railway.app
WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL", "").rstrip("/")
# Secret path for webhook URL, e.g. "hook_9f3a12"
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "hook_default_change_me")

# Admins for manual credit top-ups (comma-separated telegram user ids)
ADMIN_IDS = set()
_admin_raw = os.environ.get("ADMIN_IDS", "").strip()
if _admin_raw:
    for part in _admin_raw.split(","):
        part = part.strip()
        if part.isdigit():
            ADMIN_IDS.add(int(part))

# Product settings
FREE_WELCOME_ANSWERS = 5
COST_PER_ANSWER_CREDITS = 3

PACKAGES = [
    ("30", 30, "30 кредитов — 30 ₽"),
    ("100", 100, "100 кредитов — 90 ₽"),
    ("300", 300, "300 кредитов — 250 ₽"),
]

PAYMENT_TEXT = os.environ.get(
    "PAYMENT_TEXT",
    "Оплата пока вручную.\n\nПереведите нужную сумму, затем нажмите «Я оплатил».\n"
    "Реквизиты: (сюда вставишь карту/кошелёк/ссылку)\n"
    "После оплаты я начислю кредиты."
)

SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    """Ты — нейропсихологический консультант.

Стиль:
— спокойный
— уважительный
— без диагнозов
— без упоминаний ИИ или ChatGPT
— без морализаторства

Цель:
— помочь человеку осознать состояние
— дать поддержку и структуру
— задать 1 уточняющий вопрос

Формат:
— 5–10 предложений
— лаконично
"""
).strip()

MODEL_NAME = os.environ.get("OPENAI_MODEL", "gpt-5-nano")

# Safety limits
MAX_USER_CHARS = 2000
MAX_CONTEXT_MESSAGES = 8  # last N messages (user+assistant)

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------
# DB
# -----------------------------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
  telegram_id INTEGER PRIMARY KEY,
  free_answers INTEGER NOT NULL,
  paid_credits INTEGER NOT NULL,
  created_at TEXT NOT NULL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_id INTEGER NOT NULL,
  role TEXT NOT NULL,            -- 'user' or 'assistant'
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
)
""")

conn.commit()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_or_create_user(tg_id: int):
    cur.execute("SELECT free_answers, paid_credits FROM users WHERE telegram_id=?", (tg_id,))
    row = cur.fetchone()
    if row:
        return row[0], row[1]
    cur.execute(
        "INSERT INTO users (telegram_id, free_answers, paid_credits, created_at) VALUES (?, ?, ?, ?)",
        (tg_id, FREE_WELCOME_ANSWERS, 0, utc_now_iso())
    )
    conn.commit()
    return FREE_WELCOME_ANSWERS, 0


def update_user_free(tg_id: int, new_free: int):
    cur.execute("UPDATE users SET free_answers=? WHERE telegram_id=?", (new_free, tg_id))
    conn.commit()


def update_user_paid(tg_id: int, new_paid: int):
    cur.execute("UPDATE users SET paid_credits=? WHERE telegram_id=?", (new_paid, tg_id))
    conn.commit()


def add_paid_credits(tg_id: int, amount: int):
    free, paid = get_or_create_user(tg_id)
    paid_new = paid + amount
    update_user_paid(tg_id, paid_new)
    return free, paid_new


def save_message(tg_id: int, role: str, content: str):
    cur.execute(
        "INSERT INTO messages (telegram_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (tg_id, role, content, utc_now_iso())
    )
    conn.commit()


def get_recent_messages(tg_id: int, limit: int):
    cur.execute(
        "SELECT role, content FROM messages WHERE telegram_id=? ORDER BY id DESC LIMIT ?",
        (tg_id, limit)
    )
    rows = cur.fetchall()
    rows.reverse()
    return rows


def can_answer(tg_id: int):
    free, paid = get_or_create_user(tg_id)
    if free > 0:
        return True, "free", free, paid
    if paid >= COST_PER_ANSWER_CREDITS:
        return True, "paid", free, paid
    return False, None, free, paid


def consume(tg_id: int, kind: str):
    free, paid = get_or_create_user(tg_id)
    if kind == "free":
        update_user_free(tg_id, max(0, free - 1))
        free -= 1
    elif kind == "paid":
        update_user_paid(tg_id, max(0, paid - COST_PER_ANSWER_CREDITS))
        paid -= COST_PER_ANSWER_CREDITS
    return free, paid


# -----------------------------
# UI helpers
# -----------------------------
def buy_keyboard():
    buttons = [[InlineKeyboardButton(text=label, callback_data=f"buy:{code}")]
               for code, _, label in PACKAGES]
    buttons.append([InlineKeyboardButton(text="Я оплатил", callback_data="paid:claimed")])
    return InlineKeyboardMarkup(buttons)


def balance_text(free: int, paid: int):
    return (
        f"Баланс:\n"
        f"— бесплатных ответов: {free}\n"
        f"— платных кредитов: {paid}\n\n"
        f"Стоимость ответа: {COST_PER_ANSWER_CREDITS} кредита (1 кредит = 1 ₽)"
    )


# -----------------------------
# OpenAI call
# -----------------------------
def build_openai_input(tg_id: int, user_text: str):
    # System + short context
    history = get_recent_messages(tg_id, MAX_CONTEXT_MESSAGES)
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for role, content in history:
        # Telegram roles -> OpenAI roles
        if role not in ("user", "assistant"):
            continue
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_text})
    return msgs


def ask_openai(tg_id: int, user_text: str) -> str:
    context = build_openai_input(tg_id, user_text)

    # Responses API (recommended). output_text helper is convenient. :contentReference[oaicite:2]{index=2}
    resp = client.responses.create(
        model=MODEL_NAME,
        input=context,
        store=False,
        # optional: cap output a bit so costs + "простыни" не улетали
        max_output_tokens=350,
    )
    text = (resp.output_text or "").strip()
    return text if text else "Я на связи. Сформулируйте вопрос чуть подробнее, пожалуйста."


# -----------------------------
# Handlers
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    free, paid = get_or_create_user(tg_id)

    msg = (
        "Здравствуйте.\n\n"
        "Я — нейропсихологический помощник.\n"
        "Помогаю разобраться в состоянии, мыслях и эмоциях.\n\n"
        f"✅ У вас есть {FREE_WELCOME_ANSWERS} бесплатных ответов, чтобы ознакомиться.\n\n"
        f"Стоимость одного ответа — {COST_PER_ANSWER_CREDITS} кредита.\n"
        "1 кредит = 1 ₽.\n\n"
        "Напишите свой вопрос."
    )
    await update.message.reply_text(msg)
    await update.message.reply_text(balance_text(free, paid))


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    free, paid = get_or_create_user(tg_id)
    await update.message.reply_text(balance_text(free, paid))


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(PAYMENT_TEXT, reply_markup=buy_keyboard())


async def admin_addcredits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    if tg_id not in ADMIN_IDS:
        return

    # /addcredits <user_id> <amount>
    args = context.args
    if len(args) != 2 or (not args[0].isdigit()) or (not args[1].lstrip("-").isdigit()):
        await update.message.reply_text("Формат: /addcredits <telegram_user_id> <amount>")
        return

    user_id = int(args[0])
    amount = int(args[1])
    if amount <= 0:
        await update.message.reply_text("amount должен быть > 0")
        return

    free, paid = add_paid_credits(user_id, amount)
    await update.message.reply_text(
        f"Начислено {amount} кредитов пользователю {user_id}.\n"
        f"Теперь: free_answers={free}, paid_credits={paid}"
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    tg_id = query.from_user.id
    get_or_create_user(tg_id)

    if data.startswith("buy:"):
        # show payment text again
        await query.message.reply_text(PAYMENT_TEXT, reply_markup=buy_keyboard())
        return

    if data == "paid:claimed":
        await query.message.reply_text(
            "Ок. Напишите, пожалуйста, сумму и пакет (30/100/300). "
            "После подтверждения я начислю кредиты."
        )
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    tg_id = update.effective_user.id
    text = update.message.text.strip()
    if not text:
        return

    if len(text) > MAX_USER_CHARS:
        await update.message.reply_text(f"Слишком длинно. Сократите до {MAX_USER_CHARS} символов.")
        return

    allowed, kind, free, paid = can_answer(tg_id)
    if not allowed:
        await update.message.reply_text(
            "Бесплатные ответы закончились и кредитов не хватает.\n\n"
            f"Стоимость ответа — {COST_PER_ANSWER_CREDITS} кредита.\n"
            "Выберите пакет для пополнения:",
            reply_markup=buy_keyboard()
        )
        return

    # Save user message
    save_message(tg_id, "user", text)

    await update.message.chat.send_action("typing")

    try:
        answer = ask_openai(tg_id, text)
    except Exception as e:
        log.exception("OpenAI error: %s", e)
        await update.message.reply_text("Техническая ошибка. Попробуйте ещё раз через минуту.")
        return

    # Save assistant message
    save_message(tg_id, "assistant", answer)

    # Consume AFTER answer generated (so user doesn't lose credits on errors)
    free_after, paid_after = consume(tg_id, kind)

    # Send answer + remaining
    if kind == "free":
        tail = f"\n\nℹ️ Осталось бесплатных ответов: {free_after}"
    else:
        tail = f"\n\nℹ️ Осталось кредитов: {paid_after}"

    await update.message.reply_text(answer + tail)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("addcredits", admin_addcredits))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.COMMAND, balance))  # unknown commands -> balance/help-ish
    app.add_handler(CallbackQueryHandler(on_callback))

    port = int(os.environ.get("PORT", "8080"))

    if not WEBHOOK_BASE_URL or WEBHOOK_PATH == "hook_default_change_me":
        log.warning("WEBHOOK_BASE_URL or WEBHOOK_PATH not set. For local test, use polling.")
        # Local quick test
        app.run_polling(close_loop=False)
        return

    webhook_url = f"{WEBHOOK_BASE_URL}/{WEBHOOK_PATH}"

    log.info("Starting webhook on port=%s path=/%s", port, WEBHOOK_PATH)
    # If no cert/key: PTB starts HTTP, SSL can be handled by Railway/proxy. :contentReference[oaicite:3]{index=3}
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=WEBHOOK_PATH,
        webhook_url=webhook_url,
        drop_pending_updates=True,
        close_loop=False,
    )


if __name__ == "__main__":
    main()
