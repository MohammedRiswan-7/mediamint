import os
import asyncio
import logging
import datetime
import re
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import yt_dlp

# ─────────────────────────── CONFIG ──────────────────────────────
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME")
print("DEBUG BOT TOKEN:", BOT_TOKEN)
CREDENTIALS_FILE = "credential.json"
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────── GOOGLE SHEETS ───────────────────────

import datetime
import gspread
from google.oauth2.service_account import Credentials

# ================= CONFIG =================
SPREADSHEET_ID = "1EZBi5WbTBQiwlo6K-W0qF482eGkc5CTiowbPIUq0-Tg"
CREDENTIALS_FILE = "credentials.json"

# ================= CLIENT =================
def get_sheets_client():
    print("🔐 Loading credential file...")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=scopes
    )

    return gspread.authorize(creds)

# ================= SHEETS =================
def get_sheets():
    client = get_sheets_client()
    sheet = client.open_by_key(SPREADSHEET_ID)

    try:
        users_ws = sheet.worksheet("Users")
    except:
        users_ws = sheet.add_worksheet(title="Users", rows=1000, cols=10)
        users_ws.append_row(["user_id", "name", "username", "timestamp"])

    try:
        downloads_ws = sheet.worksheet("Downloads")
    except:
        downloads_ws = sheet.add_worksheet(title="Downloads", rows=5000, cols=10)
        downloads_ws.append_row([
            "user_id", "username", "action", "link", "title", "timestamp"
        ])

    return users_ws, downloads_ws

# ================= USER REGISTER =================
def register_user(user):
    try:
        users_ws, _ = get_sheets()

        records = users_ws.get_all_records()

        for r in records:
            if str(r.get("user_id")) == str(user.id):
                return

        users_ws.append_row([
            user.id,
            f"{user.first_name or ''} {user.last_name or ''}".strip(),
            user.username or "",
            datetime.datetime.utcnow().isoformat()
        ])

    except Exception as e:
        print("register_user error:", e)

# ================= DOWNLOAD LOG =================
def log_download(user_id, username, action, link, title):
    try:
        _, downloads_ws = get_sheets()

        downloads_ws.append_row([
            str(user_id),
            username or "",
            action,
            link,
            title,
            datetime.datetime.utcnow().isoformat()
        ])

    except Exception as e:
        print("log_download error:", e)

# ================= HISTORY =================
def get_user_history(user_id):
    try:
        _, downloads_ws = get_sheets()

        rows = downloads_ws.get_all_values()
        history = []

        for row in reversed(rows[1:]):
            if len(row) >= 6 and str(row[0]) == str(user_id):
                action = row[2]
                title = row[4]
                date = row[5][:10]
                history.append(f"{action} — {title} ({date})")

            if len(history) >= 5:
                break

        return history

    except Exception as e:
        print("history error:", e)
        return []

# ================= DOWNLOAD COUNT =================
def get_user_download_count(user_id):
    try:
        _, downloads_ws = get_sheets()
        rows = downloads_ws.get_all_values()

        return sum(1 for r in rows[1:] if r and str(r[0]) == str(user_id))

    except:
        return 0

# ================= CLEAR HISTORY =================
def clear_user_history(user_id):
    try:
        _, downloads_ws = get_sheets()

        rows = downloads_ws.get_all_values()

        if not rows:
            return

        header = rows[0]
        new_rows = [header]

        for r in rows[1:]:
            if not r or str(r[0]) != str(user_id):
                new_rows.append(r)

        downloads_ws.clear()
        downloads_ws.update(new_rows, "A1")

    except Exception as e:
        print("clear_user_history error:", e)

# ================= TEST FUNCTION =================
def test_sheet():
    try:
        users_ws, _ = get_sheets()
        users_ws.append_row(["test_user", "ok", "working", str(datetime.datetime.utcnow())])
        print("✅ Google Sheet Connected Successfully")
    except Exception as e:
        print("❌ Sheet Test Failed:", e)
# ─────────────────────────── IN-MEMORY STATE ─────────────────────
user_states: dict[int, dict] = {}

def get_state(user_id: int) -> dict:
    if user_id not in user_states:
        user_states[user_id] = {"awaiting_url": False, "pending_url": None}
    return user_states[user_id]

# ─────────────────────────── KEYBOARDS ───────────────────────────

def kb_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Enter URL ", callback_data="go_download")],
        [
            InlineKeyboardButton("📜 History", callback_data="go_history"),
            InlineKeyboardButton("ℹ️ Help", callback_data="go_help"),
        ],
        [InlineKeyboardButton("👤 About", callback_data="go_about")],
    ])


def kb_download():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎥 Video", callback_data="fmt_video"),
            InlineKeyboardButton("🎵 Audio (MP3)", callback_data="fmt_audio"),
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="go_home")],
    ])


