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

# --- কনফিগারেশন লোড ---
load_dotenv()
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SESSION_NAME = os.getenv("SESSION_NAME", "MovieAutoBot_DefaultSession")

# --- বট ক্লায়েন্ট সেটআপ ---
bot = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- লগিং সেটআপ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
# Pyrogram এর নিজস্ব লগিং কমিয়ে দেওয়া হয়েছে যাতে অতিরিক্ত লগ না আসে
logging.getLogger("pyrogram").setLevel(logging.WARNING)

# --- MongoDB সেটআপ ---
try:
    client = MongoClient(MONGO_URI)
    db = client.moviebot
    movies = db.movies
    users = db.users
    logging.info("MongoDB connected successfully!")
except Exception as e:
    logging.error(f"MongoDB connection error: {e}")
    exit(1) # MongoDB কানেক্ট না হলে বট বন্ধ করে দেওয়া হবে

# --- ফ্লাস্ক সার্ভার ফর কিপ-এলাইভ ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=os.getenv("PORT", 8080)) # PORT ভেরিয়েবল ব্যবহার করা হয়েছে

# --- ব্যবহারকারী সেভ ফাংশন ---
async def save_user(user):
    # যদি ব্যবহারকারী ইতিমধ্যেই ডেটাবেসে না থাকে, তবে সেভ করুন
    if not users.find_one({"_id": user.id}):
        users.insert_one({
            "_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "joined": datetime.utcnow(),
            "is_premium": False,
            "expiry": None
        })
        logging.info(f"New user saved: {user.username or user.first_name} ({user.id})")

# --- প্রিমিয়াম চেকার ফাংশন ---
def is_premium(user_id):
    u = users.find_one({"_id": user_id})
    if u and u.get("is_premium") and u.get("expiry"):
        return datetime.utcnow() < u["expiry"]
    return False

# --- মুভি অ্যাড ফাংশন (চ্যানেল ফিল্টার) ---
@bot.on_message(filters.channel & filters.chat(CHANNEL_ID) & filters.text)
async def save_movie(c, m):
    # নিশ্চিত করুন যে মেসেজটি একটি টেক্সট মেসেজ এবং কোনো ফরওয়ার্ড করা মেসেজ নয়
    if m.forward_from_chat or m.forward_from or m.forward_sender_name:
        logging.info(f"Skipping forwarded message in channel: {m.id}")
        return

    # টাইটেল, বছর এবং ভাষা বের করার জন্য regex
    # ^(.*?)\s+(\d{4})\s+(.*?)\s - এটি একটি সাধারণ regex যা মুভির নাম (যে কোনো কিছু), বছর (৪টি সংখ্যা), এবং ভাষা (যে কোনো কিছু) কে পৃথক করে
    # যেমন: "Movie Name 2023 Bengali - Link"
    title_match = re.match(r"^(.*?)\s+(\d{4})\s+(.*?)\s", m.text)

    if title_match:
        title = title_match.group(1).strip()
        year = title_match.group(2)
        lang = title_match.group(3).split(" ")[0].strip() # ভাষার পরে অতিরিক্ত টেক্সট থাকলে তা বাদ দেওয়া

        # ডেটাবেসে মুভিটি আছে কিনা তা চেক করুন
        existing = movies.find_one({"title": title, "year": year})
        if not existing:
            movies.insert_one({
                "title": title,
                "year": year,
                "lang": lang,
                "link": m.text, # পুরো মেসেজটিকে লিংক হিসেবে সংরক্ষণ করা হয়েছে
                "date": datetime.utcnow()
            })
            logging.info(f"Saved new movie: {title} ({year}) [{lang}]")
        else:
            logging.info(f"Movie already exists: {title} ({year})")
    else:
        logging.warning(f"Could not parse movie from channel message: {m.text}")

