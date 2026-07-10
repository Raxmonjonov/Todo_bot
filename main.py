"""
✅ Todo Bot — Production-Ready
Aiogram 3.x + aiosqlite + Throttling + Categories + Reminders
"""

import asyncio
import html
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    Message,
    TelegramObject,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# ─── Konfiguratsiya ────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DB_PATH = os.getenv("DB_PATH", "todo.db")
THROTTLE_RATE = float(os.getenv("THROTTLE_RATE", "0.5"))
MAX_TASK_LENGTH = int(os.getenv("MAX_TASK_LENGTH", "500"))

# ─── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("todo-bot")

# ─── Kategoriyalar ─────────────────────────────────────────────────
CATEGORIES = {
    "work": {"name": "💼 Ish", "emoji": "💼"},
    "personal": {"name": "👤 Shaxsiy", "emoji": "👤"},
    "study": {"name": "📚 O'qish", "emoji": "📚"},
    "health": {"name": "💪 Salomatlik", "emoji": "💪"},
    "shopping": {"name": "🛒 Xarid", "emoji": "🛒"},
    "other": {"name": "📌 Boshqa", "emoji": "📌"},
}

PRIORITY_LEVELS = {
    "low": {"name": "Past", "emoji": "🟢", "order": 3},
    "medium": {"name": "O'rta", "emoji": "🟡", "order": 2},
    "high": {"name": "Yuqori", "emoji": "🔴", "order": 1},
}


# ─── Database ────────────────────────────────────────────────────────
async def init_db():
    """Bazani ishga tushirish va jadvallarni yaratish."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'other',
                priority TEXT NOT NULL DEFAULT 'medium',
                done INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_id INTEGER,
                text TEXT NOT NULL,
                remind_at TIMESTAMP NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
    logger.info("Database muvaffaqiyatli ishga tushirildi: %s", DB_PATH)


async def save_user(user_id: int, username: str | None, full_name: str | None):
    """Foydalanuvchini bazaga saqlash."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
            (user_id, username, full_name),
        )
        await db.commit()


# ─── Task CRUD ──────────────────────────────────────────────────────
async def add_task(user_id: int, text: str, category: str = "other", priority: str = "medium") -> int:
    """Yangi vazifa qo'shish."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO tasks (user_id, text, category, priority) VALUES (?, ?, ?, ?)",
            (user_id, text, category, priority),
        )
        await db.commit()
        task_id = cursor.lastrowid
    logger.info("Yangi vazifa #%s — user %s: %s", task_id, user_id, text[:50])
    return task_id


async def get_tasks(user_id: int, category: str | None = None, show_done: bool = True) -> list[tuple]:
    """Foydalanuvchining vazifalarini olish."""
    async with aiosqlite.connect(DB_PATH) as db:
        if category:
            query = "SELECT id, text, category, priority, done, created_at FROM tasks WHERE user_id = ? AND category = ?"
            params = (user_id, category)
        else:
            query = "SELECT id, text, category, priority, done, created_at FROM tasks WHERE user_id = ?"
            params = (user_id,)

        if not show_done:
            query += " AND done = 0"
        query += " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END, id"

        async with db.execute(query, params) as cursor:
            return await cursor.fetchall()


async def get_task_by_id(task_id: int, user_id: int) -> tuple | None:
    """Bitta vazifani olish."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, text, category, priority, done, created_at FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ) as cursor:
            return await cursor.fetchone()


async def toggle_task(task_id: int, user_id: int) -> bool:
    """Vazifa holatini o'zgartirish."""
    async with aiosqlite.connect(DB_PATH) as db:
        task = await db.execute_fetchall(
            "SELECT done FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
        )
        if not task:
            return False
        new_status = 1 - task[0][0]
        completed_at = datetime.now().isoformat() if new_status else None
        await db.execute(
            "UPDATE tasks SET done = ?, completed_at = ? WHERE id = ? AND user_id = ?",
            (new_status, completed_at, task_id, user_id),
        )
        await db.commit()
    return True