def kb_video_quality():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 360p", callback_data="quality_360")],
        [InlineKeyboardButton("🖥️ 720p", callback_data="quality_720")],
        [InlineKeyboardButton("🎬 1080p", callback_data="quality_1080")],
        [InlineKeyboardButton("🔙 Back", callback_data="go_download")],
    ])


def kb_share():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share Bot", url=f"https://t.me/{BOT_USERNAME}")],
        [InlineKeyboardButton("🏠 Home", callback_data="go_home")],
    ])


def kb_history(has_items: bool):
    rows = []
    if has_items:
        rows.append([InlineKeyboardButton("🗑️ Clear History", callback_data="clear_history")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="go_home")])
    return InlineKeyboardMarkup(rows)


def kb_back_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="go_home")]
    ])

# ─────────────────────────── SCREEN TEXTS ────────────────────────

def text_home(user) -> str:
    username = f"@{user.username}" if user.username else user.first_name or "User"
    count = get_user_download_count(user.id)
    return (
        "🎬 *MediaMint Dashboard*\n\n"
        f"👤 User: {username}\n"
        f"📊 download Audio/Video \n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome! What would you like to do today?"
    )


def text_download() -> str:
    return (
        "📥 *Download Center*\n\n"
        "Please paste a YouTube or Instagram URL below.\n\n"
        "Then choose your format:"
    )


def text_help() -> str:
    return (
        "ℹ️ *How to Use MediaMint*\n\n"
        "1️⃣ Tap *📥 Download Media* from the dashboard\n"
        "2️⃣ Paste a *YouTube* or *Instagram* link\n"
        "3️⃣ Choose *Video* or *Audio* format\n"
        "4️⃣ For video, select quality (360p / 720p / 1080p)\n"
        "5️⃣ Wait while we download and send the file\n"
        "6️⃣ Enjoy and share the bot with friends! 🎉\n\n"
        "_Supported: YouTube, Instagram_"
    )


def text_about() -> str:
    return (
        "👤 *About MediaMint*\n\n"
        "🤖 *Bot:* MediaMint Downloader\n"
        "🔖 *Version:* 1.0.0\n"
        "⚙️ *Engine:* yt-dlp + FFmpeg\n"
        "📊 *Storage:* Google Sheets\n"
        "🛡️ *Platform:* Telegram\n\n"
        ""
    )

# ─────────────────────────── URL DETECTION ───────────────────────

def is_supported_url(text: str) -> bool:
    patterns = [
        r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/\S+",
        r"(https?://)?(www\.)?instagram\.com/\S+",
    ]
    return any(re.search(p, text) for p in patterns)

# ─────────────────────────── DOWNLOAD LOGIC ──────────────────────

async def download_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    fmt: str,
    quality: str | None,
):
    user = update.effective_user
    chat_id = update.effective_chat.id

    progress_msg = await context.bot.send_message(chat_id, "⏳ Starting download…")

    async def edit(text: str):
        try:
            await progress_msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass

    stages = [
        ("🔍 Fetching media info…", 0),
        ("⬇️ Downloading… `10%`", 1),
        ("⬇️ Downloading… `30%`", 1),
        ("⬇️ Downloading… `55%`", 1),
        ("⬇️ Downloading… `75%`", 1),
        ("🔧 Processing… `90%`", 1),
        ("✅ Finalising… `100%`", 0.5),
    ]

    async def fake_progress():
        for msg, delay in stages:
            await edit(msg)
            await asyncio.sleep(delay)

    progress_task = asyncio.create_task(fake_progress())

    try:
        output_tmpl = str(DOWNLOADS_DIR / "%(id)s.%(ext)s")

        if fmt == "audio":
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": output_tmpl,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "quiet": True,
                "no_warnings": True,
            }
        else:
            height = {"360": 360, "720": 720, "1080": 1080}.get(quality, 720)
            ydl_opts = {
                "format": f"bestvideo[height<={height}]+bestaudio/best[height<={height}]",
                "outtmpl": output_tmpl,
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
            }

        loop = asyncio.get_event_loop()

        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info

        info = await loop.run_in_executor(None, _download)

        progress_task.cancel()

        video_id = info.get("id", "media")
        ext = "mp3" if fmt == "audio" else "mp4"
        file_path = DOWNLOADS_DIR / f"{video_id}.{ext}"

        if not file_path.exists():
            candidates = list(DOWNLOADS_DIR.glob(f"{video_id}.*"))
            if candidates:
                file_path = candidates[0]
            else:
                raise FileNotFoundError("Downloaded file not found on disk.")

        title = info.get("title", "media")
        action_label = f"audio MP3" if fmt == "audio" else f"video {quality}p"

        await edit(f"📤 Sending *{title}*…")

        if fmt == "audio":
            with open(file_path, "rb") as f:
                await context.bot.send_audio(
                    chat_id,
                    audio=f,
                    title=title,
                    caption=f"🎵 *{title}*\n\n_Downloaded by MediaMint_",
                    parse_mode="Markdown",
                    reply_markup=kb_share(),
                )
        else:
            with open(file_path, "rb") as f:
                await context.bot.send_video(
                    chat_id,
                    video=f,
                    caption=f"🎬 *{title}* ({quality}p)\n\n_Downloaded by MediaMint_",
                    parse_mode="Markdown",
                    supports_streaming=True,
                    reply_markup=kb_share(),
                )

        await progress_msg.delete()

        log_download(user.id, user.username or str(user.id), action_label, url, title)

        try:
            file_path.unlink()
        except Exception:
            pass

    except asyncio.CancelledError:
        pass
    except Exception as e:
        progress_task.cancel()
        logger.error(f"Download error: {e}")
        await edit(
            f"❌ *Download Failed*\n\n"
            f"`{str(e)[:200]}`\n\n"
            "Please check the URL and try again."
        )

