import os
import asyncio
import tempfile
import threading
from pathlib import Path

from flask import Flask
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


# =========================
# SOZLAMALAR
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "telegram_media_bot"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# =========================
# RENDER HEALTH SERVER
# =========================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Telegram Media Bot ishlayapti!"


@web_app.route("/health")
def health():
    return "OK", 200


def run_web_server():
    port = int(os.getenv("PORT", "10000"))
    web_app.run(host="0.0.0.0", port=port)


# =========================
# OBUNA TEKSHIRISH
# =========================

async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not CHANNEL_USERNAME:
        return True

    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL_USERNAME,
            user_id=user_id
        )

        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception as e:
        print("Obuna tekshirish xatosi:", e)
        return False


def subscription_keyboard():
    channel = CHANNEL_USERNAME or ""

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 Kanalga obuna bo‘lish",
                url=f"https://t.me/{channel.lstrip('@')}"
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Obunani tekshirish",
                callback_data="check_subscription"
            )
        ]
    ])


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not await is_subscribed(user.id, context):
        await update.message.reply_text(
            "👋 Assalomu alaykum!\n\n"
            "Botdan foydalanish uchun avval kanalimizga obuna bo‘ling 👇",
            reply_markup=subscription_keyboard()
        )
        return

    await update.message.reply_text(
        "👋 Assalomu alaykum!\n\n"
        "🎬 Instagram, TikTok, YouTube va boshqa qo‘llab-quvvatlanadigan "
        "saytlardan video yoki audio yuklab olishingiz mumkin.\n\n"
        "🔗 Havolani yuboring."
    )


# =========================
# HELP
# =========================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Botdan foydalanish:\n\n"
        "1️⃣ Kanalga obuna bo‘ling.\n"
        "2️⃣ Video yoki audio havolasini yuboring.\n"
        "3️⃣ Kerakli formatni tanlang.\n\n"
        "🎬 Video — videoni yuklab beradi.\n"
        "🎵 Audio — audioni MP3 formatida yuklab beradi."
    )


# =========================
# OBUNANI TEKSHIRISH
# =========================

async def check_subscription(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if await is_subscribed(query.from_user.id, context):
        await query.edit_message_text(
            "✅ Obunangiz tasdiqlandi!\n\n"
            "🔗 Endi video yoki audio havolasini yuboring."
        )
    else:
        await query.edit_message_text(
            "❌ Siz hali kanalga obuna bo‘lmagansiz.\n\n"
            "Avval obuna bo‘ling:",
            reply_markup=subscription_keyboard()
        )


# =========================
# HAVOLANI QABUL QILISH
# =========================

async def process_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not await is_subscribed(user.id, context):
        await update.message.reply_text(
            "❌ Avval kanalga obuna bo‘ling.",
            reply_markup=subscription_keyboard()
        )
        return

    url = update.message.text.strip()

    if not url.startswith(("http://", "https://")):
        await update.message.reply_text(
            "❗ Iltimos, to‘g‘ri havola yuboring."
        )
        return

    context.user_data["url"] = url

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎬 VIDEO",
                callback_data="video"
            ),
            InlineKeyboardButton(
                "🎵 AUDIO",
                callback_data="audio"
            )
        ]
    ])

    await update.message.reply_text(
        "📥 Havola qabul qilindi.\n\n"
        "Qaysi format kerak?",
        reply_markup=keyboard
    )


# =========================
# YUKLAB OLISH
# =========================

async def download_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("url")

    if not url:
        await query.edit_message_text(
            "❌ Havola topilmadi. Havolani qaytadan yuboring."
        )
        return

    media_type = query.data

    await query.edit_message_text(
        "⏳ Yuklab olinmoqda...\n"
        "Iltimos, biroz kuting."
    )

    try:
        if media_type == "audio":
            result = await download_audio(url)
        else:
            result = await download_video(url)

        if not result:
            await query.message.reply_text(
                "❌ Yuklab olishning iloji bo‘lmadi."
            )
            return

        file_path, title = result

        await query.message.reply_text(
            "✅ Tayyor!\n\n"
            "📤 Telegramga yuborilmoqda..."
        )

        if media_type == "audio":
            with open(file_path, "rb") as audio:
                await query.message.reply_audio(
                    audio=audio,
                    title=title[:100]
                )
        else:
            with open(file_path, "rb") as video:
                await query.message.reply_video(
                    video=video,
                    caption="✅ Yuklab olindi"
                )

        try:
            os.remove(file_path)
        except Exception:
            pass

    except Exception as e:
        print("Download error:", e)

        await query.message.reply_text(
            "❌ Xatolik yuz berdi.\n\n"
            "Havola ishlamasligi yoki sayt tomonidan "
            "yuklab olish cheklangan bo‘lishi mumkin."
        )


# =========================
# VIDEO
# =========================

async def download_video(url: str):
    output_template = str(
        DOWNLOAD_DIR / "%(id)s.%(ext)s"
    )

    options = {
        "outtmpl": output_template,
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }

    def download():
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

            filename = ydl.prepare_filename(info)

            if os.path.exists(filename):
                return filename, info.get("title", "video")

            # Ba'zi formatlarda kengaytma o‘zgarishi mumkin
            base = Path(filename).stem

            for file in DOWNLOAD_DIR.glob(base + ".*"):
                return str(file), info.get("title", "video")

        return None

    return await asyncio.to_thread(download)


# =========================
# AUDIO
# =========================

async def download_audio(url: str):
    output_template = str(
        DOWNLOAD_DIR / "%(id)s.%(ext)s"
    )

    options = {
        "outtmpl": output_template,
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    def download():
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

            filename = ydl.prepare_filename(info)
            mp3_file = str(Path(filename).with_suffix(".mp3"))

            if os.path.exists(mp3_file):
                return mp3_file, info.get("title", "audio")

            base = Path(filename).stem

            for file in DOWNLOAD_DIR.glob(base + ".mp3"):
                return str(file), info.get("title", "audio")

        return None

    return await asyncio.to_thread(download)


# =========================
# MAIN
# =========================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN sozlanmagan."
        )

    if not CHANNEL_USERNAME:
        print(
            "DIQQAT: CHANNEL_USERNAME sozlanmagan. "
            "Majburiy obuna tekshiruvi o‘chirilgan."
        )

    # Render health serverini alohida thread'da ishga tushirish
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CallbackQueryHandler(
            check_subscription,
            pattern="^check_subscription$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            download_callback,
            pattern="^(video|audio)$"
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            process_link
        )
    )

    print("🤖 Bot ishga tushdi...")
    print("🌐 Health server ishlayapti...")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
