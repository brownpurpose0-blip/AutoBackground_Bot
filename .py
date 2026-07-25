import asyncio
import io
import logging
import os

from PIL import Image
from rembg import remove, new_session
from telegram import Update, InputFile
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("autobackgroundbot")

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# u2netp is a much smaller/faster model (~4MB) than the default u2net (~176MB),
# which keeps memory and cold-start time reasonable on a small Railway plan.
# Set REMBG_MODEL=u2net in Railway variables if you want higher quality and
# have the RAM/CPU budget for it.
REMBG_MODEL = os.environ.get("REMBG_MODEL", "u2netp")
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15MB safety cap

_session = None  # created lazily so bot startup isn't blocked by model load


def get_session():
    global _session
    if _session is None:
        logger.info("Loading rembg model '%s'...", REMBG_MODEL)
        _session = new_session(REMBG_MODEL)
        logger.info("Model loaded.")
    return _session


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *AutoBackground_Bot*\n\n"
        "Send me a photo (or an image file) and I'll remove the background "
        "and send it back as a transparent PNG.\n\n"
        "Use /help for details.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Just send a photo or image document — no command needed.\n\n"
        "*Tips*\n"
        "• Send as a *file/document* (not a compressed photo) for the best "
        "quality input — Telegram compresses regular photos.\n"
        "• The output is always a lossless PNG with a transparent background, "
        "sent back as a document.\n\n"
        "/stats — how many images you've processed\n"
        f"Max file size: {MAX_FILE_SIZE_BYTES // (1024*1024)}MB",
        parse_mode=ParseMode.MARKDOWN,
    )


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = await db.get_stats(update.effective_user.id)
    await update.message.reply_text(f"Images processed: {stats['images_processed']}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]  # largest size
    await process_and_reply(update, context, photo.file_id, photo.file_size)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        return
    await process_and_reply(update, context, doc.file_id, doc.file_size)


async def process_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str, file_size):
    if file_size and file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text(
            f"That file is too large ({file_size // (1024*1024)}MB). "
            f"Max is {MAX_FILE_SIZE_BYTES // (1024*1024)}MB."
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
    status_msg = await update.message.reply_text("🎨 Removing background... this can take a few seconds.")

    try:
        tg_file = await context.bot.get_file(file_id)
        input_bytes = bytes(await tg_file.download_as_bytearray())

        loop = asyncio.get_event_loop()
        output_bytes = await loop.run_in_executor(None, remove_background_sync, input_bytes)

        output_file = io.BytesIO(output_bytes)
        output_file.name = "no-background.png"

        await update.message.reply_document(
            document=InputFile(output_file, filename="no-background.png"),
            caption="✅ Done!",
        )
        await db.record_process(update.effective_user.id)
    except Exception:
        logger.exception("background removal failed")
        await update.message.reply_text(
            "Something went wrong processing that image. Make sure it's a valid "
            "image file and try again."
        )
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass


def remove_background_sync(input_bytes: bytes) -> bytes:
    session = get_session()
    # Normalize input via PIL first so odd formats/modes don't trip up rembg.
    image = Image.open(io.BytesIO(input_bytes)).convert("RGBA")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    result = remove(buf.getvalue(), session=session)
    return result


async def post_init(application: Application):
    await db.init_db()


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))

    logger.info("Starting AutoBackground_Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
