# ✅ Todo Bot

Kundalik vazifalarni yozish, saqlash va o'chirish imkonini beruvchi Telegram bot.

## ✨ Imkoniyatlar
- Vazifa qo'shish (matn yuborish orqali)
- Vazifalar ro'yxatini ko'rish (`/list`)
- Bajarilgan deb belgilash (⬜️ / ✅)
- Vazifani o'chirish (🗑)
- Har bir foydalanuvchining vazifalari alohida saqlanadi (SQLite)

## 🛠 Texnologiyalar
- Python 3.11+
- [aiogram 3.x](https://docs.aiogram.dev/)
- [aiosqlite](https://pypi.org/project/aiosqlite/) — ma'lumotlar bazasi

## 🚀 O'rnatish

1. Kutubxonalarni o'rnating:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   pip install -r requirements.txt
   ```

2. `.env.example` dan nusxa olib `.env` yarating:
   ```
   BOT_TOKEN=...
   ```
   `BOT_TOKEN` ni [@BotFather](https://t.me/BotFather) dan oling.

3. Ishga tushiring:
   ```bash
   python main.py
   ```

## 💬 Foydalanish
- `/start` — botni ishga tushirish
- Vazifani yozib yuboring → ro'yxatga qo'shiladi
- `/list` — ro'yxatni ko'rish, tugmalar orqali belgilash yoki o'chirish
