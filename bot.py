import asyncio
import logging
import os
import shutil
import sys
import subprocess
import uuid
import json
from datetime import datetime, timedelta
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import MenuButtonCommands, BotCommand

# --- ⚙️ НАСТРОЙКИ ---
# Бот попробует взять токен из настроек сервера. Если не найдет — возьмет тот, что в кавычках.
TOKEN_ENV = os.getenv("BOT_TOKEN") 
API_TOKEN = TOKEN_ENV if TOKEN_ENV else '8188676725:AAESOxSODXSy3YRe7wGjA6kI-QjgCiL0Xjs'

# Папка для временных файлов
BASE_TEMP_DIR = "temp_work"
DATA_FILE = "bot_data.json"

# --- 🚀 ИНИЦИАЛИЗАЦИЯ ---
logging.basicConfig(level=logging.INFO)
if not API_TOKEN or "ВСТАВЬ" in API_TOKEN:
    print("❌ ОШИБКА: Токен не найден! Укажи BOT_TOKEN в настройках сервера или впиши в код.")
    # sys.exit() # Раскомментируй на сервере, чтобы бот не запускался без токена

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Словарь для хранения путей к файлам: {user_id: (file_path, dir_path)}
users_files = {}

# ═══════════════════════════════════════════════════════════════
# � FSM СОСТОЯНИЯ ДЛЯ АДМИН ПАНЕЛИ
# ═══════════════════════════════════════════════════════════════

class AdminStates(StatesGroup):
    waiting_plan_to_add = State()
    waiting_user_id_to_add = State()
    waiting_user_id_to_remove = State()
    waiting_user_id_to_block = State()
    waiting_user_id_to_unblock = State()

# ═══════════════════════════════════════════════════════════════
# �💳 СИСТЕМА ПОДПИСОК И АДМИНОВ
# ═══════════════════════════════════════════════════════════════

# Тарифные планы
PLANS = {
    "free": {
        "name": "Free",
        "max_creations": 3,
        "max_input_size": 10 * 1024,  # 10 KB
        "max_input_lines": 40,
        "max_output_size": 400 * 1024,  # 400 KB
        "price": "Бесплатно"
    },
    "pro": {
        "name": "Pro",
        "max_creations": 15,
        "max_input_size": 30 * 1024,  # 30 KB
        "max_input_lines": 100,
        "max_output_size": 10 * 1024 * 1024,  # 10 MB
        "price": "100 ⭐ / 30 грн / 65 руб"
    },
    "ultra": {
        "name": "Ultra",
        "max_creations": float('inf'),
        "max_input_size": 1024 * 1024,  # 1 MB
        "max_input_lines": float('inf'),
        "max_output_size": float('inf'),
        "price": "300 ⭐ / 70 грн / 165 руб"
    }
}

