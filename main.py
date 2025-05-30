# ✅ MovieAutoBot: Fully Featured Telegram Bot (main.py)

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

# Load .env
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Bot client setup
bot = Client("MovieAutoBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
logging.basicConfig(level=logging.INFO)

# MongoDB setup
client = MongoClient(MONGO_URI)
db = client.moviebot
movies = db.movies
users = db.users

# Flask server for keep-alive
app = Flask(__name__)
@app.route("/")
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run).start()

# Save user
async def save_user(user):
    if not users.find_one({"_id": user.id}):
        users.insert_one({"_id": user.id, "username": user.username, "joined": datetime.utcnow(), "is_premium": False, "expiry": None})

# Premium checker
def is_premium(user_id):
    u = users.find_one({"_id": user_id})
    if u and u.get("is_premium") and u.get("expiry"):
        return datetime.utcnow() < u["expiry"]
    return False

# Add movie
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
            movies.insert_one({"title": title, "year": year, "lang": lang, "link": m.text, "date": datetime.utcnow()})

# Inline search
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
        btns = InlineKeyboardMarkup([
            [InlineKeyboardButton("ভুল নাম লিখেছি", callback_data=f"nf_{iq.from_user.id}_wrong")],
            [InlineKeyboardButton("এখনো আসেনি", callback_data=f"nf_{iq.from_user.id}_notyet")],
            [InlineKeyboardButton("আপলোড আছে", callback_data=f"nf_{iq.from_user.id}_exists")],
            [InlineKeyboardButton("শিগগির আসবে", callback_data=f"nf_{iq.from_user.id}_soon")]
        ])
        await c.send_message(ADMIN_ID, f"❗ Movie not found: {query}")
User: [{iq.from_user.first_name}](tg://user?id={iq.from_user.id})
Query: `{query}`", reply_markup=btns)
    await iq.answer(results, cache_time=1)

# Callback handler (admin response)
@bot.on_callback_query()
async def callback_handler(c, cb):
    if not str(cb.from_user.id) == str(ADMIN_ID):
        await cb.answer("Admins only", show_alert=True)
        return
    _, uid, resp = cb.data.split("_")
    msg = {
        "wrong": "আপনি ভুল নাম লিখেছেন। দয়া করে আবার চেষ্টা করুন।",
        "notyet": "এই মুভিটি এখনো আমাদের ডাটাবেসে নেই।",
        "exists": "মুভিটি আপলোড আছে, একটু ভালোভাবে সার্চ করুন।",
        "soon": "এই মুভিটি শিগগিরই আপলোড করা হবে।"
    }.get(resp, "ধন্যবাদ")
    await c.send_message(int(uid), msg)
    await cb.answer("User notified.")

# Buy command
@bot.on_message(filters.command("buy"))
async def buy_cmd(c, m):
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("7 দিন - 50৳", callback_data="buy_7")],
        [InlineKeyboardButton("15 দিন - 80৳", callback_data="buy_15")],
        [InlineKeyboardButton("30 দিন - 120৳", callback_data="buy_30")],
    ])
    await m.reply("💳 পেমেন্ট করতে নিচের বিকাশ/নগদ নাম্বার ব্যবহার করুন:
`01975123274`

প্ল্যান বেছে নিন এবং এডমিনকে জানান: @ctgmovies23", reply_markup=btn)

# Grant premium (admin only)
@bot.on_message(filters.command("grant") & filters.user(ADMIN_ID))
async def grant(c, m):
    try:
        uid, days = map(str.strip, m.text.split()[1:])
        expiry = datetime.utcnow() + timedelta(days=int(days))
        users.update_one({"_id": int(uid)}, {"$set": {"is_premium": True, "expiry": expiry}}, upsert=True)
        await m.reply("✅ Granted")
    except:
        await m.reply("Usage: /grant user_id days")

# Delete commands
@bot.on_message(filters.command("delete_movie") & filters.user(ADMIN_ID))
async def delete_movie(c, m):
    title = m.text.split(maxsplit=1)[1]
    result = movies.delete_one({"title": {"$regex": f"^{title}$", "$options": "i"}})
    await m.reply(f"🗑️ Deleted: {result.deleted_count}")

@bot.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_ID))
async def delete_all_movies(c, m):
    movies.drop()
    await m.reply("🗑️ All movies deleted")

# Stats
@bot.on_message(filters.command("stats") & filters.user(ADMIN_ID))
async def stats(c, m):
    u = users.count_documents({})
    p = users.count_documents({"is_premium": True})
    mv = movies.count_documents({})
    await m.reply(f"👤 Users: {u}\n💎 Premiums: {p}\n🎬 Movies: {mv}")

# Start bot
bot.run()
