from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


BUY_TEXT = (
    "NeuroPsychologist 🤍\n\n"
    "Текстовый ИИ-ассистент для психологической поддержки.\n"
    "Формат: диалог в чате Telegram.\n\n"
    "Тарифы:\n"
    "• 30 кредитов — 30 ₽\n"
    "• 100 кредитов — 90 ₽\n"
    "• 300 кредитов — 250 ₽\n\n"
    "1 ответ = 3 кредита\n"
    "5 первых ответов — бесплатно"
)

BUY_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("Купить 30 кредитов · 30 ₽", callback_data="preview:credits_30")],
    [InlineKeyboardButton("Купить 100 кредитов · 90 ₽", callback_data="preview:credits_100")],
    [InlineKeyboardButton("Купить 300 кредитов · 250 ₽", callback_data="preview:credits_300")],
])


async def buy_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(BUY_TEXT, reply_markup=BUY_KB)


async def preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    _, key = q.data.split(":", 1)
    if key == "credits_30":
        msg = "Вы выбрали пакет 30 кредитов за 30 ₽"
    elif key == "credits_100":
        msg = "Вы выбрали пакет 100 кредитов за 90 ₽"
    elif key == "credits_300":
        msg = "Вы выбрали пакет 300 кредитов за 250 ₽"
    else:
        msg = "Пакет не найден"

    await q.message.reply_text(msg)
import re
from telegram import Update
from telegram.ext import ContextTypes

BUY_BUTTON_RE = re.compile(r"^Купить\s+(30|100|300)\s+кредитов", re.IGNORECASE)

async def buy_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    m = BUY_BUTTON_RE.match(text)
    if not m:
        return

    n = int(m.group(1))
    if n == 30:
        msg = "Вы выбрали пакет 30 кредитов за 30 ₽"
    elif n == 100:
        msg = "Вы выбрали пакет 100 кредитов за 90 ₽"
    else:
        msg = "Вы выбрали пакет 300 кредитов за 250 ₽"

    await update.message.reply_text(msg)