# Данные в памяти
class BotData:
    def __init__(self):
        self.admins = set()  # ID администраторов
        self.user_plans = {}  # {user_id: plan_name}
        self.user_creations = defaultdict(int)  # {user_id: count}
        self.user_join_time = {}  # {user_id: datetime}
        self.users_creating = set()  # user_ids создающих файлы сейчас
        self.request_queue = []  # очередь запросов
        self.processing = set()  # user_ids в обработке
        self.last_queue_check = datetime.now()
        self.timeout_count = {}  # {user_id: {date_str: count}}
        self.temp_blocked_users = {}  # {user_id: unblock_datetime}
        self.permanently_blocked_users = set()  # user_ids постоянно заблокированных
        self.load_data()
    
    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.admins = set(data.get("admins", []))
                    self.user_plans = data.get("user_plans", {})
                    self.user_join_time = {int(k): datetime.fromisoformat(v) 
                                          for k, v in data.get("user_join_time", {}).items()}
                    self.timeout_count = data.get("timeout_count", {})
                    self.temp_blocked_users = {int(k): datetime.fromisoformat(v)
                                              for k, v in data.get("temp_blocked_users", {}).items()}
                    self.permanently_blocked_users = set(data.get("permanently_blocked_users", []))
            except:
                pass
    
    def save_data(self):
        data = {
            "admins": list(self.admins),
            "user_plans": self.user_plans,
            "user_join_time": {k: v.isoformat() for k, v in self.user_join_time.items()},
            "timeout_count": self.timeout_count,
            "temp_blocked_users": {k: v.isoformat() for k, v in self.temp_blocked_users.items()},
            "permanently_blocked_users": list(self.permanently_blocked_users)
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    
    def get_user_plan(self, user_id: int) -> str:
        return self.user_plans.get(str(user_id), "free")
    
    def set_user_plan(self, user_id: int, plan: str):
        self.user_plans[str(user_id)] = plan
        self.save_data()
    
    def add_admin(self, user_id: int):
        self.admins.add(user_id)
        self.save_data()
    
    def remove_admin(self, user_id: int):
        self.admins.discard(user_id)
        self.save_data()
    
    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins
    
    def register_user(self, user_id: int):
        if user_id not in self.user_join_time:
            self.user_join_time[user_id] = datetime.now()
            self.save_data()
    
    def block_user(self, user_id: int):
        """Блокирует пользователя (удаляет его из системы)"""
        user_id_str = str(user_id)
        self.permanently_blocked_users.add(user_id)
        if user_id_str in self.user_plans:
            del self.user_plans[user_id_str]
        if user_id in self.user_join_time:
            del self.user_join_time[user_id]
        if user_id in self.user_creations:
            del self.user_creations[user_id]
        self.save_data()
    
    def unblock_user(self, user_id: int):
        """Разблокирует пользователя и восстанавливает его"""
        self.permanently_blocked_users.discard(user_id)
        if user_id not in self.user_join_time:
            self.user_join_time[user_id] = datetime.now()
        self.set_user_plan(user_id, "free")
        self.user_creations[user_id] = 0
        self.save_data()
    
    def add_timeout(self, user_id: int):
        """Добавляет таймаут пользователю и проверяет лимит"""
        today = datetime.now().strftime("%Y-%m-%d")
        user_id_str = str(user_id)
        
        if user_id_str not in self.timeout_count:
            self.timeout_count[user_id_str] = {}
        
        self.timeout_count[user_id_str][today] = self.timeout_count[user_id_str].get(today, 0) + 1
        count = self.timeout_count[user_id_str][today]
        
        self.save_data()
        return count
    
    def is_temp_blocked(self, user_id: int) -> bool:
        """Проверяет если ли временная блокировка"""
        if user_id in self.temp_blocked_users:
            unblock_time = self.temp_blocked_users[user_id]
            if datetime.now() < unblock_time:
                return True
            else:
                # Время разблокировки прошло
                del self.temp_blocked_users[user_id]
                self.save_data()
                return False
        return False
    
    def is_permanently_blocked(self, user_id: int) -> bool:
        """Проверяет если ли постоянная блокировка"""
        return user_id in self.permanently_blocked_users
    
    def block_temp(self, user_id: int):
        """Временно блокирует пользователя на 24 часа"""
        unblock_time = datetime.now() + timedelta(hours=24)
        self.temp_blocked_users[user_id] = unblock_time
        self.save_data()
    
    def check_queue(self):
        """Проверка очереди: обрабатываем максимум 15 запросов в минуту"""
        now = datetime.now()
        if (now - self.last_queue_check).total_seconds() < 4:
            return
        
        self.last_queue_check = now
        # Разрешаем примерно 15/60 = 0.25 запроса в секунду
        if self.request_queue and len(self.processing) < 15:
            user_id = self.request_queue.pop(0)
            self.processing.add(user_id)

bot_data = BotData()

# Добавляем основного администратора при первом запуске
if 8566608157 not in bot_data.admins:
    bot_data.add_admin(8566608157)

# Очистка мусора при старте
if os.path.exists(BASE_TEMP_DIR):
    shutil.rmtree(BASE_TEMP_DIR)
os.makedirs(BASE_TEMP_DIR, exist_ok=True)

# --- 📱 КЛАВИАТУРЫ ---

# Главное меню (внизу)
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🚀 Начать создание")],
        [KeyboardButton(text="💳 Премиум"), KeyboardButton(text="ℹ️ Инфо")],
        [KeyboardButton(text="📹 Тутор")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие..."
)

# Админ меню
admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🚀 Начать создание")],
        [KeyboardButton(text="💳 Премиум"), KeyboardButton(text="ℹ️ Инфо")],
        [KeyboardButton(text="📹 Тутор")],
        [KeyboardButton(text="📊 Админ панель"), KeyboardButton(text="👥 Управление")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие..."
)

# Клавиатура для заблокированного пользователя
blocked_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📞 Написать админу")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие..."
)

# Кнопка под сообщением для скачивания
def get_download_kb(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📂 Скачать файл", callback_data=f"get_file_{user_id}")]])

# Премиум клавиатура
premium_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💎 Pro (30 грн)", url="https://t.me/Visasai")],
    [InlineKeyboardButton(text="👑 Ultra (70 грн)", url="https://t.me/Visasai")]
])


# --- 🛡️ ФУНКЦИЯ БЕЗОПАСНОСТИ ---
def is_safe_code(code: str) -> bool:
    """Проверяет код на наличие опасных команд перед запуском."""
    code_lower = code.lower()
    
    # ⛔ ЧЕРНЫЙ СПИСОК (Запрещено)
    banned_keywords = [
        "import os", "from os",             # Доступ к системе
        "import sys", "from sys",           # Системные настройки
        "import shutil", "from shutil",     # Удаление файлов
        "import subprocess",                # Запуск процессов
        "input(",                           # Ожидание ввода (завесит бота)
        "eval(", "exec(",                   # Скрытый запуск кода
        "open(",                            # Открытие левых файлов
        "__import__",                       # Хитрый импорт
        "requests", "urllib", "aiohttp",    # Интернет (чтобы не дудосили)
        "while true", "while 1"             # Бесконечные циклы
    ]

    for word in banned_keywords:
        if word in code_lower:
            return False, word # Возвращаем запрещенное слово
            
    return True, None


