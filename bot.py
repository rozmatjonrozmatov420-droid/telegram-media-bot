import os
import asyncio
import tempfile
import shutil
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import yt_dlp


BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "telegram_media_bot"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def is_subscribed(user_id: int, context) -> bool:
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME,
            user_id=user_id
        )

        return member.status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        ]

    except Exception:
        return False


def subscribe_keyboard():
    channel = CHANNEL_USERNAME.replace("@", "")

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 Kanalga obuna bo‘lish",
                url=f"https://t.me/{channel}"
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Obunani tekshirish",
                callback_data="check_subscription"
            )
        ]
    ])


async def require_subscription(update: Update, context) -> bool:
    user = update.effective_user

    if await is_subscribed(user.id, context):
        return True

    text = (
        "🔒 <b>Botdan foydalanish uchun kanalimizga obuna bo‘ling.</b>\n\n"
        "1️⃣ Kanalga obuna bo‘ling\n"
        "2️⃣ «Obunani tekshirish» tugmasini bosing\n"
        "3️⃣ Keyin video yoki musiqa havolasini yuboring."
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=subscribe_keyboard()
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=subscribe_keyboard()
        )

    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return

    await update.message.reply_text(
        "👋 <b>Salom!</b>\n\n"
        "🎬 Video yoki 🎵 musiqa yuklash uchun "
        "havolasini shu yerga yuboring.\n\n"
        "Masalan:\n"
        "🔗 YouTube\n"
        "🔗 Instagram\n"
        "🔗 TikTok\n"
        "🔗 Facebook\n"
        "🔗 X\n"
        "🔗 Reddit\n"
        "va yt-dlp qo‘llab-quvvatlaydigan boshqa saytlar.",
        parse_mode="HTML"
    )


async def check_subscription(update: Update, context):
    query = update.callback_query
    await query.answer()

    if await is_subscribed(query.from_user.id, context):
        await query.message.edit_text(
            "✅ <b>Obuna tasdiqlandi!</b>\n\n"
            "Endi video yoki musiqa havolasini yuborishingiz mumkin.",
            parse_mode="HTML"
        )
    else:
        await query.answer(
            "❌ Siz hali kanalga obuna bo‘lmagansiz.",
            show_alert=True
        )


def download_media(url: str, mode: str, folder: Path):
    if mode == "audio":
        options = {
            "format": "bestaudio/best",
            "outtmpl": str(folder / "%(title).80s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    else:
        options = {
            "format": "best[height<=720]/best",
            "outtmpl": str(folder / "%(title).80s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

        if mode == "audio":
            filename = str(Path(filename).with_suffix(".mp3"))
        else:
            mp4 = Path(filename).with_suffix(".mp4")
            if mp4.exists():
                filename = str(mp4)

        if not Path(filename).exists():
            files = list(folder.iterdir())
            if not files:
                raise Exception("Fayl topilmadi.")
            filename = str(files[0])

        return filename


async def process_link(update: Update, context):
    if not await require_subscription(update, context):
        return

    url = update.message.text.strip()

    if not (
        url.startswith("http://") or
        url.startswith("https://")
    ):
        await update.message.reply_text(
            "❌ Iltimos, to‘g‘ri havola yuboring."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 VIDEO", callback_data="video"),
            InlineKeyboardButton("🎵 AUDIO", callback_data="audio"),
        ]
    ])

    context.user_data["url"] = url

    await update.message.reply_text(
        "Havola qabul qilindi. 👇\n\n"
        "Qaysi formatda yuklaymiz?",
        reply_markup=keyboard
    )


async def download_callback(update: Update, context):
    query = update.callback_query
    await query.answer()

    if not await is_subscribed(query.from_user.id, context):
        await query.message.reply_text(
            "🔒 Avval kanalga obuna bo‘ling.",
            reply_markup=subscribe_keyboard()
        )
        return

    url = context.user_data.get("url")

    if not url:
        await query.message.reply_text(
            "❌ Havola topilmadi. Havolani qaytadan yuboring."
        )
        return

    mode = query.data

    await query.message.edit_text(
        "⏳ Yuklanmoqda...\n"
        "Biroz kuting."
    )

    folder = DOWNLOAD_DIR / str(query.from_user.id)

    if folder.exists():
        shutil.rmtree(folder)

    folder.mkdir(parents=True, exist_ok=True)

    try:
        filename = await asyncio.to_thread(
            download_media,
            url,
            mode,
            folder
        )

        file_path = Path(filename)

        if not file_path.exists():
            raise Exception("Fayl yaratilmadi.")

        # Telegram bot upload limitidan oshib ketmasligi uchun
        if file_path.stat().st_size > 49 * 1024 * 1024:
            await query.message.edit_text(
                "❌ Fayl juda katta.\n\n"
                "Telegram bot orqali yuborish uchun fayl hajmi "
                "juda katta bo‘ldi."
            )
            return

        await query.message.edit_text("📤 Telegramga yuborilmoqda...")

        with open(file_path, "rb") as file:
            if mode == "audio":
                await query.message.reply_audio(
                    audio=file,
                    caption="🎵 Tayyor!"
                )
            else:
                await query.message.reply_video(
                    video=file,
                    caption="🎬 Tayyor!",
                    supports_streaming=True
                )

        await query.message.delete()

    except Exception as e:
        await query.message.edit_text(
            "❌ Yuklashda xatolik yuz berdi.\n\n"
            "Havola ishlamasligi yoki platforma tomonidan "
            "cheklangan bo‘lishi mumkin."
        )

    finally:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)


async def help_command(update: Update, context):
    if not await require_subscription(update, context):
        return

    await update.message.reply_text(
        "📖 <b>Botdan foydalanish</b>\n\n"
        "1. Video yoki musiqa havolasini nusxalang.\n"
        "2. Botga yuboring.\n"
        "3. 🎬 VIDEO yoki 🎵 AUDIO tanlang.\n"
        "4. Bot faylni tayyorlab beradi.",
        parse_mode="HTML"
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN sozlanmagan.")

    if not CHANNEL_USERNAME:
        raise RuntimeError("CHANNEL_USERNAME sozlanmagan.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        CallbackQueryHandler(
            check_subscription,
            pattern="^check_subscription$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            download_callback,
            pattern="^(video|audio)$"
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            process_link
        )
    )

    print("Bot ishga tushdi...")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