# --- ইনলাইন সার্চ হ্যান্ডলার ---
@bot.on_inline_query()
async def search_movie(c, iq: types.InlineQuery):
    await save_user(iq.from_user) # ইনলাইন কোয়েরি করলেও ব্যবহারকারী সেভ হবে
    query = iq.query.strip()
    logging.info(f"Inline query from {iq.from_user.username or iq.from_user.first_name} ({iq.from_user.id}): '{query}'")

    if not query:
        await iq.answer([], cache_time=1)
        return

    # টাইটেল regex সার্চ এবং লিমিট
    res = movies.find({"title": {"$regex": query, "$options": "i"}}).limit(20)
    results = []
    
    is_user_premium = is_premium(iq.from_user.id)

    for i, m in enumerate(res):
        # প্রিমিয়াম ব্যবহারকারী না হলে প্রথম 2টি ফলাফলের পর আর দেখাবে না
        if not is_user_premium and i >= 2:
            break
        
        # ইনলাইন রেজাল্ট তৈরি
        results.append(types.InlineQueryResultArticle(
            title=f"{m['title']} ({m['year']}) [{m['lang']}]",
            input_message_content=types.InputTextMessageContent(m['link']) # এখানে পুরো মেসেজটি লিংক হিসেবে যাচ্ছে
        ))

    # যদি কোনো ফলাফল না পাওয়া যায়, ব্যবহারকারীকে মেসেজ পাঠানো হবে
    if not results:
        btns = InlineKeyboardMarkup([
            [InlineKeyboardButton("ভুল নাম লিখেছি", callback_data=f"nf_{iq.from_user.id}_wrong")],
            [InlineKeyboardButton("এখনো আসেনি", callback_data=f"nf_{iq.from_user.id}_notyet")],
            [InlineKeyboardButton("আপলোড আছে", callback_data=f"nf_{iq.from_user.id}_exists")],
            [InlineKeyboardButton("শিগগির আসবে", callback_data=f"nf_{iq.from_user.id}_soon")]
        ])
        # ইনলাইন কোয়েরির জন্য সরাসরি মেসেজ পাঠানো যায় না, তাই এটি কাজ করবে না।
        # এর পরিবর্তে ইনলাইন রেজাল্টে "No results found" দেখানো উচিত।
        # কিন্তু আপনার বর্তমান লজিক অনুযায়ী, এটি মেসেজ পাঠাচ্ছে।
        # যদি এই মেসেজ কাজ না করে, তবে আপনাকে ইনলাইন রেজাল্ট হিসেবে এটি দেখাতে হবে।
        try:
            await c.send_message(iq.from_user.id, f"❗ মুভি পাওয়া যায়নি।\nআপনার সার্চ: `{query}`", reply_markup=btns)
            logging.info(f"Sent 'movie not found' message to {iq.from_user.id}")
        except Exception as e:
            logging.error(f"Error sending 'movie not found' message to {iq.from_user.id}: {e}")
            # একটি বিকল্প হিসেবে আপনি একটি খালি বা "Not Found" রেজাল্ট পাঠাতে পারেন
            # results.append(types.InlineQueryResultArticle(
            #     title="কোনো মুভি পাওয়া যায়নি",
            #     input_message_content=types.InputTextMessageContent(f"আপনার সার্চ: '{query}' এর জন্য কোনো মুভি পাওয়া যায়নি।")
            # ))
    
    await iq.answer(results, cache_time=1)


# --- ক্যলব্যাক হ্যান্ডলার (অ্যাডমিন রেসপন্স) ---
@bot.on_callback_query()
async def callback_handler(c, cb: types.CallbackQuery):
    logging.info(f"Callback query from {cb.from_user.username or cb.from_user.first_name} ({cb.from_user.id}): {cb.data}")
    
    # অ্যাডমিন চেক
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("শুধুমাত্র অ্যাডমিনরা এটি ব্যবহার করতে পারবেন।", show_alert=True)
        return

    # ডেটা পার্সিং
    try:
        _, uid_str, resp = cb.data.split("_")
        uid = int(uid_str)
    except ValueError:
        await cb.answer("ক্যালব্যাক ডেটা ভুল।", show_alert=True)
        logging.error(f"Malformed callback data: {cb.data}")
        return

    # রেসপন্স মেসেজ তৈরি
    msg = {
        "wrong": "আপনি ভুল নাম লিখেছেন। দয়া করে আবার চেষ্টা করুন।",
        "notyet": "এই মুভিটি এখনো আমাদের ডাটাবেসে নেই।",
        "exists": "মুভিটি আপলোড আছে, একটু ভালোভাবে সার্চ করুন।",
        "soon": "এই মুভিটি শিগগিরই আপলোড করা হবে।"
    }.get(resp, "ধন্যবাদ") # ডিফল্ট ধন্যবাদ মেসেজ

    try:
        await c.send_message(uid, msg)
        await cb.answer("ব্যবহারকারীকে জানানো হয়েছে।")
        logging.info(f"Sent callback response to user {uid}: {msg}")
    except Exception as e:
        await cb.answer("ব্যবহারকারীকে জানাতে সমস্যা হয়েছে।", show_alert=True)
        logging.error(f"Error sending callback message to user {uid}: {e}")