async def delete_task(task_id: int, user_id: int) -> bool:
    """Vazifani o'chirish."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def clear_tasks(user_id: int, only_done: bool = False) -> int:
    """Vazifalarni tozalash."""
    async with aiosqlite.connect(DB_PATH) as db:
        if only_done:
            cursor = await db.execute(
                "DELETE FROM tasks WHERE user_id = ? AND done = 1", (user_id,)
            )
        else:
            cursor = await db.execute("DELETE FROM tasks WHERE user_id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount


async def get_task_stats(user_id: int) -> dict:
    """Vazifalar statistikasi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*), SUM(CASE WHEN done=1 THEN 1 ELSE 0 END) FROM tasks WHERE user_id = ?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            total, done = row[0], row[1] or 0
        async with db.execute(
            "SELECT category, COUNT(*) FROM tasks WHERE user_id = ? AND done = 0 GROUP BY category",
            (user_id,),
        ) as cur:
            by_category = await cur.fetchall()
    return {"total": total, "done": done, "pending": total - done, "by_category": by_category}


# ─── Reminder CRUD ──────────────────────────────────────────────────
async def add_reminder(user_id: int, text: str, remind_at: str, task_id: int | None = None) -> int:
    """Eslatma qo'shish."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO reminders (user_id, text, remind_at, task_id) VALUES (?, ?, ?, ?)",
            (user_id, text, remind_at, task_id),
        )
        await db.commit()
        return cursor.lastrowid


async def get_pending_reminders() -> list[tuple]:
    """Vaqti kelgan eslatmalarni olish."""
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, text, remind_at FROM reminders WHERE done = 0 AND remind_at <= ?",
            (now,),
        ) as cursor:
            return await cursor.fetchall()


async def mark_reminder_done(reminder_id: int):
    """Eslatmani bajarilgan deb belgilash."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
        await db.commit()


async def get_user_reminders(user_id: int) -> list[tuple]:
    """Foydalanuvchining eslatmalarini olish."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, text, remind_at, done FROM reminders WHERE user_id = ? ORDER BY remind_at DESC LIMIT 10",
            (user_id,),
        ) as cursor:
            return await cursor.fetchall()


# ─── Throttling Middleware ──────────────────────────────────────────
class ThrottlingMiddleware:
    """Foydalanuvchilarning juda tez-tez xabar yuborishini cheklaydi."""

    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit
        self.last_call: dict[int, float] = defaultdict(float)

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user_id = getattr(getattr(event, "from_user", None), "id", None)
        if user_id is None:
            return await handler(event, data)

        now = time.monotonic()
        if now - self.last_call[user_id] < self.rate_limit:
            if isinstance(event, Message):
                await event.answer("⚠️ Iltimos, biroz kutib turing...")
            elif isinstance(event, CallbackQuery):
                await event.answer("⚠️ Iltimos, biroz kutib turing...", show_alert=False)
            return None

        self.last_call[user_id] = now
        return await handler(event, data)


# ─── Error Handling Middleware ──────────────────────────────────────
class ErrorMiddleware:
    """Barcha xatolarni ushlaydi va logging qiladi."""

    async def __call__(self, handler, event: TelegramObject, data: dict):
        try:
            return await handler(event, data)
        except TelegramBadRequest as e:
            logger.warning("TelegramBadRequest: %s", e)
        except TelegramNetworkError as e:
            logger.error("TelegramNetworkError: %s", e)
        except Exception as e:
            logger.exception("Kutilmagan xatolik: %s", e)
        return None


# ─── FSM Holatlar ────────────────────────────────────────────────────
class AddTask(StatesGroup):
    text = State()
    category = State()
    priority = State()


class AddReminder(StatesGroup):
    text = State()
    datetime = State()


# ─── Yordamchi funksiyalar ─────────────────────────────────────────
def escape(text: str) -> str:
    """HTML xavfsiz matn."""
    return html.escape(str(text)) if text else ""


def format_datetime(dt_str: str) -> str:
    """Sanani formatlash."""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return dt_str or "—"


# ─── Keyboardlar ────────────────────────────────────────────────────
def main_keyboard() -> InlineKeyboardMarkup:
    """Asosiy menyu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Vazifalarim", callback_data="tasks")
    builder.button(text="➕ Yangi vazifa", callback_data="add_task")
    builder.button(text="🔍 Qidirish", callback_data="search")
    builder.button(text="⏰ Eslatmalar", callback_data="reminders")
    builder.button(text="📊 Statistika", callback_data="stats")
    builder.adjust(2)
    return builder.as_markup()