# --- 🏗️ ФУНКЦИЯ ЗАПУСКА КОДА ---
async def execute_code(message: types.Message, task_dir: str, code_content: str):
    user_id = message.from_user.id
    
    # 0a. Проверка постоянной блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer(
            f"🚫 **Вы заблокированы навсегда**\n\n"
            f"Ваш аккаунт был удален администратором.\n"
            f"Обратитесь к админу для уточнения: https://t.me/Visasai"
        )
        shutil.rmtree(task_dir)
        return
    
    # 0b. Проверка временной блокировки - не создавать файлы, но бот работает
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(
                f"🚫 **Вы не можете создавать файлы**\n\n"
                f"Превышен лимит таймаутов (10+ за день).\n"
                f"Восстановление через: ~{hours_left} часов\n\n"
                f"Вы можете использовать другие функции бота! 💳"
            )
        shutil.rmtree(task_dir)
        return
    
    # 1. Проверка безопасности
    is_safe, banned_word = is_safe_code(code_content)
    if not is_safe:
        await message.answer(f"⛔ **Код заблокирован!**\nНайдена запрещенная команда: `{banned_word}`.\n\nВ целях безопасности запрещены: os, sys, input, интернет.", parse_mode="Markdown")
        shutil.rmtree(task_dir)
        return

    try:
        status_msg = await message.answer("⚙️ Проверка пройдена. Запускаю...")
        
        # Проверяем ограничения плана
        plan_name = bot_data.get_user_plan(user_id)
        plan = PLANS[plan_name]
        
        # Проверка размера входящего кода
        code_size = len(code_content.encode('utf-8'))
        code_lines = len(code_content.split('\n'))
        
        if code_size > plan["max_input_size"]:
            size_kb = code_size // 1024
            max_kb = plan["max_input_size"] // 1024
            await status_msg.edit_text(
                f"📦 Код слишком большой!\n"
                f"Ваш: {size_kb} KB, Лимит на {plan['name']}: {max_kb} KB\n\n"
                f"Обновите план чтобы увеличить лимит 💳"
            )
            shutil.rmtree(task_dir)
            return
        
        if code_lines > plan["max_input_lines"]:
            await status_msg.edit_text(
                f"📝 Код слишком длинный!\n"
                f"Строк: {code_lines}, Лимит на {plan['name']}: {plan['max_input_lines']}\n\n"
                f"Обновите план 💳"
            )
            shutil.rmtree(task_dir)
            return
        
        # Проверка кол-ва использований
        if bot_data.user_creations[user_id] >= plan["max_creations"]:
            await status_msg.edit_text(
                f"🚫 Вы исчерпали лимит на {plan['name']}!\n"
                f"Создано файлов: {bot_data.user_creations[user_id]}/{plan['max_creations']}\n\n"
                f"Обновите план для бесконечных созданий 💳"
            )
            shutil.rmtree(task_dir)
            return
        
        # 2. Запуск скрипта в отдельном процессе
        # timeout=30 секунд — максимум для обработки
        try:
            proc = subprocess.run(
                [sys.executable, "script.py"],
                cwd=task_dir,       
                capture_output=True,
                text=True,
                timeout=30          
            )
        except subprocess.TimeoutExpired:
            # Добавляем таймаут и проверяем лимит
            timeout_count = bot_data.add_timeout(user_id)
            
            await status_msg.edit_text(
                f"⏰ **Время вышло!**\n\n"
                f"Скрипт работал дольше 30 секунд и был остановлен.\n"
                f"Таймаутов за день: {timeout_count}/10"
            )
            
            # Если 10 таймаутов - блокируем на день
            if timeout_count >= 10:
                bot_data.block_temp(user_id)
                await message.answer(
                    f"🚫 **Вы заблокированы на 24 часа**\n\n"
                    f"Причина: Превышен лимит таймаутов (10+ за день).\n\n"
                    f"✅ Ваш тариф сохранен!\n"
                    f"После разблокировки все вернется в норму."
                )
            
            shutil.rmtree(task_dir)
            return

        if proc.returncode != 0:
            # ОШИБКА В КОДЕ ПОЛЬЗОВАТЕЛЯ
            err = proc.stderr[-800:] 
            # ⚠️ Выводим без Markdown, чтобы бот не падал от символов _ и *
            await status_msg.edit_text(f"⚠️ Ошибка в твоем коде:\n\n{err}")
            shutil.rmtree(task_dir) 
        else:
            # УСПЕХ: Ищем созданные файлы
            generated_files = [f for f in os.listdir(task_dir) if f != "script.py"]
            
            if generated_files:
                result_file = os.path.join(task_dir, generated_files[0])
                file_size = os.path.getsize(result_file)
                
                # Проверяем размер выходного файла
                if file_size > plan["max_output_size"]:
                    size_mb = file_size // (1024 * 1024)
                    max_mb = plan["max_output_size"] // (1024 * 1024) if plan["max_output_size"] != float('inf') else "∞"
                    await status_msg.edit_text(
                        f"📦 Выходной файл слишком большой!\n"
                        f"Размер: {size_mb} MB, Лимит на {plan['name']}: {max_mb} MB\n\n"
                        f"Обновите план 💳"
                    )
                    shutil.rmtree(task_dir)
                    return
                
                users_files[message.from_user.id] = (result_file, task_dir)
                bot_data.user_creations[user_id] += 1
                
                await status_msg.edit_text(
                    f"✅ Готово! Файл создан: {generated_files[0]}\n"
                    f"Использовано: {bot_data.user_creations[user_id]}/{plan['max_creations']}", 
                    reply_markup=get_download_kb(message.from_user.id)
                )
            else:
                await status_msg.edit_text("🤔 Код сработал без ошибок, но файл не создался.\nТы точно написал `doc.save(...)`?")
                shutil.rmtree(task_dir)

    except subprocess.TimeoutExpired:
        await status_msg.edit_text("⏰ Время вышло! Скрипт работал дольше 30 секунд.")
        shutil.rmtree(task_dir)
    except Exception as e:
        await status_msg.edit_text(f"❌ Системная ошибка: {e}")
        shutil.rmtree(task_dir)


