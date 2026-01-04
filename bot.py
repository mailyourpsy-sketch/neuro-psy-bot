import os
import logging
import re
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("BOOT: SIMPLE BUY PREVIEW")

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

BUY_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["Купить 30 кредитов · 30 ₽"],
        ["Купить 100 кредитов · 90 ₽"],
        ["Купить 300 кредитов · 250 ₽"],
    ],
    resize_keyboard=True,
)

BUY_RE = re.compile(r"Купить\s+(30|100|300)", re.IGNORECASE)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(BUY_TEXT, reply_markup=BUY_KEYBOARD)


async def handle_buy_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    m = BUY_RE.search(text)
    if not m:
        return

    amount = int(m.group(1))
    if amount == 30:
        msg = "Вы выбрали пакет 30 кредитов за 30 ₽"
    elif amount == 100:
        msg = "Вы выбрали пакет 100 кредитов за 90 ₽"
    else:
        msg = "Вы выбрали пакет 300 кредитов за 250 ₽"

    await update.message.reply_text(msg)


def main():
    app = Application.builder().token(os.environ["BOT_TOKEN"]).build()

    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_buttons))

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        url_path=os.environ["WEBHOOK_PATH"],
        webhook_url=f"{os.environ['WEBHOOK_URL'].rstrip('/')}/{os.environ['WEBHOOK_PATH'].lstrip('/')}",
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