def tasks_keyboard(tasks: list[tuple]) -> InlineKeyboardMarkup:
    """Vazifalar ro'yxati klaviaturasi."""
    builder = InlineKeyboardBuilder()
    for task_id, text, category, priority, done, created_at in tasks:
        cat_emoji = CATEGORIES.get(category, {}).get("emoji", "📌")
        pri_emoji = PRIORITY_LEVELS.get(priority, {}).get("emoji", "🟡")
        mark = "✅" if done else "⬜️"
        display = text[:30] + "..." if len(text) > 30 else text
        builder.button(
            text=f"{mark} {pri_emoji}{cat_emoji} {display}",
            callback_data=f"toggle:{task_id}",
        )
        builder.button(text="🗑", callback_data=f"del:{task_id}")
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="🧹 Bajarilganlarni tozalash", callback_data="clear_done"),
        InlineKeyboardButton(text="🗑 Hammasini tozalash", callback_data="clear_all"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main"))
    return builder.as_markup()


def category_keyboard() -> InlineKeyboardMarkup:
    """Kategoriyalar klaviaturasi."""
    builder = InlineKeyboardBuilder()
    for key, cat in CATEGORIES.items():
        builder.button(text=f"{cat['emoji']} {cat['name']}", callback_data=f"cat:{key}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main"))
    return builder.as_markup()


def priority_keyboard() -> InlineKeyboardMarkup:
    """Muhimlik darajasi klaviaturasi."""
    builder = InlineKeyboardBuilder()
    for key, pri in PRIORITY_LEVELS.items():
        builder.button(text=f"{pri['emoji']} {pri['name']}", callback_data=f"pri:{key}")
    builder.adjust(3)
    return builder.as_markup()


def admin_keyboard() -> InlineKeyboardMarkup:
    """Admin klaviaturasi."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Umumiy statistika", callback_data="admin:stats")
    builder.button(text="👥 Foydalanuvchilar", callback_data="admin:users")
    builder.button(text="📋 Vazifalar soni", callback_data="admin:task_count")
    builder.button(text="🔄 Yangilash", callback_data="admin:refresh")
    builder.adjust(1)
    return builder.as_markup()


# ─── Router ──────────────────────────────────────────────────────────
router = Router()


# ─── Asosiy Buyruqlar ──────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Botni ishga tushirish."""
    await state.clear()
    await save_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )
    text = (
        f"✅ <b>Todo Bot</b>ga xush kelibsiz, {escape(message.from_user.first_name)}!\n\n"
        "Vazifalaringizni boshqaring 👇"
    )
    await message.answer(text, reply_markup=main_keyboard())
    logger.info("Yangi foydalanuvchi: %s (@%s)", message.from_user.id, message.from_user.username)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Yordam."""
    text = (
        "✅ <b>Todo Bot</b> — Yordam\n\n"
        "<b>Buyruqlar:</b>\n"
        "  /start — Asosiy menyu\n"
        "  /help — Shu yordam\n"
        "  /list — Vazifalar ro'yxati\n"
        "  /add — Yangi vazifa qo'shish\n"
        "  /clear — Hammani tozalash\n\n"
        "<b>Qanday ishlaydi:</b>\n"
        "  1️⃣ ➕ Yangi vazifa → Matn, kategoriya, muhimlik\n"
        "  2️⃣ ⬜️/✅ Bajarilgan deb belgilash\n"
        "  3️⃣ 🗑 O'chirish\n"
        "  4️⃣ ⏰ Eslatma qo'shish\n"
        "  5️⃣ 📊 Statistika\n\n"
        "🏷 <b>Kategoriyalar:</b> Ish, Shaxsiy, O'qish, Salomatlik, Xarid, Boshqa\n"
        "🔴🟡🟢 <b>Muhimlik:</b> Yuqori, O'rta, Past"
    )
    await message.answer(text)


@router.message(Command("list"))
async def cmd_list(message: Message):
    """Vazifalar ro'yxati."""
    await _show_tasks(message, message.from_user.id)


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    """Yangi vazifa qo'shish (buyruq orqali)."""
    await state.set_state(AddTask.text)
    await message.answer(
        "📝 <b>Yangi vazifa</b>\n\n"
        "Vazifa matnini kiriting:\n"
        "<i>(/bekor — bekor qilish)</i>"
    )