# --- 📨 ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем постоянную блокировку
    if bot_data.is_permanently_blocked(user_id):
        await message.answer(
            f"🚫 **Вы заблокированы навсегда**\n\n"
            f"Ваш аккаунт был удален администратором.\n"
            f"Обратитесь к админу для уточнения: https://t.me/Visasai"
        )
        return
    
    bot_data.register_user(user_id)
    
    # Проверяем временную блокировку
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(
                f"🚫 **Вы временно заблокированы**\n\n"
                f"Превышен лимит таймаутов (10+ за день).\n"
                f"Восстановление через: ~{hours_left} часов\n\n"
                f"Вы можете связаться с админом для уточнения деталей.",
                reply_markup=blocked_kb,
                parse_mode="Markdown"
            )
            return
    
    # Выбираем клавиатуру в зависимости от прав
    kb = admin_kb if bot_data.is_admin(user_id) else main_kb
    
    await message.answer("👋 Привет! Я публичный генератор файлов.\nКидай код — получай результат.", reply_markup=kb)

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ У вас нет доступа к админ консоли.")
        return
    
    # Считаем активных пользователей
    total_users = len(bot_data.user_join_time)
    creating_now = len(bot_data.users_creating)
    in_queue = len(bot_data.request_queue)
    processing = len(bot_data.processing)
    
    # Подсчитываем план распределение
    plans_count = defaultdict(int)
    for plan in bot_data.user_plans.values():
        plans_count[plan] += 1
    plans_count["free"] = total_users - sum(plans_count.values())
    
    # Получаем список новых юзеров за последний час
    now = datetime.now()
    hour_ago = now - timedelta(hours=1)
    new_users = sum(1 for t in bot_data.user_join_time.values() if t > hour_ago)
    
    admin_text = (
        "📊 **АДМИН ПАНЕЛЬ**\n\n"
        f"👥 **Всего пользователей:** {total_users}\n"
        f"🆕 **Новых за час:** {new_users}\n\n"
        f"⚙️ **Сейчас обрабатывается:**\n"
        f"  • Создают файлы: {creating_now}\n"
        f"  • В очереди: {in_queue}\n"
        f"  • Обрабатываются: {processing}\n\n"
        f"💳 **Распределение по планам:**\n"
        f"  • Free: {plans_count['free']}\n"
        f"  • Pro: {plans_count['pro']}\n"
        f"  • Ultra: {plans_count['ultra']}\n"
    )
    
    await message.answer(admin_text, parse_mode="Markdown")

@dp.message(F.text == "📊 Админ панель")
async def button_admin_panel(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ Недостаточно прав")
        return
    
    # Считаем активных пользователей
    total_users = len(bot_data.user_join_time)
    creating_now = len(bot_data.users_creating)
    in_queue = len(bot_data.request_queue)
    processing = len(bot_data.processing)
    
    # Подсчитываем план распределение
    plans_count = defaultdict(int)
    for plan in bot_data.user_plans.values():
        plans_count[plan] += 1
    plans_count["free"] = total_users - sum(plans_count.values())
    
    # Получаем список новых юзеров за последний час
    now = datetime.now()
    hour_ago = now - timedelta(hours=1)
    new_users = sum(1 for t in bot_data.user_join_time.values() if t > hour_ago)
    
    admin_text = (
        "📊 **АДМИН ПАНЕЛЬ**\n\n"
        f"👥 **Всего пользователей:** {total_users}\n"
        f"🆕 **Новых за час:** {new_users}\n\n"
        f"⚙️ **Сейчас обрабатывается:**\n"
        f"  • Создают файлы: {creating_now}\n"
        f"  • В очереди: {in_queue}\n"
        f"  • Обрабатываются: {processing}\n\n"
        f"💳 **Распределение по планам:**\n"
        f"  • Free: {plans_count['free']}\n"
        f"  • Pro: {plans_count['pro']}\n"
        f"  • Ultra: {plans_count['ultra']}"
    )
    
    # Кнопки для управления
    manage_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Добавить премиум", callback_data="admin_add_premium")],
        [InlineKeyboardButton(text="❌ Забрать премиум", callback_data="admin_remove_premium")],
        [InlineKeyboardButton(text="🚫 Заблокировать пользователя", callback_data="admin_block_user")],
        [InlineKeyboardButton(text="✅ Разблокировать пользователя", callback_data="admin_unblock_user")]
    ])
    
    await message.answer(admin_text, parse_mode="Markdown", reply_markup=manage_kb)

