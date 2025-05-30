import os
import re
import time
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pyrogram import Client, filters, types
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pymongo import MongoClient
from flask import Flask
from threading import Thread

# Load .env variables
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Bot setup
bot = Client("MovieAutoBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# MongoDB setup
client = MongoClient(MONGO_URI)
db = client.moviebot
movies = db.movies
users = db.users

# Flask keep-alive
app = Flask(__name__)
@app.route("/")
def home():
    return "Bot is running!"
Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 8080}).start()

# Save user to DB
async def save_user(user):
    if not users.find_one({"_id": user.id}):
        users.insert_one({
            "_id": user.id,
            "username": user.username,
            "joined": datetime.utcnow(),
            "is_premium": False,
            "expiry": None
        })

def is_premium(user_id):
    u = users.find_one({"_id": user_id})
    return bool(u and u.get("is_premium") and u.get("expiry") and datetime.utcnow() < u["expiry"])

# Handle /start
@bot.on_message(filters.command("start"))
async def start_cmd(c, m):
    await save_user(m.from_user)
    await m.reply_text(
        f"👋 হ্যালো {m.from_user.first_name}!\n\n"
        "🎬 আমি একটি Movie Bot। ইনলাইন মোডে সার্চ করতে:\n"
        "`@YourBotUsername মুভির নাম`\n\n"
        "🛒 প্রিমিয়াম নিতে /buy চাপুন।",
        quote=True
    )

# Handle /buy
@bot.on_message(filters.command("buy"))
async def buy_cmd(c, m):
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("7 দিন - ৫০৳", callback_data="buy_7")],
        [InlineKeyboardButton("15 দিন - ৮০৳", callback_data="buy_15")],
        [InlineKeyboardButton("30 দিন - ১২০৳", callback_data="buy_30")],
    ])
    await m.reply(
        "💳 পেমেন্ট করতে নিচের বিকাশ/নগদ নাম্বার ব্যবহার করুন:\n`01975123274`\n\n"
        "প্ল্যান বেছে নিন এবং এডমিনকে জানান: @ctgmovies23",
        reply_markup=btn
    )

# Grant premium
@bot.on_message(filters.command("grant") & filters.user(ADMIN_ID))
async def grant(c, m):
    try:
        uid, days = map(str.strip, m.text.split()[1:])
        expiry = datetime.utcnow() + timedelta(days=int(days))
        users.update_one({"_id": int(uid)}, {"$set": {"is_premium": True, "expiry": expiry}}, upsert=True)
        await m.reply("✅ প্রিমিয়াম গ্রান্ট করা হয়েছে।")
    except Exception as e:
        await m.reply("ব্যবহারের নিয়ম: `/grant user_id দিন`")

# Save movies from channel
@bot.on_message(filters.channel & filters.chat(CHANNEL_ID))
async def save_movie(c, m):
    if not m.text:
        return
    title_match = re.match(r"^(.*?)\s+(\d{4})\s+(.*?)\s", m.text)
    if title_match:
        title = title_match.group(1).strip()
        year = title_match.group(2)
        lang = title_match.group(3)
        existing = movies.find_one({"title": title, "year": year})
        if not existing:
            movies.insert_one({
                "title": title,
                "year": year,
                "lang": lang,
                "link": m.text,
                "date": datetime.utcnow()
            })

# Inline search handler
@bot.on_inline_query()
async def search_movie(c, iq):
    await save_user(iq.from_user)
    query = iq.query.strip()
    if not query:
        await iq.answer([], cache_time=1)
        return

    res = movies.find({"title": {"$regex": query, "$options": "i"}}).limit(20)
    results = []
    for i, m in enumerate(res):
        if not is_premium(iq.from_user.id) and i >= 2:
            break
        results.append(types.InlineQueryResultArticle(
            title=f"{m['title']} ({m['year']}) [{m['lang']}]",
            input_message_content=types.InputTextMessageContent(m['link'])
        ))

    if not results:
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ ভুল নাম লিখেছি", callback_data=f"nf_{iq.from_user.id}_wrong")],
            [InlineKeyboardButton("⌛ এখনো আসেনি", callback_data=f"nf_{iq.from_user.id}_notyet")],
            [InlineKeyboardButton("✅ আপলোড আছে", callback_data=f"nf_{iq.from_user.id}_exists")],
            [InlineKeyboardButton("📥 শিগগির আসবে", callback_data=f"nf_{iq.from_user.id}_soon")]
        ])
        await c.send_message(iq.from_user.id, f"❗ মুভি পাওয়া যায়নি:\n`{query}`", reply_markup=buttons)

    await iq.answer(results, cache_time=1)

# Callback feedback (Admin only)
@bot.on_callback_query()
async def callback_handler(c, cb):
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("Admins only", show_alert=True)
        return
    _, uid, resp = cb.data.split("_")
    messages = {
        "wrong": "❗ আপনি ভুল নাম লিখেছেন। আবার চেষ্টা করুন।",
        "notyet": "⏳ এই মুভিটি এখনো আমাদের কাছে নেই।",
        "exists": "✅ মুভিটি আপলোড আছে, ভালোভাবে খুঁজুন।",
        "soon": "📥 শিগগিরই আপলোড করা হবে।"
    }
    await c.send_message(int(uid), messages.get(resp, "ধন্যবাদ"))
    await cb.answer("রেসপন্স পাঠানো হয়েছে।")

# Delete one movie
@bot.on_message(filters.command("delete_movie") & filters.user(ADMIN_ID))
async def delete_movie(c, m):
    try:
        title = m.text.split(maxsplit=1)[1]
        result = movies.delete_one({"title": {"$regex": f"^{title}$", "$options": "i"}})
        await m.reply(f"🗑️ ডিলিট হয়েছে: {result.deleted_count} টি মুভি।")
    except IndexError:
        await m.reply("ব্যবহারের নিয়ম: `/delete_movie [মুভির নাম]`")

# Delete all movies
@bot.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_ID))
async def delete_all_movies(c, m):
    movies.drop()
    await m.reply("🗑️ সব মুভি ডিলিট করা হয়েছে।")

# Stats command
@bot.on_message(filters.command("stats") & filters.user(ADMIN_ID))
async def stats(c, m):
    total = users.count_documents({})
    premium = users.count_documents({"is_premium": True})
    mv = movies.count_documents({})
    await m.reply(f"👤 ইউজার: {total}\n💎 প্রিমিয়াম: {premium}\n🎬 মোট মুভি: {mv}")

# Run bot
bot.run()