@router.message(Command("clear"))
async def cmd_clear(message: Message):
    """Barcha vazifalarni o'chirish."""
    count = await clear_tasks(message.from_user.id)
    await message.answer(f"🧹 {count} ta vazifa o'chirildi.")


@router.message(Command("bekor"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Amalni bekor qilish."""
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        await message.answer("❌ Bekor qilindi.\n\nAsosiy menyu: /start")
    else:
        await message.answer("Bekor qilinadigan amal yo'q.\n\nMenyu: /start")


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Admin panel."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Sizda admin huquqi yo'q.")
        return
    await message.answer("🔧 <b>Admin Panel</b>", reply_markup=admin_keyboard())


# ─── Callback Handlerlar ────────────────────────────────────────────
@router.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery):
    """Asosiy menyuga qaytish."""
    await callback.answer()
    try:
        await callback.message.edit_text(
            "✅ <b>Todo Bot</b>\n\nVazifalaringizni boshqaring 👇",
            reply_markup=main_keyboard(),
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "tasks")
async def cb_tasks(callback: CallbackQuery):
    """Vazifalar ro'yxati."""
    await callback.answer()
    tasks = await get_tasks(callback.from_user.id)
    if not tasks:
        await callback.message.edit_text(
            "📭 Vazifalar yo'q.\n\n➕ Yangi vazifa qo'shing!",
            reply_markup=InlineKeyboardBuilder()
            .button(text="➕ Yangi vazifa", callback_data="add_task")
            .button(text="⬅️ Orqaga", callback_data="back_main")
            .adjust(1)
            .as_markup(),
        )
        return
    await callback.message.edit_text(
        _tasks_header(tasks),
        reply_markup=tasks_keyboard(tasks),
    )


@router.callback_query(F.data == "add_task")
async def cb_add_task(callback: CallbackQuery, state: FSMContext):
    """Yangi vazifa qo'shish."""
    await callback.answer()
    await state.set_state(AddTask.text)
    await callback.message.edit_text(
        "📝 <b>Yangi vazifa</b>\n\n"
        "Vazifa matnini kiriting:\n"
        "<i>(/bekor — bekor qilish)</i>"
    )


@router.callback_query(F.data == "search")
async def cb_search(callback: CallbackQuery):
    """Qidirish."""
    await callback.answer()
    await callback.message.edit_text(
        "🔍 <b>Qidirish</b>\n\nQidiriladigan so'zni yozing:",
        reply_markup=InlineKeyboardBuilder()
        .button(text="⬅️ Orqaga", callback_data="back_main")
        .as_markup(),
    )


@router.callback_query(F.data == "reminders")
async def cb_reminders(callback: CallbackQuery):
    """Eslatmalar ro'yxati."""
    await callback.answer()
    reminders = await get_user_reminders(callback.from_user.id)
    if not reminders:
        await callback.message.edit_text(
            "⏰ Eslatmalar yo'q.\n\nVazifaga eslatma qo'shish uchun vazifani tanlang.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="⬅️ Orqaga", callback_data="back_main")
            .as_markup(),
        )
        return
    lines = ["⏰ <b>Oxirgi eslatmalar:</b>\n"]
    for rid, text, remind_at, done in reminders:
        status = "✅" if done else "⏳"
        lines.append(f"  {status} {escape(text[:40])}\n  📅 {format_datetime(remind_at)}\n")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardBuilder()
        .button(text="⬅️ Orqaga", callback_data="back_main")
        .as_markup(),
    )


@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    """Statistika."""
    await callback.answer()
    stats = await get_task_stats(callback.from_user.id)
    lines = [
        "📊 <b>Statistika</b>\n",
        f"📋 Jami vazifalar: {stats['total']}",
        f"✅ Bajarilgan: {stats['done']}",
        f"⏳ Kutilayotgan: {stats['pending']}",
    ]
    if stats["by_category"]:
        lines.append("\n🏷 <b>Kategoriyalar bo'yicha:</b>")
        for cat, count in stats["by_category"]:
            cat_info = CATEGORIES.get(cat, {})
            lines.append(f"  {cat_info.get('emoji', '📌')} {cat_info.get('name', cat)}: {count}")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardBuilder()
        .button(text="⬅️ Orqaga", callback_data="back_main")
        .as_markup(),
    )