@dp.message(F.text == "👥 Управление")
async def button_admin_manage(message: types.Message):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ Недостаточно прав")
        return
    
    manage_text = (
        "👥 **УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ**\n\n"
        "Используйте команды:\n\n"
        "💳 **Дать подписку:**\n"
        "`/admin_add_user <id> <план>`\n"
        "Планы: free, pro, ultra\n\n"
        "👤 **Сделать админом:**\n"
        "`/admin_add <id>`\n\n"
        "👤 **Убрать админа:**\n"
        "`/admin_remove <id>`\n\n"
        "Пример:\n"
        "`/admin_add_user 123456789 pro`\n"
        "`/admin_add 123456789`"
    )
    
    await message.answer(manage_text, parse_mode="Markdown")

@dp.message(F.text == "📞 Написать админу")
async def button_contact_admin(message: types.Message):
    user_id = message.from_user.id
    
    # Для постоянно заблокированных - отказываем
    if bot_data.is_permanently_blocked(user_id):
        await message.answer("🚫 Вы заблокированы навсегда и не можете использовать бота.")
        return
    
    # Проверяем если пользователь временно заблокирован
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            text = f"Привет! Меня заблокировали на {hours_left} часов. Причина блокировки: превышен лимит таймаутов (10+ запросов с таймаутом за день). ID: {user_id}"
    else:
        text = f"Привет админ! Мне нужна помощь. Мой ID: {user_id}"
    
    # Ссылка с автоматическим сообщением
    admin_contact = "Visasai"  # Telegram username админа
    tg_link = f"https://t.me/{admin_contact}?text={text.replace(' ', '%20')}"
    
    contact_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать админу", url=tg_link)]
    ])
    
    await message.answer(
        "📞 **Контакт с администратором**\n\n"
        "Нажмите кнопку ниже чтобы написать админу.\n"
        "Сообщение будет предзаполнено автоматически.",
        parse_mode="Markdown",
        reply_markup=contact_kb
    )

@dp.message(Command("admin_add"))
async def cmd_admin_add(message: types.Message):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ Недостаточно прав")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("❌ Используйте: /admin_add <user_id>")
            return
        
        target_id = int(parts[1])
        bot_data.add_admin(target_id)
        await message.answer(f"✅ Пользователь {target_id} стал администратором")
    except ValueError:
        await message.answer("❌ Неверный ID")

@dp.message(Command("admin_remove"))
async def cmd_admin_remove(message: types.Message):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ Недостаточно прав")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("❌ Используйте: /admin_remove <user_id>")
            return
        
        target_id = int(parts[1])
        bot_data.remove_admin(target_id)
        await message.answer(f"✅ Пользователь {target_id} больше не администратор")
    except ValueError:
        await message.answer("❌ Неверный ID")

