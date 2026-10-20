import asyncio
from datetime import datetime, timedelta
import logging
import os
import re
import threading
from flask import Flask
import google.generativeai as genai
from telegram import ChatPermissions, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ==========================================
# ⚙️ কনফিগারেশন (একদম সেট করা)
# ==========================================
BOT_TOKEN = "8777986749:AAHYtOSUckLrEfJE4D88LPKoi1Y-Hk3Nvfo"
GEMINI_KEY = "AQ.Ab8RN6JbMDwxYw80lVx4Aa9IX-SmuJcgkQh05qEMR2Hgsk925g"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Gemini AI সেটআপ ---
genai.configure(api_key=GEMINI_KEY)

GLOBAL_ROMANTIC_PROMPT = """
You are a sweet, romantic, and highly caring global AI companion.
- If the user talks in Bengali, respond in sweet, romantic, and flirty Bengali with heart emojis (❤️, 🥰, 😘).
- If the user talks in English or any other language, respond in very sweet, romantic, friendly, and elegant English.
- Keep your replies concise, natural, and warm. Never use bad language.
"""

try:
  model = genai.GenerativeModel("gemini-3.5-flash")
except Exception as e:
  logger.error(f"Gemini Model Error: {e}")

# রেজেক্স ফিল্টার
URL_REGEX = re.compile(
    r"(https?://|www\.|t\.me/|wa\.me/|telegram\.me/)", re.IGNORECASE
)
INBOX_REGEX = re.compile(
    r"(ইনবক্স|ইনবক্সে|dm|inbox|ডিএম|pm|personal)", re.IGNORECASE
)

link_cooldowns = {}

# ==========================================
# 🌐 ২৪/৭ সার্ভার রানিং রাখার জন্য হেলথ চেক
# ==========================================
app = Flask(__name__)


@app.route("/")
def home():
  return "OmniGuard AI Companion Bot is Running 24/7!"


def run_flask():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


# ==========================================
# 📢 চ্যানেল/লগ নোটিফিকেশন ফাংশন
# ==========================================
async def send_report_log(
    context: ContextTypes.DEFAULT_TYPE, chat_title, user_info, reason, text
):
  log_message = (
      f"🚨 **[SPAM REPORT LOG]**\n\n"
      f"👥 **Group:** {chat_title}\n"
      f"👤 **User:** {user_info}\n"
      f"❌ **Reason:** {reason}\n"
      f"💬 **Message:** `{text}`"
  )
  # অ্যাডমিন/বট মেসেজ হ্যান্ডলিং
  logger.info(f"Report Logged: {log_message}")


# ==========================================
# 🤖 বট কমান্ড ও বার্তা হ্যান্ডলার
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await update.message.reply_text(
      "💖 হ্যালো! আমি OmniGuard AI Companion। গ্রুপে আমার সাথে কথা বলতে মেসেজে"
      " আমাকে মেনশন বা রিপ্লাই করো। 🥰"
  )


async def welcome_new_member(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  for member in update.message.new_chat_members:
    await update.message.reply_text(
        f"💖 স্বাগতম {member.mention_html()} আমাদের গ্রুপে! আশা করি তোমার সময়টা"
        " খুব সুন্দর কাটবে। 🥰",
        parse_mode="HTML",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
  message = update.effective_message
  chat = update.effective_chat
  user = update.effective_user

  if not message or not message.text or not user:
    return

  is_admin = False
  try:
    member = await chat.get_member(user.id)
    if member.status in ["administrator", "creator"]:
      is_admin = True
  except Exception:
    pass

  text = message.text
  has_link = bool(URL_REGEX.search(text))
  has_inbox = bool(INBOX_REGEX.search(text))
  word_count = len(text.split())

  # এডমিন ছাড়া সাধারণ ইউজারদের মডারেশন রুলস
  if not is_admin:
    # ১. ইনবক্স রুলস
    if has_inbox:
      try:
        await message.delete()
        warn_msg = await context.bot.send_message(
            chat_id=chat.id,
            text=f"🚫 {user.mention_html()}, এখানে ইনবক্স বা DM চাওয়া নিষেধ!"
            " তোমাকে সতর্ক করা হলো।",
            parse_mode="HTML",
        )
        await send_report_log(
            context,
            chat.title,
            user.mention_html(),
            "DM/Inbox Solicitation",
            text,
        )
        await asyncio.sleep(60)
        await warn_msg.delete()
        return
      except Exception as e:
        logger.error(e)

    # ২. ওয়ার্ড লিমিট (সর্বোচ্চ ৩০ শব্দ)
    if word_count > 30:
      try:
        await message.delete()
        warn_msg = await context.bot.send_message(
            chat_id=chat.id,
            text=f"⚠️ {user.mention_html()}, সর্বোচ্চ ৩০ শব্দের বেশি মেসেজ"
            " দেওয়া যাবে না!",
            parse_mode="HTML",
        )
        await send_report_log(
            context, chat.title, user.mention_html(), "Word Limit Exceeded", text
        )
        await asyncio.sleep(60)
        await warn_msg.delete()
        return
      except Exception as e:
        logger.error(e)

    # ৩. লিংক কুলডাউন (৫ মিনিট)
    if has_link:
      now = datetime.now()
      last_link_time = link_cooldowns.get(user.id)

      if last_link_time and (now - last_link_time) < timedelta(minutes=5):
        remaining_time = 5 - int(
            (now - last_link_time).total_seconds() / 60
        )
        try:
          await message.delete()
          warn_msg = await context.bot.send_message(
              chat_id=chat.id,
              text=f"⏳ {user.mention_html()}, পরের লিংক দিতে আরও"
              f" {remaining_time} মিনিট অপেক্ষা করো।",
              parse_mode="HTML",
          )
          await send_report_log(
              context,
              chat.title,
              user.mention_html(),
              "Link Cooldown Violation",
              text,
          )
          await asyncio.sleep(60)
          await warn_msg.delete()
          return
        except Exception as e:
          logger.error(e)
      else:
        link_cooldowns[user.id] = now

  # ==========================================
  # 🤖 স্মার্ট AI চ্যাট রিপ্লাই
  # ==========================================
  bot_username = context.bot.username
  is_for_bot = False

  if bot_username and f"@{bot_username}" in text:
    is_for_bot = True
    text = text.replace(f"@{bot_username}", "").strip()

  if (
      message.reply_to_message
      and message.reply_to_message.from_user.id == context.bot.id
  ):
    is_for_bot = True

  if is_for_bot and text:
    try:
      await context.bot.send_chat_action(chat_id=chat.id, action="typing")
      final_prompt = GLOBAL_ROMANTIC_PROMPT + "\n\nUser: " + text
      response = model.generate_content(final_prompt)
      reply_text = response.text

      if len(reply_text) > 4000:
        reply_text = reply_text[:3990] + "..."

      await message.reply_text(reply_text)

    except Exception as e:
      logger.error(f"Gemini Error: {e}")
      await message.reply_text(
          "আমার একটু মন খারাপ আছে, একটু পর কথা বলি, ওকে? 🥺"
      )


def main():
  threading.Thread(target=run_flask, daemon=True).start()

  logger.info("🤖 Global AI Companion Bot Starting...")
  application = Application.builder().token(BOT_TOKEN).build()

  application.add_handler(CommandHandler("start", start_command))
  application.add_handler(
      MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member)
  )
  application.add_handler(
      MessageHandler(
          filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
          handle_message,
      )
  )

  logger.info("✅ Global Bot is Running...")
  application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
  main()
