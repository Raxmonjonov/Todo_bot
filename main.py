import asyncio
import html
import logging
import os

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = "todo.db"

dp = Dispatcher()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.commit()


async def add_task(user_id: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO tasks (user_id, text) VALUES (?, ?)", (user_id, text))
        await db.commit()


async def get_tasks(user_id: int) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, text, done FROM tasks WHERE user_id = ? ORDER BY id", (user_id,)
        ) as cursor:
            return await cursor.fetchall()


async def toggle_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET done = 1 - done WHERE id = ?", (task_id,))
        await db.commit()


async def delete_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()


async def clear_tasks(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tasks WHERE user_id = ?", (user_id,))
        await db.commit()


def tasks_keyboard(tasks):
    builder = InlineKeyboardBuilder()
    for task_id, text, done in tasks:
        mark = "✅" if done else "⬜️"
        builder.button(text=f"{mark} {text}", callback_data=f"toggle:{task_id}")
        builder.button(text="🗑", callback_data=f"del:{task_id}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🧹 Hammasini tozalash", callback_data="clear_all"))
    return builder.as_markup()


def header(tasks) -> str:
    done = sum(1 for _, _, d in tasks if d)
    return f"🗒 <b>Vazifalar</b> (bajarilgan {done}/{len(tasks)}):"


async def show_tasks(message: Message, user_id: int):
    tasks = await get_tasks(user_id)
    if not tasks:
        await message.answer("📭 Vazifalar yo'q. Yangi vazifani yozib yuboring.")
        return
    await message.answer(header(tasks), reply_markup=tasks_keyboard(tasks))


async def refresh(callback: CallbackQuery):
    tasks = await get_tasks(callback.from_user.id)
    try:
        if tasks:
            await callback.message.edit_text(header(tasks), reply_markup=tasks_keyboard(tasks))
        else:
            await callback.message.edit_text("📭 Vazifalar yo'q.")
    except TelegramBadRequest:
        pass


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "✅ <b>Todo Bot</b>ga xush kelibsiz!\n\n"
        "• Vazifa qo'shish — uni yozib yuboring\n"
        "• /list — vazifalar ro'yxati\n"
        "• ⬜️/✅ — bajarilgan deb belgilash\n"
        "• 🗑 — o'chirish   • /clear — hammasini o'chirish"
    )


@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "✅ <b>Todo Bot</b> — yordam\n\n"
        "• Matn yuboring → vazifa qo'shiladi\n"
        "• /list — ro'yxat\n"
        "• ⬜️/✅ tugmasi — holatni o'zgartirish\n"
        "• 🗑 — bittasini o'chirish\n"
        "• /clear — barcha vazifalarni o'chirish"
    )


@dp.message(Command("list"))
async def list_cmd(message: Message):
    await show_tasks(message, message.from_user.id)


@dp.message(Command("clear"))
async def clear_cmd(message: Message):
    await clear_tasks(message.from_user.id)
    await message.answer("🧹 Barcha vazifalar o'chirildi.")


@dp.message(F.text)
async def add(message: Message):
    text = message.text.strip()
    await add_task(message.from_user.id, text)
    await message.answer(f"➕ Qo'shildi: <b>{html.escape(text)}</b>")
    await show_tasks(message, message.from_user.id)


@dp.callback_query(F.data.startswith("toggle:"))
async def toggle(callback: CallbackQuery):
    await toggle_task(int(callback.data.split(":")[1]))
    await callback.answer("Holat o'zgartirildi")
    await refresh(callback)


@dp.callback_query(F.data.startswith("del:"))
async def delete(callback: CallbackQuery):
    await delete_task(int(callback.data.split(":")[1]))
    await callback.answer("O'chirildi")
    await refresh(callback)


@dp.callback_query(F.data == "clear_all")
async def clear_all(callback: CallbackQuery):
    await clear_tasks(callback.from_user.id)
    await callback.answer("Hammasi tozalandi")
    try:
        await callback.message.edit_text("📭 Vazifalar yo'q.")
    except TelegramBadRequest:
        pass


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi. .env faylini to'ldiring.")
    await init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