@dp.message(Command("admin_add_user"))
async def cmd_admin_add_user(message: types.Message):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ Недостаточно прав")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 3:
            await message.answer("❌ Используйте: /admin_add_user <user_id> <plan>\nПланы: free, pro, ultra")
            return
        
        target_id = int(parts[1])
        plan = parts[2].lower()
        
        if plan not in PLANS:
            await message.answer(f"❌ Неизвестный план. Доступны: {', '.join(PLANS.keys())}")
            return
        
        bot_data.set_user_plan(target_id, plan)
        bot_data.user_creations[target_id] = 0
        
        plan_info = PLANS[plan]
        await message.answer(
            f"✅ Пользователю {target_id} выдан план **{plan_info['name']}**\n"
            f"Лимит созданий: {plan_info['max_creations']}",
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Неверный ID")


# ═══════════════════════════════════════════════════════════════
# 🎛️ ОБРАБОТЧИКИ ИНЛАЙН КНОПОК АДМИН ПАНЕЛИ
# ═══════════════════════════════════════════════════════════════

@dp.callback_query(F.data == "admin_add_premium")
async def callback_add_premium(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not bot_data.is_admin(user_id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    # Кнопки выбора плана
    plan_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Free", callback_data="plan_free")],
        [InlineKeyboardButton(text="Pro", callback_data="plan_pro")],
        [InlineKeyboardButton(text="Ultra", callback_data="plan_ultra")]
    ])
    
    await callback.message.answer("💳 Выберите план для добавления:", reply_markup=plan_kb)
    await state.set_state(AdminStates.waiting_plan_to_add)
    await callback.answer()

@dp.callback_query(F.data.in_(["plan_free", "plan_pro", "plan_ultra"]), AdminStates.waiting_plan_to_add)
async def callback_plan_selected(callback: types.CallbackQuery, state: FSMContext):
    plan_name = callback.data.split("_")[1]
    
    await state.update_data(plan=plan_name)
    await state.set_state(AdminStates.waiting_user_id_to_add)
    
    await callback.message.answer(
        f"✅ Выбран план **{PLANS[plan_name]['name']}**\n\n"
        f"Введите ID пользователя, которому выдать этот план:",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(AdminStates.waiting_user_id_to_add)
async def receive_user_id_to_add(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ Недостаточно прав")
        await state.clear()
        return
    
    try:
        target_id = int(message.text)
        data = await state.get_data()
        plan = data.get("plan", "free")
        
        bot_data.set_user_plan(target_id, plan)
        bot_data.user_creations[target_id] = 0
        
        plan_info = PLANS[plan]
        await message.answer(
            f"✅ **Успешно!**\n\n"
            f"Пользователю {target_id} выдан план **{plan_info['name']}**\n"
            f"Креаций: {plan_info['max_creations']}\n"
            f"Вход: {plan_info['max_input_size']//1024}KB / {plan_info['max_input_lines']} строк\n"
            f"Выход: {plan_info['max_output_size']//(1024*1024)}MB",
            parse_mode="Markdown"
        )
        
        # Отправляем уведомление пользователю
        try:
            await bot.send_message(
                target_id,
                f"🎉 **Поздравляем!**\n\n"
                f"Вам выдан премиум план **{plan_info['name']}**\n\n"
                f"📊 Ваши новые возможности:\n"
                f"  • Креаций: {plan_info['max_creations'] if plan_info['max_creations'] != float('inf') else '∞'}\n"
                f"  • Входящие файлы: до {plan_info['max_input_size']//1024}KB\n"
                f"  • Выходящие файлы: до {plan_info['max_output_size']//(1024*1024)}MB\n\n"
                f"Начните пользоваться! 🚀",
                parse_mode="Markdown"
            )
        except:
            pass
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный ID. Введите число:")

@dp.callback_query(F.data == "admin_remove_premium")
async def callback_remove_premium(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not bot_data.is_admin(user_id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    await callback.message.answer("Введите ID пользователя, у которого забрать премиум:")
    await state.set_state(AdminStates.waiting_user_id_to_remove)
    await callback.answer()

@dp.message(AdminStates.waiting_user_id_to_remove)
async def receive_user_id_to_remove(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ Недостаточно прав")
        await state.clear()
        return
    
    try:
        target_id = int(message.text)
        
        # Устанавливаем план Free
        bot_data.set_user_plan(target_id, "free")
        bot_data.user_creations[target_id] = 0
        
        await message.answer(
            f"✅ **Успешно!**\n\n"
            f"Пользователю {target_id} выдан план **Free** (премиум отобран)",
            parse_mode="Markdown"
        )
        
        # Отправляем уведомление пользователю
        try:
            await bot.send_message(
                target_id,
                f"⚠️ **Уведомление**\n\n"
                f"Ваш премиум план был отменен.\n\n"
                f"Ваш текущий план: **Free**\n"
                f"Оставшиеся креации будут обнулены.",
                parse_mode="Markdown"
            )
        except:
            pass
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный ID. Введите число:")

@dp.callback_query(F.data == "admin_block_user")
async def callback_block_user(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not bot_data.is_admin(user_id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    await callback.message.answer("🚫 Введите ID пользователя для блокировки:")
    await state.set_state(AdminStates.waiting_user_id_to_block)
    await callback.answer()

@dp.message(AdminStates.waiting_user_id_to_block)
async def receive_user_id_to_block(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ Недостаточно прав")
        await state.clear()
        return
    
    try:
        target_id = int(message.text)
        
        # Отправляем уведомление пользователю ДО блокировки
        try:
            await bot.send_message(
                target_id,
                f"🚫 **Вы заблокированы навсегда**\n\n"
                f"Ваш аккаунт был заблокирован администратором.\n"
                f"Ваш тариф и все данные удалены.\n\n"
                f"Для получения дополнительной информации напишите сюда: https://t.me/Visasai",
                parse_mode="Markdown"
            )
        except:
            pass
        
        # Блокируем пользователя НАВСЕГДА (удаляем все данные)
        bot_data.block_user(target_id)
        
        await message.answer(
            f"✅ **Успешно!**\n\n"
            f"Пользователь {target_id} **ЗАБЛОКИРОВАН НАВСЕГДА**.\n"
            f"Все данные и тариф удалены из системы.",
            parse_mode="Markdown"
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный ID. Введите число:")

@dp.callback_query(F.data == "admin_unblock_user")
async def callback_unblock_user(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if not bot_data.is_admin(user_id):
        await callback.answer("❌ Недостаточно прав", show_alert=True)
        return
    
    await callback.message.answer("✅ Введите ID пользователя для разблокировки:")
    await state.set_state(AdminStates.waiting_user_id_to_unblock)
    await callback.answer()

@dp.message(AdminStates.waiting_user_id_to_unblock)
async def receive_user_id_to_unblock(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if not bot_data.is_admin(user_id):
        await message.answer("❌ Недостаточно прав")
        await state.clear()
        return
    
    try:
        target_id = int(message.text)
        
        # Разблокируем пользователя
        bot_data.unblock_user(target_id)
        
        await message.answer(
            f"✅ **Успешно!**\n\n"
            f"Пользователь {target_id} разблокирован.\n"
            f"План: Free, креации: 0",
            parse_mode="Markdown"
        )
        
        # Отправляем уведомление пользователю
        try:
            await bot.send_message(
                target_id,
                f"✅ **Вы разблокированы!**\n\n"
                f"Ваш аккаунт был восстановлен администратором.\n\n"
                f"Ваш текущий план: **Free**\n"
                f"Вы можете снова начать пользоваться ботом! 🚀",
                parse_mode="Markdown"
            )
        except:
            pass
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный ID. Введите число:")

@dp.message(F.text == "🚀 Начать создание")
async def menu_start_gen(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer("🚫 Вы заблокированы навсегда и не можете использовать бота.")
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(f"🚫 Вы не можете создавать файлы. Разблокировка через: ~{hours_left} часов")
        return
    
    await message.answer("👇 Просто отправь мне код (текстом или файлом .py).")

@dp.message(F.text == "💳 Премиум")
async def menu_premium(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer("🚫 Вы заблокированы навсегда и не можете использовать бота.")
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(f"🚫 Премиум недоступен. Разблокировка через: ~{hours_left} часов")
        return
    
    current_plan = bot_data.get_user_plan(user_id)
    used = bot_data.user_creations[user_id]
    plan = PLANS[current_plan]
    
    text = (
        "╔════════════════════════════════╗\n"
        "║     💎 ПРЕМИУМ ПОДПИСКИ 💎    ║\n"
        "╚════════════════════════════════╝\n\n"
        f"📊 **Ваш текущий план:** {plan['name']}\n"
        f"📈 Использовано: {used}/{plan['max_creations']} креаций\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    
    # Free план
    text += "┌─ 🆓 FREE 🆓 ─────────────────┐\n"
    text += "│ Бесплатно\n"
    text += "│ 📝 3 креации\n"
    text += "│ 📦 10KB вход / 40 строк\n"
    text += "│ 📤 400KB выход\n"
    if current_plan == "free":
        text += "│ ✅ АКТИВЕН\n"
    text += "└────────────────────────────┘\n\n"
    
    # Pro план
    text += "┌─ 💎 PRO 💎 ───────────────────┐\n"
    text += "│ 100 ⭐ / 30 грн / 65 руб\n"
    text += "│ 📝 15 креаций\n"
    text += "│ 📦 30KB вход / 100 строк\n"
    text += "│ 📤 10MB выход\n"
    if current_plan == "pro":
        text += "│ ✅ АКТИВЕН\n"
    text += "└────────────────────────────┘\n\n"
    
    # Ultra план
    text += "┌─ 👑 ULTRA 👑 ─────────────────┐\n"
    text += "│ 300 ⭐ / 70 грн / 165 руб\n"
    text += "│ 📝 ∞ Бесконечные креации\n"
    text += "│ 📦 1MB вход / ∞ строк\n"
    text += "│ 📤 ∞ Без ограничений\n"
    if current_plan == "ultra":
        text += "│ ✅ АКТИВЕН\n"
    text += "└────────────────────────────┘\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "👇 Нажмите кнопку чтобы обновить подписку 👇"
    
    await message.answer(text, parse_mode="Markdown", reply_markup=premium_kb)

@dp.message(F.text == "ℹ️ Инфо")
async def menu_about(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer("🚫 Вы заблокированы навсегда и не можете использовать бота.")
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(f"🚫 Информация недоступна. Разблокировка через: ~{hours_left} часов")
        return
    
    plan = bot_data.get_user_plan(user_id)
    plan_info = PLANS[plan]
    
    text = (
        "╔════════════════════════════════╗\n"
        "║  🤖 GlaGen - Gen File Bot 🤖  ║\n"
        "╚════════════════════════════════╝\n\n"
        "🎯 Безопасная песочница для Python\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 ВАША ПОДПИСКА\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 План: **{plan_info['name']}**\n"
        f"📥 Входящие файлы: до **{plan_info['max_input_size'] // 1024}KB** ({plan_info['max_input_lines']} строк)\n"
        f"📤 Выходящие файлы: до **{plan_info['max_output_size'] // (1024*1024) if plan_info['max_output_size'] != float('inf') else '∞'}MB**\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ ПОДДЕРЖИВАЕМЫЕ ФОРМАТЫ\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📄 docx - Word документы\n"
        "📊 xlsx - Excel таблицы\n"
        "🎨 pptx - PowerPoint презентации\n"
        "📑 pdf - PDF файлы\n"
        "📈 matplotlib - Графики\n"
        "🔲 qrcode - QR коды\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⛔ ЗАПРЕЩЕНО\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "❌ os, sys - Доступ к системе\n"
        "❌ input() - Ожидание ввода\n"
        "❌ requests, urllib - Интернет\n"
        "❌ eval(), exec() - Опасный код\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ ЛИМИТЫ\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏰ Максимум: **30 секунд** на выполнение\n"
        "🔄 После 10 таймаутов: блок на 24ч\n\n"
        "💡 Обновите подписку для больших лимитов!"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📹 Тутор")
async def menu_tutorial(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer("🚫 Вы заблокированы навсегда и не можете использовать бота.")
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(f"🚫 Тутор недоступен. Разблокировка через: ~{hours_left} часов")
        return
    
    if os.path.exists("tutor.mp4"):
        await message.answer_video(FSInputFile("tutor.mp4"), caption="🎥 Как пользоваться ботом")
    else:
        await message.answer("⚠️ Видео 'tutor.mp4' не загружено на сервер.")

# 1. Если прислали ФАЙЛ
@dp.message(F.document)
async def handle_document(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer(
            f"🚫 **Вы заблокированы навсегда**\n\n"
            f"Ваш аккаунт был удален администратором.\n"
            f"Обратитесь к админу для уточнения: https://t.me/Visasai"
        )
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(
                f"🚫 **Вы не можете создавать файлы**\n\n"
                f"Превышен лимит таймаутов (10+ за день).\n"
                f"Восстановление через: ~{hours_left} часов"
            )
        return
    
    bot_data.register_user(user_id)
    
    if not message.document.file_name.endswith('.py'):
        await message.answer("📄 Принимаю только файлы .py")
        return

    task_dir = os.path.join(BASE_TEMP_DIR, str(uuid.uuid4()))
    os.makedirs(task_dir, exist_ok=True)
    file_path = os.path.join(task_dir, "script.py")
    
    # Скачиваем файл
    file_info = await bot.get_file(message.document.file_id)
    await bot.download_file(file_info.file_path, file_path)
    
    # Читаем код для проверки безопасности
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    bot_data.users_creating.add(user_id)
    await execute_code(message, task_dir, content)
    bot_data.users_creating.discard(user_id)

# 2. Если прислали ТЕКСТ
@dp.message(F.text)
async def handle_text_code(message: types.Message):
    # Игнорируем нажатия кнопок меню
    if message.text in ["🚀 Начать создание", "ℹ️ Инфо", "📹 Тутор", "💳 Премиум", "📊 Админ панель", "👥 Управление", "📞 Написать админу"]: 
        return

    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer(
            f"🚫 **Вы заблокированы навсегда**\n\n"
            f"Ваш аккаунт был удален администратором.\n"
            f"Обратитесь к админу для уточнения: https://t.me/Visasai"
        )
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(
                f"🚫 **Вы не можете создавать файлы**\n\n"
                f"Превышен лимит таймаутов (10+ за день).\n"
                f"Восстановление через: ~{hours_left} часов"
            )
        return
    
    bot_data.register_user(user_id)
    
    code = message.text
    # Чистим от маркдауна (```python ... ```)
    if "```" in code:
        lines = code.split('\n')
        if lines[0].strip().startswith("```"): lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"): lines = lines[:-1]
        code = "\n".join(lines)

    # 🔥 АВТО-ПАТЧ: Чиним ошибку name == main
    if 'if name == "main":' in code:
        code = code.replace('if name == "main":', 'if __name__ == "__main__":')
    if "if name == 'main':" in code:
        code = code.replace("if name == 'main':", "if __name__ == '__main__':")

    task_dir = os.path.join(BASE_TEMP_DIR, str(uuid.uuid4()))
    os.makedirs(task_dir, exist_ok=True)
    
    with open(os.path.join(task_dir, "script.py"), "w", encoding="utf-8") as f:
        f.write(code)
    
    bot_data.users_creating.add(user_id)
    await execute_code(message, task_dir, code)
    bot_data.users_creating.discard(user_id)


# --- 📥 КНОПКА СКАЧИВАНИЯ ---
@dp.callback_query(F.data.startswith("get_file_"))
async def callback_send_file(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await callback.answer("🚫 Вы заблокированы и не можете скачивать файлы.", show_alert=True)
        return
    
    if bot_data.is_temp_blocked(user_id):
        await callback.answer("🚫 Вы временно заблокированы и не можете скачивать файлы.", show_alert=True)
        return
    
    if user_id in users_files:
        file_path, dir_path = users_files[user_id]
        try:
            await callback.message.answer_document(FSInputFile(file_path), caption="Готово! 😎")
            await callback.message.delete() # Удаляем кнопку, чтобы не жали дважды
        except Exception as e:
            await callback.message.answer(f"Ошибка отправки: {e}")
        finally:
            # Удаляем папку и очищаем память
            try: shutil.rmtree(dir_path)
            except: pass
            del users_files[user_id]
    else:
        await callback.answer("Файл уже удален или устарел", show_alert=True)

# --- 🔥 ЗАПУСК ---
if __name__ == "__main__":
    print("🚀 Бот запущен на сервере!")
    asyncio.run(dp.start_polling(bot))