# ─── Vazifa Amallari ────────────────────────────────────────────────
@router.callback_query(F.data.startswith("toggle:"))
async def cb_toggle(callback: CallbackQuery):
    """Vazifa holatini o'zgartirish."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Xatolik", show_alert=True)
        return
    try:
        task_id = int(parts[1])
    except ValueError:
        await callback.answer("Xatolik", show_alert=True)
        return

    success = await toggle_task(task_id, callback.from_user.id)
    if not success:
        await callback.answer("Vazifa topilmadi", show_alert=True)
        return

    await callback.answer("Holat o'zgartirildi ✅")
    tasks = await get_tasks(callback.from_user.id)
    try:
        if tasks:
            await callback.message.edit_text(_tasks_header(tasks), reply_markup=tasks_keyboard(tasks))
        else:
            await callback.message.edit_text("📭 Vazifalar yo'q.\n\n➕ Yangi vazifa qo'shing!")
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("del:"))
async def cb_delete(callback: CallbackQuery):
    """Vazifani o'chirish."""
    parts = callback.data.split(":")
    if len(parts) != 2:
        await callback.answer("Xatolik", show_alert=True)
        return
    try:
        task_id = int(parts[1])
    except ValueError:
        await callback.answer("Xatolik", show_alert=True)
        return

    success = await delete_task(task_id, callback.from_user.id)
    if not success:
        await callback.answer("Vazifa topilmadi", show_alert=True)
        return

    await callback.answer("O'chirildi 🗑")
    tasks = await get_tasks(callback.from_user.id)
    try:
        if tasks:
            await callback.message.edit_text(_tasks_header(tasks), reply_markup=tasks_keyboard(tasks))
        else:
            await callback.message.edit_text("📭 Vazifalar yo'q.\n\n➕ Yangi vazifa qo'shing!")
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "clear_done")
async def cb_clear_done(callback: CallbackQuery):
    """Bajarilgan vazifalarni tozalash."""
    count = await clear_tasks(callback.from_user.id, only_done=True)
    await callback.answer(f"🧹 {count} ta vazifa tozalandi")
    tasks = await get_tasks(callback.from_user.id)
    try:
        if tasks:
            await callback.message.edit_text(_tasks_header(tasks), reply_markup=tasks_keyboard(tasks))
        else:
            await callback.message.edit_text("📭 Vazifalar yo'q.\n\n➕ Yangi vazifa qo'shing!")
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "clear_all")
async def cb_clear_all(callback: CallbackQuery):
    """Barcha vazifalarni tozalash."""
    count = await clear_tasks(callback.from_user.id)
    await callback.answer(f"🗑 {count} ta vazifa o'chirildi")
    try:
        await callback.message.edit_text(
            "📭 Vazifalar yo'q.\n\n➕ Yangi vazifa qo'shing!",
            reply_markup=InlineKeyboardBuilder()
            .button(text="⬅️ Orqaga", callback_data="back_main")
            .as_markup(),
        )
    except TelegramBadRequest:
        pass


# ─── FSM: Yangi vazifa qo'shish ────────────────────────────────────
@router.message(AddTask.text)
async def add_task_text(message: Message, state: FSMContext):
    """Vazifa matnini qabul qilish."""
    if not message.text or not message.text.strip():
        await message.answer("⚠️ Iltimos, matn kiriting:")
        return
    text = message.text.strip()
    if len(text) > MAX_TASK_LENGTH:
        await message.answer(f"❌ Matn juda uzun. Maksimal {MAX_TASK_LENGTH} belgi.")
        return
    await state.update_data(text=text)
    await state.set_state(AddTask.category)
    await message.answer(
        f"📝 <b>{escape(text)}</b>\n\n"
        "🏷 Kategoriyani tanlang:",
        reply_markup=category_keyboard(),
    )