# ─────────────────────────── HANDLERS ────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    state = get_state(user.id)
    state["awaiting_url"] = False
    state["pending_url"] = None
    await update.message.reply_text(
        text_home(user),
        parse_mode="Markdown",
        reply_markup=kb_home(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data
    state = get_state(user.id)

    async def edit(text, markup=None):
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)

    if data == "go_home":
        state["awaiting_url"] = False
        state["pending_url"] = None
        await edit(text_home(user), kb_home())

    elif data == "go_download":
        state["awaiting_url"] = True
        state["pending_url"] = None
        await edit(
            "📥 *Download Center*\n\n"
            "✏️ Please paste a *YouTube* or *Instagram* URL in the chat:",
            kb_back_home(),
        )

    elif data == "go_history":
        history = get_user_history(user.id)
        if history:
            lines = "\n".join(f"• {h}" for h in history)
            text = f"📜 *Recent Downloads*\n\n{lines}"
        else:
            text = "📜 *History*\n\nNo downloads yet. Start by downloading something! 🎬"
        await edit(text, kb_history(bool(history)))

    elif data == "clear_history":
        clear_user_history(user.id)
        await edit("🗑️ History cleared!", kb_back_home())

    elif data == "go_help":
        await edit(text_help(), kb_back_home())

    elif data == "go_about":
        await edit(text_about(), kb_back_home())

    elif data == "fmt_video":
        url = state.get("pending_url")
        if not url:
            await edit("⚠️ No URL found. Please go back and paste a link.", kb_back_home())
            return
        await edit(
            f"🎥 *Video Quality*\n\nURL: `{url[:60]}…`\n\nSelect quality:",
            kb_video_quality(),
        )

    elif data == "fmt_audio":
        url = state.get("pending_url")
        if not url:
            await edit("⚠️ No URL found. Please go back and paste a link.", kb_back_home())
            return
        state["awaiting_url"] = False
        await edit("🎵 *Audio (MP3)* selected!\n\nStarting download…", None)
        await download_media(update, context, url, "audio", None)

    elif data.startswith("quality_"):
        quality = data.split("_")[1]
        url = state.get("pending_url")
        if not url:
            await edit("⚠️ No URL found. Please go back and paste a link.", kb_back_home())
            return
        state["awaiting_url"] = False
        await edit(f"🎬 *{quality}p* selected!\n\nStarting download…", None)
        await download_media(update, context, url, "video", quality)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = get_state(user.id)
    text = update.message.text or ""

    if state.get("awaiting_url"):
        if is_supported_url(text):
            state["pending_url"] = text
            state["awaiting_url"] = False
            await update.message.reply_text(
                f"🔗 *URL received!*\n\n`{text[:80]}`\n\nNow choose your format:",
                parse_mode="Markdown",
                reply_markup=kb_download(),
            )
        else:
            await update.message.reply_text(
                "⚠️ That doesn't look like a valid YouTube or Instagram URL.\n\n"
                "Please paste a proper link and try again.",
                reply_markup=kb_back_home(),
            )
    else:
        if is_supported_url(text):
            state["pending_url"] = text
            state["awaiting_url"] = False
            await update.message.reply_text(
                f"🔗 *URL detected!*\n\n`{text[:80]}`\n\nChoose your format:",
                parse_mode="Markdown",
                reply_markup=kb_download(),
            )
        else:
            await update.message.reply_text(
                "👋 Use /start to open the dashboard!",
                reply_markup=kb_home(),
            )

# ─────────────────────────── MAIN ────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("🎬 MediaMint Bot is running…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()