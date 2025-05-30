# 🎬 MovieAutoBot – Telegram Movie Search & Premium Access Bot

MovieAutoBot হল একটি উন্নত টেলিগ্রাম বট, যা আপনার প্রাইভেট মুভি চ্যানেল থেকে অটো-মুভি সংগ্রহ করে ব্যবহারকারীদের সার্চ রেজাল্ট দেয়, ভুল বানানেও মিল খুঁজে পায়, প্রিমিয়াম সাবস্ক্রিপশন সাপোর্ট করে এবং গ্রুপ ও প্রাইভেট চ্যাটে সমানভাবে কাজ করে।

---

## 🚀 Features

- ✅ অটো Movie Save from Private Channel
- 🔍 Advanced MongoDB fuzzy Search (Regex-based)
- ⏱️ Auto-delete movie results after 5 minutes
- 🧠 ভুল নামেও সার্চ রেজাল্ট দেখায় (e.g. "jawr 2" → "Jawan 2")
- 🔘 Inline Buttons (Watch Online / Download / Request)
- 🛒 Bkash/Nagad-based Premium Access
- 👥 Works in both Groups and Private Chat
- 👨‍💼 Admin Panel (via Flask Dashboard - optional)
- 🔔 New Movie Notification to Subscribers
- 📊 User Stats Tracking via MongoDB

---

## ⚙️ Deployment Instructions

### 🧩 Prerequisites

- Python 3.10+
- MongoDB Database
- A Telegram Bot Token
- A Telegram Channel (Private or Public) for movie posting

### 🛠️ Install Dependencies

```bash
pip install -r requirements.txt