@router.callback_query(F.data.startswith("cat:"), AddTask.category)
async def add_task_category(callback: CallbackQuery, state: FSMContext):
    """Kategoriyani tanlash."""
    category = callback.data.split(":")[1]
    if category not in CATEGORIES:
        await callback.answer("Noto'g'ri kategoriya", show_alert=True)
        return
    await state.update_data(category=category)
    await state.set_state(AddTask.priority)
    cat_name = CATEGORIES[category]["name"]
    await callback.answer(f"Kategoriya: {cat_name}")
    await callback.message.edit_text(
        f"🏷 <b>{cat_name}</b> tanlandi\n\n"
        "🔴 Muhimlik darajasini tanlang:",
        reply_markup=priority_keyboard(),
    )


@router.callback_query(F.data.startswith("pri:"), AddTask.priority)
async def add_task_priority(callback: CallbackQuery, state: FSMContext):
    """Muhimlik darajasini tanlash va vazifani saqlash."""
    priority = callback.data.split(":")[1]
    if priority not in PRIORITY_LEVELS:
        await callback.answer("Noto'g'ri daraja", show_alert=True)
        return

    data = await state.get_data()
    text = data.get("text", "")
    category = data.get("category", "other")

    task_id = await add_task(callback.from_user.id, text, category, priority)
    await state.clear()

    cat_info = CATEGORIES.get(category, {})
    pri_info = PRIORITY_LEVELS.get(priority, {})
    await callback.answer(f"✅ Vazifa qo'shildi!")
    await callback.message.edit_text(
        f"✅ <b>Vazifa qo'shildi!</b>\n\n"
        f"📝 {escape(text)}\n"
        f"🏷 {cat_info.get('emoji', '📌')} {cat_info.get('name', category)}\n"
        f"{pri_info.get('emoji', '🟡')} {pri_info.get('name', priority)}",
        reply_markup=InlineKeyboardBuilder()
        .button(text="📋 Vazifalarim", callback_data="tasks")
        .button(text="➕ Yana qo'shish", callback_data="add_task")
        .button(text="⬅️ Orqaga", callback_data="back_main")
        .adjust(1)
        .as_markup(),
    )


# ─── FSM: Matn qidirish ────────────────────────────────────────────
@router.message(F.text & ~F.text.startswith("/"))
async def search_tasks(message: Message):
    """Vazifalarni qidirish."""
    query = message.text.strip()
    if len(query) < 2:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, text, category, priority, done, created_at FROM tasks WHERE user_id = ? AND text LIKE ? ORDER BY id",
            (message.from_user.id, f"%{query}%"),
        ) as cursor:
            tasks = await cursor.fetchall()

    if not tasks:
        await message.answer(f"🔍 \"{escape(query)}\" — hech narsa topilmadi.")
        return

    builder = InlineKeyboardBuilder()
    for task_id, text, category, priority, done, _ in tasks:
        cat_emoji = CATEGORIES.get(category, {}).get("emoji", "📌")
        pri_emoji = PRIORITY_LEVELS.get(priority, {}).get("emoji", "🟡")
        mark = "✅" if done else "⬜️"
        display = text[:30] + "..." if len(text) > 30 else text
        builder.button(text=f"{mark} {pri_emoji}{cat_emoji} {display}", callback_data=f"toggle:{task_id}")
        builder.button(text="🗑", callback_data=f"del:{task_id}")
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main"))

    await message.answer(
        f"🔍 \"{escape(query)}\" — {len(tasks)} ta natija:",
        reply_markup=builder.as_markup(),
    )