# --- 'buy' কমান্ড ---
@bot.on_message(filters.command("buy"))
async def buy_cmd(c, m: types.Message):
    await save_user(m.from_user) # 'buy' কমান্ড ব্যবহারকারী সেভ হবে
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("7 দিন - 50৳", callback_data="buy_7")],
        [InlineKeyboardButton("15 দিন - 80৳", callback_data="buy_15")],
        [InlineKeyboardButton("30 দিন - 120৳", callback_data="buy_30")],
    ])
    await m.reply(
        """💳 পেমেন্ট করতে নিচের বিকাশ/নগদ নাম্বার ব্যবহার করুন:
`01975123274`

প্ল্যান বেছে নিন এবং এডমিনকে জানান: @ctgmovies23""",
        reply_markup=btn
    )
    logging.info(f"'buy' command from {m.from_user.id}")

# --- প্রিমিয়াম প্রদান (অ্যাডমিন অনলি) ---
@bot.on_message(filters.command("grant") & filters.user(ADMIN_ID))
async def grant(c, m: types.Message):
    await save_user(m.from_user) # অ্যাডমিনকেও সেভ করুন যদি না থাকে
    try:
        parts = m.text.split()
        if len(parts) != 3:
            await m.reply("ব্যবহারের নিয়ম: `/grant user_id days`")
            return

        uid_str = parts[1]
        days_str = parts[2]

        try:
            uid = int(uid_str)
            days = int(days_str)
        except ValueError:
            await m.reply("ব্যবহারের নিয়ম: `/grant user_id days` (দিন এবং user_id সংখ্যা হতে হবে)")
            return

        expiry = datetime.utcnow() + timedelta(days=days)
        users.update_one({"_id": uid}, {"$set": {"is_premium": True, "expiry": expiry}}, upsert=True)
        await m.reply(f"✅ প্রিমিয়াম প্রদান করা হয়েছে। ব্যবহারকারী ID: {uid}, মেয়াদ: {days} দিন।")
        logging.info(f"Granted premium to user {uid} for {days} days by admin {m.from_user.id}")
        
        # প্রিমিয়াম ব্যবহারকারীকে জানান
        try:
            await c.send_message(uid, f"🥳 অভিনন্দন! আপনি {days} দিনের জন্য প্রিমিয়াম সুবিধা পেয়েছেন। আপনার প্রিমিয়াম সাবস্ক্রিপশন {expiry.strftime('%Y-%m-%d %H:%M:%S UTC')} পর্যন্ত বৈধ থাকবে।")
        except Exception as e:
            logging.warning(f"Could not send premium notification to user {uid}: {e}")

    except Exception as e:
        logging.error(f"Error granting premium by admin {m.from_user.id}: {e}")
        await m.reply("প্রিমিয়াম দিতে সমস্যা হয়েছে।")

# --- মুভি ডিলিট কমান্ড ---
@bot.on_message(filters.command("delete_movie") & filters.user(ADMIN_ID))
async def delete_movie(c, m: types.Message):
    await save_user(m.from_user)
    try:
        title = m.text.split(maxsplit=1)[1]
        result = movies.delete_one({"title": {"$regex": f"^{re.escape(title)}$", "$options": "i"}}) # regex escape যোগ করা হয়েছে
        if result.deleted_count > 0:
            await m.reply(f"🗑️ ডিলিট করা হয়েছে: {result.deleted_count} টি মুভি।")
            logging.info(f"Deleted movie '{title}' by admin {m.from_user.id}")
        else:
            await m.reply(f"'{title}' নামের কোনো মুভি পাওয়া যায়নি।")
            logging.info(f"Attempted to delete non-existent movie '{title}' by admin {m.from_user.id}")
    except IndexError:
        await m.reply("ব্যবহারের নিয়ম: `/delete_movie [মুভির নাম]`")
    except Exception as e:
        logging.error(f"Error deleting movie by admin {m.from_user.id}: {e}")
        await m.reply("মুভি ডিলিট করতে সমস্যা হয়েছে।")