# ─── Admin Handlerlar ───────────────────────────────────────────────
@router.callback_query(F.data.startswith("admin:"))
async def cb_admin(callback: CallbackQuery):
    """Admin callback handlerlari."""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    action = callback.data.split(":")[1]

    if action == "stats":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM tasks") as cur:
                total_tasks = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                total_users = (await cur.fetchone())[0]
        await callback.answer()
        await callback.message.edit_text(
            f"📊 <b>Umumiy statistika</b>\n\n"
            f"📋 Vazifalar: {total_tasks}\n"
            f"👥 Foydalanuvchilar: {total_users}",
            reply_markup=admin_keyboard(),
        )

    elif action == "users":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_id, username, full_name, created_at FROM users ORDER BY created_at DESC LIMIT 10"
            ) as cur:
                users = await cur.fetchall()
        lines = ["👥 <b>Oxirgi 10 ta foydalanuvchi:</b>\n"]
        for uid, uname, fname, created in users:
            lines.append(f"  👤 {escape(str(fname) if fname else 'Noma\'lum')} (@{uname or 'yo\'q'}) | {created}")
        await callback.answer()
        await callback.message.edit_text("\n".join(lines), reply_markup=admin_keyboard())

    elif action == "task_count":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_id, COUNT(*) as cnt FROM tasks GROUP BY user_id ORDER BY cnt DESC LIMIT 10"
            ) as cur:
                stats = await cur.fetchall()
        lines = ["📋 <b>Eng ko'p vazifali foydalanuvchilar:</b>\n"]
        for uid, cnt in stats:
            lines.append(f"  👤 ID:{uid} — {cnt} ta vazifa")
        await callback.answer()
        await callback.message.edit_text("\n".join(lines), reply_markup=admin_keyboard())

    elif action == "refresh":
        await callback.answer("🔄 Yangilandi")
        await callback.message.edit_text("🔧 <b>Admin Panel</b>", reply_markup=admin_keyboard())


# ─── EslatmalarChecker ─────────────────────────────────────────────
async def check_reminders(bot: Bot):
    """Eslatmalarni tekshirish va yuborish."""
    while True:
        try:
            reminders = await get_pending_reminders()
            for rid, user_id, text, remind_at in reminders:
                try:
                    await bot.send_message(
                        user_id,
                        f"⏰ <b>Eslatma!</b>\n\n{escape(text)}",
                    )
                    await mark_reminder_done(rid)
                    logger.info("Eslatma #%s yuborildi — user %s", rid, user_id)
                except Exception as e:
                    logger.error("Eslatma yuborilmadi (#%s): %s", rid, e)
        except Exception as e:
            logger.error("Eslatmalar tekshirishda xatolik: %s", e)
        await asyncio.sleep(60)


# ─── Yordamchi funksiyalar ─────────────────────────────────────────
def _tasks_header(tasks: list[tuple]) -> str:
    """Vazifalar sarlavhasi."""
    total = len(tasks)
    done = sum(1 for t in tasks if t[4])
    return f"📋 <b>Vazifalar</b> (bajarilgan {done}/{total}):"


# ─── Bot ishga tushirish ────────────────────────────────────────────
async def main():
    """Asosiy funksiya."""
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN topilmadi! .env faylini tekshiring.")
        raise RuntimeError("BOT_TOKEN topilmadi. .env faylini to'ldiring.")

    # Bazani ishga tushirish
    await init_db()

    # Bot yaratish
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    # Dispatcher yaratish
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware'larni qo'shish
    dp.message.middleware(ErrorMiddleware())
    dp.callback_query.middleware(ErrorMiddleware())
    dp.message.middleware(ThrottlingMiddleware(THROTTLE_RATE))
    dp.callback_query.middleware(ThrottlingMiddleware(THROTTLE_RATE))

    # Routerlarni ro'yxatdan o'tkazish
    dp.include_router(router)

    # Shutdown hook
    async def on_shutdown(bot: Bot):
        logger.info("Bot to'xtatilmoqda...")
        await bot.session.close()

    dp.shutdown.register(on_shutdown)

    # Eslatmalar checker'ni ishga tushirish
    asyncio.create_task(check_reminders(bot))

    # Botni ishga tushirish
    me = await bot.get_me()
    logger.info("🤖 Todo Bot ishga tushdi! (@%s)", me.username)
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Bot foydalanuvchi tomonidan to'xtatildi.")
    finally:
        await on_shutdown(bot)


if __name__ == "__main__":
    asyncio.run(main())