# --- সব মুভি ডিলিট কমান্ড ---
@bot.on_message(filters.command("delete_all_movies") & filters.user(ADMIN_ID))
async def delete_all_movies(c, m: types.Message):
    await save_user(m.from_user)
    try:
        movies.drop()
        await m.reply("🗑️ সব মুভি ডিলিট করা হয়েছে।")
        logging.info(f"All movies deleted by admin {m.from_user.id}")
    except Exception as e:
        logging.error(f"Error deleting all movies by admin {m.from_user.id}: {e}")
        await m.reply("সব মুভি ডিলিট করতে সমস্যা হয়েছে।")

# --- স্ট্যাটাস কমান্ড ---
@bot.on_message(filters.command("stats") & filters.user(ADMIN_ID))
async def stats(c, m: types.Message):
    await save_user(m.from_user)
    try:
        total_users = users.count_documents({})
        premium_users = users.count_documents({"is_premium": True})
        total_movies = movies.count_documents({})
        await m.reply(f"👤 মোট ব্যবহারকারী: {total_users}\n💎 প্রিমিয়াম ব্যবহারকারী: {premium_users}\n🎬 মোট মুভি: {total_movies}")
        logging.info(f"Stats requested by admin {m.from_user.id}")
    except Exception as e:
        logging.error(f"Error fetching stats by admin {m.from_user.id}: {e}")
        await m.reply("স্ট্যাটাস পেতে সমস্যা হয়েছে।")

# --- 'start' কমান্ড (নতুন যোগ করা হয়েছে) ---
@bot.on_message(filters.command("start") & filters.private)
async def start_command(c, m: types.Message):
    await save_user(m.from_user) # 'start' কমান্ড ব্যবহারকারী সেভ হবে
    await m.reply_text(
        "👋 **স্বাগতম!**\n\n"
        "আমি একটি অটোমেটিক মুভি বট। আপনি আপনার পছন্দের মুভিটি "
        "ইনলাইন মোডে সার্চ করে পেতে পারেন।\n\n"
        "আমার ব্যবহারবিধি:\n"
        "১. যেকোনো চ্যাটে `@YourBotUsername movie name` লিখে সার্চ করুন।\n"
        "২. যদি মুভিটি ডাটাবেসে থাকে, তাহলে আপনি ফলাফল দেখতে পাবেন।\n"
        "৩. আরও তথ্যের জন্য `/help` কমান্ড ব্যবহার করুন।"
    )
    logging.info(f"'start' command from {m.from_user.id}")

# --- 'help' কমান্ড (নতুন যোগ করা হয়েছে) ---
@bot.on_message(filters.command("help") & filters.private)
async def help_command(c, m: types.Message):
    await save_user(m.from_user) # 'help' কমান্ড ব্যবহারকারী সেভ হবে
    await m.reply_text(
        "ℹ️ **সাহায্য মেনু:**\n\n"
        "**মুভি সার্চ:**\n"
        "যেকোনো চ্যাটে `@YourBotUsername [মুভির নাম]` লিখে সার্চ করুন।\n"
        "উদাহরণ: `@YourBotUsername Pathaan`\n\n"
        "**প্রিমিয়াম প্ল্যান:**\n"
        "`/buy` কমান্ড ব্যবহার করে প্রিমিয়াম প্ল্যান সম্পর্কে জানতে পারবেন।\n\n"
        "**অ্যাডমিন কমান্ড (শুধুমাত্র অ্যাডমিনদের জন্য):**\n"
        "`/grant [user_id] [days]` - ব্যবহারকারীকে প্রিমিয়াম অ্যাক্সেস দিন।\n"
        "`/delete_movie [মুভির নাম]` - ডাটাবেস থেকে একটি মুভি ডিলিট করুন।\n"
        "`/delete_all_movies` - সব মুভি ডিলিট করুন।\n"
        "`/stats` - বর্তমান ব্যবহারকারী এবং মুভির পরিসংখ্যান দেখুন।"
    )
    logging.info(f"'help' command from {m.from_user.id}")

# --- বট স্টার্ট করা ---
if __name__ == "__main__":
    logging.info("Starting Flask server...")
    Thread(target=run_flask).start() # Flask সার্ভার একটি পৃথক থ্রেডে শুরু হবে

    logging.info("Starting Pyrogram bot...")
    bot.run_forever() # বটকে অনন্তকাল ধরে চালু রাখা হবে
