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
from aiogram.types import MenuButtonCommands, BotCommand, PreCheckoutQuery, ContentType, LabeledPrice
from aiogram.exceptions import TelegramBadRequest

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
    waiting_user_id_to_add_admin = State()
    
    # Состояния для создания заданий
    waiting_task_text = State()
    waiting_task_type = State()
    waiting_task_target = State()
    waiting_reward_type = State()
    waiting_reward_value = State()
    waiting_reward_duration = State()

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

# Словари переводов
LANG = {
    "ru": {
        "start": "👋 Привет! Я публичный генератор файлов.\nКидай код — получай результат.",
        "premium": "╔════════════════════════════════╗\n║     💎 ПРЕМИУМ ПОДПИСКИ 💎    ║\n╚════════════════════════════════╝\n\n📊 **Ваш текущий план:** {plan}\n📈 Использовано: {used}/{max} креаций\n⏳ Обновление через: **{reset_time}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n",
        "lang_select": "🌐 Выберите язык:",
        "lang_changed": "✅ Язык изменен на Русский!",
        "ref_info": "👥 **РЕФЕРАЛЬНАЯ СИСТЕМА**\n\nПригласи друга и получи **+2 креации** к лимиту на 7 дней!\n\n🔗 Твоя ссылка:\n`{link}`\n\nВсего приглашено: {count}",
        "my_files": "📋 **ВАШИ ПОСЛЕДНИЕ ФАЙЛЫ**",
        "no_files": "🤔 У вас пока нет созданных файлов.",
        "blocked_list": "🚫 **СПИСОК ЗАБЛОКИРОВАННЫХ**\n\n",
        "no_blocked": "✅ Заблокированных пользователей нет.",
        "unblock_btn": "✅ Разблокировать пользователя",
        "stats_btn": "📊 Моя статистика",
        "files_btn": "📋 Мои файлы",
        "lang_btn": "🌐 Язык",
        "ref_btn": "👥 Рефералы",
        "gen_btn": "🚀 Начать создание",
        "prem_btn": "💳 Премиум",
        "info_btn": "ℹ️ Инфо",
        "tutor_btn": "📹 Тутор",
        "tasks_btn": "🎁 Задания",
        "info": (
            "╔════════════════════════════════╗\n"
            "║  🤖 GlaGen - Gen File Bot 🤖  ║\n"
            "╚════════════════════════════════╝\n\n"
            "🎯 Безопасная песочница для Python\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 ВАША ПОДПИСКА\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💳 План: **{plan_name}**\n"
            "📥 Входящие файлы: до **{input_size}KB** ({input_lines} строк)\n"
            "📤 Выходящие файлы: до **{output_size}MB**\n\n"
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
            "⏳ ЛИМИТЫ\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏰ Максимум: **30 секунд** на выполнение\n"
            "🔄 После 10 таймаутов: блок на 24ч\n\n"
            "💡 Обновите подписку для больших лимитов!"
        ),
        "prem_msg": (
            "╔════════════════════════════════╗\n"
            "║     💎 ПРЕМИУМ ПОДПИСКИ 💎    ║\n"
            "╚════════════════════════════════╝\n\n"
            "📊 **Ваш текущий план:** {plan}\n"
            "📈 Использовано: {used}/{max} креаций\n"
            "⏳ Обновление через: **{reset_time}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "┌─ 🆓 FREE 🆓 ─────────────────┐\n"
            "│ Бесплатно\n"
            "│ 📝 3 креации\n"
            "│ 📦 10KB вход / 40 строк\n"
            "│ 📤 400KB выход\n"
            "{free_active}"
            "└────────────────────────────┘\n\n"
            "┌─ 💎 PRO 💎 ───────────────────┐\n"
            "│ 100 ⭐ / 30 грн / 65 руб\n"
            "│ 📝 15 креаций\n"
            "│ 📦 30KB вход / 100 строк\n"
            "│ 📤 10MB выход\n"
            "{pro_active}"
            "└────────────────────────────┘\n\n"
            "┌─ 👑 ULTRA 👑 ─────────────────┐\n"
            "│ 300 ⭐ / 70 грн / 165 руб\n"
            "│ 📝 ∞ Бесконечные креации\n"
            "│ 📦 1MB вход / ∞ строк\n"
            "│ 📤 ∞ Без ограничений\n"
            "{ultra_active}"
            "└────────────────────────────┘\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 Нажмите кнопку чтобы обновить подписку 👇"
        ),
        "prem_active": "│ ✅ АКТИВЕН\n",
        "prem_choice_stars": "⭐ Оплатить Stars",
        "prem_choice_contact": "💬 Написать админу",
        "prem_plan_pro": "💎 Pro (30 грн / 100 ⭐)",
        "prem_plan_ultra": "👑 Ultra (70 грн / 300 ⭐)",
        "gen_prompt": "👇 Просто отправь мне код (текстом или файлом .py).",
        "pay_success": "🎉 **Оплата прошла успешно!**\n\nВам активирован план **{plan}**.\nПриятного пользования! 🚀",
        "blocked_perm": "🚫 Вы заблокированы навсегда и не можете использовать бота.",
        "blocked_temp": "🚫 Вы не можете создавать файлы. Разблокировка через: ~{hours} часов",
        "tasks_menu": "🎁 **ДОСТУПНЫЕ ЗАДАНИЯ**\n\nВыполняйте задания и получайте ценные награды: дополнительные лимиты или временный Premium!",
        "task_item": "🔹 {text}\nНаграда: **{reward}**",
        "task_completed": "✅ Задание выполнено! Вам начислено: {reward}",
        "task_already_done": "⚠️ Вы уже выполняли это задание.",
        "task_not_subbed": "❌ **Вы еще не подписаны!**\n\nПожалуйста, подпишитесь на канал {target} и нажмите кнопку подтверждения повторно.",
        "task_reward_creations": "{count} доп. креаций",
        "task_reward_premium": "{days} дн. PRO",
        "admin_tasks_btn": "🎁 Управление заданиями",
        "admin_no_tasks": "В системе пока нет активных заданий.",
        "admin_tasks_list": "📋 **СПИСОК ЗАДАНИЙ**",
        "task_type_sub": "Подписка на канал",
        "task_type_manual": "Ручное подтверждение",
        "admin_task_target_tip": "🆔 Введите юзернейм канала (с @) или числовой ID.\nБот Должен быть в этом канале!"
    },
    "ua": {
        "start": "👋 Привіт! Я публічний генератор файлів.\nКидай код — отримуй результат.",
        "premium": "╔════════════════════════════════╗\n║     💎 ПРЕМІУМ ПІДПИСКИ 💎     ║\n╚════════════════════════════════╝\n\n📊 **Ваш поточний план:** {plan}\n📈 Використано: {used}/{max} креацій\n⏳ Оновлення через: **{reset_time}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n",
        "lang_select": "🌐 Оберіть мову:",
        "lang_changed": "✅ Мову змінено на Українську!",
        "ref_info": "👥 **РЕФЕРАЛЬНА СИСТЕМА**\n\nЗапроси друга та отримай **+2 креації** до ліміту на 7 днів!\n\n🔗 Твоє посилання:\n`{link}`\n\nВсього запрошено: {count}",
        "my_files": "📋 **ВАШІ ОСТАННІ ФАЙЛИ**",
        "no_files": "🤔 У вас поки немає створених файлів.",
        "blocked_list": "🚫 **СПОСОК ЗАБЛОКОВАНИХ**\n\n",
        "no_blocked": "✅ Заблокованих користувачів немає.",
        "unblock_btn": "✅ Розблокирувати користувача",
        "stats_btn": "📊 Моя статистика",
        "files_btn": "📋 Мої файли",
        "lang_btn": "🌐 Мова",
        "ref_btn": "👥 Реферали",
        "gen_btn": "🚀 Почати створення",
        "prem_btn": "💳 Преміум",
        "info_btn": "ℹ️ Інфо",
        "tutor_btn": "📹 Тутор",
        "tasks_btn": "🎁 Завдання",
        "info": (
            "╔════════════════════════════════╗\n"
            "║  🤖 GlaGen - Gen File Bot 🤖  ║\n"
            "╚════════════════════════════════╝\n\n"
            "🎯 Безпечна пісочниця для Python\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 ВАША ПЕРЕДПЛАТА\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💳 План: **{plan_name}**\n"
            "📥 Вхідні файли: до **{input_size}KB** ({input_lines} рядків)\n"
            "📤 Вихідні файли: до **{output_size}MB**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ ПІДТРИМУВАНІ ФОРМАТЫ\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📄 docx - Word документи\n"
            "📊 xlsx - Excel таблиці\n"
            "🎨 pptx - PowerPoint презентації\n"
            "📑 pdf - PDF файли\n"
            "📈 matplotlib - Графіки\n"
            "🔲 qrcode - QR коди\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏳ ЛІМІТИ\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏰ Максимум: **30 секунд** на виконання\n"
            "🔄 Після 10 таймаутів: блок на 24г\n\n"
            "💡 Оновіть передплату для більших лімітів!"
        ),
        "prem_msg": (
            "╔════════════════════════════════╗\n"
            "║     💎 ПРЕМІУМ ПІДПИСКИ 💎     ║\n"
            "╚════════════════════════════════╝\n\n"
            "📊 **Ваш поточний план:** {plan}\n"
            "📈 Використано: {used}/{max} креацій\n"
            "⏳ Оновлення через: **{reset_time}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "┌─ 🆓 FREE 🆓 ─────────────────┐\n"
            "│ Безкоштовно\n"
            "│ 📝 3 креації\n"
            "│ 📦 10KB вхід / 40 рядків\n"
            "│ 📤 400KB вихід\n"
            "{free_active}"
            "└────────────────────────────┘\n\n"
            "┌─ 💎 PRO 💎 ───────────────────┐\n"
            "│ 100 ⭐ / 30 грн / 65 руб\n"
            "│ 📝 15 креацій\n"
            "│ 📦 30KB вхід / 100 рядків\n"
            "│ 📤 10MB вихід\n"
            "{pro_active}"
            "└────────────────────────────┘\n\n"
            "┌─ 👑 ULTRA 👑 ─────────────────┐\n"
            "│ 300 ⭐ / 70 грн / 165 руб\n"
            "│ 📝 ∞ Нескінченні креації\n"
            "│ 📦 1MB вхід / ∞ рядків\n"
            "│ 📤 ∞ Без обмежень\n"
            "{ultra_active}"
            "└────────────────────────────┘\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 Натисніть кнопку щоб оновити передплату 👇"
        ),
        "prem_active": "│ ✅ АКТИВНИЙ\n",
        "prem_choice_stars": "⭐ Оплатити Stars",
        "prem_choice_contact": "💬 Написати адміну",
        "prem_plan_pro": "💎 Pro (30 грн / 100 ⭐)",
        "prem_plan_ultra": "👑 Ultra (70 грн / 300 ⭐)",
        "gen_prompt": "👇 Відправ мені код (текстом або файлом .py).",
        "pay_success": "🎉 **Оплата пройшла успішно!**\n\nВам активовано план **{plan}**.\nПриємного користування! 🚀",
        "blocked_perm": "🚫 Ви заблоковані назавжди і не можете використовувати бота.",
        "blocked_temp": "🚫 Ви не можете створювати файли. Розблокування через: ~{hours} годин",
        "tasks_menu": "🎁 **ДОСТУПНІ ЗАВДАННЯ**\n\nВиконуйте завдання та отримуйте цінні нагороди: додаткові ліміти або тимчасовий Premium!",
        "task_item": "🔹 {text}\nНагорода: **{reward}**",
        "task_completed": "✅ Завдання виконано! Вам нараховано: {reward}",
        "task_already_done": "⚠️ Ви вже виконували це завдання.",
        "task_not_subbed": "❌ **Ви ще не підписані!**\n\nБудь ласка, підпишіться на канал {target} та натисніть кнопку підтвердження ще раз.",
        "task_reward_creations": "{count} дод. креацій",
        "task_reward_premium": "{days} дн. PRO",
        "admin_tasks_btn": "🎁 Управління завданнями",
        "admin_no_tasks": "У системі поки немає активних завдань.",
        "admin_tasks_list": "📋 **СПИСОК ЗАВДАНЬ**",
        "task_type_sub": "Підписка на канал",
        "task_type_manual": "Ручне підтвердження",
        "admin_task_target_tip": "🆔 Введіть юзернейм каналу (з @) або числовий ID.\nБот Має бути в цьому каналі!"
    },
    "en": {
        "start": "👋 Hi! I am a public file generator.\nSend code — get results.",
        "premium": "╔════════════════════════════════╗\n║     💎 PREMIUM SUBSCRIPTIONS 💎  ║\n╚════════════════════════════════╝\n\n📊 **Your current plan:** {plan}\n📈 Used: {used}/{max} creations\n⏳ Reset in: **{reset_time}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n",
        "lang_select": "🌐 Choose language:",
        "lang_changed": "✅ Language changed to English!",
        "ref_info": "👥 **REFERRAL SYSTEM**\n\nInvite a friend and get **+2 creations** to your limit for 7 days!\n\n🔗 Your link:\n`{link}`\n\nTotal invited: {count}",
        "my_files": "📋 **YOUR RECENT FILES**",
        "no_files": "🤔 You have no created files yet.",
        "blocked_list": "🚫 **BLOCKED LIST**\n\n",
        "no_blocked": "✅ No blocked users.",
        "unblock_btn": "✅ Unblock user",
        "files_btn": "📋 My Files",
        "lang_btn": "🌐 Language",
        "ref_btn": "👥 Referrals",
        "gen_btn": "🚀 Start Creation",
        "prem_btn": "💳 Premium",
        "info_btn": "ℹ️ Info",
        "tutor_btn": "📹 Tutorial",
        "tasks_btn": "🎁 Tasks",
        "info": (
            "╔════════════════════════════════╗\n"
            "║  🤖 GlaGen - Gen File Bot 🤖  ║\n"
            "╚════════════════════════════════╝\n\n"
            "🎯 Safe sandbox for Python\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 YOUR SUBSCRIPTION\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💳 Plan: **{plan_name}**\n"
            "📥 Input files: up to **{input_size}KB** ({input_lines} lines)\n"
            "📤 Output files: up to **{output_size}MB**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ SUPPORTED FORMATS\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📄 docx - Word documents\n"
            "📊 xlsx - Excel spreadsheets\n"
            "🎨 pptx - PowerPoint presentations\n"
            "📑 pdf - PDF files\n"
            "📈 matplotlib - Charts\n"
            "🔲 qrcode - QR codes\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏳ LIMITS\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⏰ Maximum: **30 seconds** per execution\n"
            "🔄 After 10 timeouts: block for 24h\n\n"
            "💡 Upgrade your subscription for higher limits!"
        ),
        "prem_msg": (
            "╔════════════════════════════════╗\n"
            "║     💎 PREMIUM SUBSCRIPTIONS 💎  ║\n"
            "╚════════════════════════════════╝\n\n"
            "📊 **Your current plan:** {plan}\n"
            "📈 Used: {used}/{max} creations\n"
            "⏳ Reset in: **{reset_time}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "┌─ 🆓 FREE 🆓 ─────────────────┐\n"
            "│ Free\n"
            "│ 📝 3 creations\n"
            "│ 📦 10KB input / 40 lines\n"
            "│ 📤 400KB output\n"
            "{free_active}"
            "└────────────────────────────┘\n\n"
            "┌─ 💎 PRO 💎 ───────────────────┐\n"
            "│ 100 ⭐ / 30 UAH / 65 RUB\n"
            "│ 📝 15 creations\n"
            "│ 📦 30KB input / 100 lines\n"
            "│ 📤 10MB output\n"
            "{pro_active}"
            "└────────────────────────────┘\n\n"
            "┌─ 👑 ULTRA 👑 ─────────────────┐\n"
            "│ 300 ⭐ / 70 UAH / 165 RUB\n"
            "│ 📝 ∞ Infinite creations\n"
            "│ 📦 1MB input / ∞ lines\n"
            "│ 📤 ∞ No limits\n"
            "{ultra_active}"
            "└────────────────────────────┘\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 Press the button to upgrade 👇"
        ),
        "prem_active": "│ ✅ ACTIVE\n",
        "prem_choice_stars": "⭐ Pay with Stars",
        "prem_choice_contact": "💬 Write to Admin",
        "prem_plan_pro": "💎 Pro (30 UAH / 100 ⭐)",
        "prem_plan_ultra": "👑 Ultra (70 UAH / 300 ⭐)",
        "gen_prompt": "👇 Just send me your code (as text or a .py file).",
        "pay_success": "🎉 **Payment successful!**\n\nYour plan is now **{plan}**.\nEnjoy! 🚀",
        "blocked_perm": "🚫 You are permanently blocked and cannot use the bot.",
        "blocked_temp": "🚫 You cannot create files. Unblock in: ~{hours} hours",
        "tasks_menu": "🎁 **AVAILABLE TASKS**\n\nComplete tasks and get valuable rewards: extra limits or temporary Premium!",
        "task_item": "🔹 {text}\nReward: **{reward}**",
        "task_completed": "✅ Task completed! You received: {reward}",
        "task_already_done": "⚠️ You have already completed this task.",
        "task_not_subbed": "❌ **Not subscribed yet!**\n\nPlease subscribe to {target} and then click the confirm button again.",
        "task_reward_creations": "{count} extra creations",
        "task_reward_premium": "{days} days PRO",
        "admin_tasks_btn": "🎁 Manage Tasks",
        "admin_no_tasks": "No active tasks in the system.",
        "admin_tasks_list": "📋 **TASKS LIST**",
        "task_type_sub": "Channel Sub",
        "task_type_manual": "Manual Confirm",
        "admin_task_target_tip": "🆔 Enter channel username (with @) or numeric ID.\nBot MUST be in this channel!"
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
        self.last_creations_reset = datetime.now()
        self.user_file_history = defaultdict(list)  # {user_id: [{name, path, timestamp}]}
        self.user_lang = {}  # {user_id: "ru"}
        self.user_referrals = defaultdict(list)  # {user_id: [invited_ids]}
        self.user_referral_bonus = {}  # {user_id: expires_isoformat}
        self.tasks = []  # [{id, text, type, target, reward_type, reward_value, reward_duration}]
        self.user_completed_tasks = defaultdict(set)  # {user_id: {task_id}}
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
                    self.last_creations_reset = datetime.fromisoformat(data.get("last_creations_reset", datetime.now().isoformat()))
                    self.user_file_history = {int(k): v for k, v in data.get("user_file_history", {}).items()}
                    self.user_lang = data.get("user_lang", {})
                    self.user_referrals = {int(k): v for k, v in data.get("user_referrals", {}).items()}
                    self.user_referral_bonus = {int(k): v for k, v in data.get("user_referral_bonus", {}).items()}
                    self.tasks = data.get("tasks", [])
                    self.user_completed_tasks = defaultdict(set, {int(k): set(v) for k, v in data.get("user_completed_tasks", {}).items()})
            except:
                pass
    
    def save_data(self):
        data = {
            "admins": list(self.admins),
            "user_plans": self.user_plans,
            "user_join_time": {k: v.isoformat() for k, v in self.user_join_time.items()},
            "timeout_count": self.timeout_count,
            "temp_blocked_users": {k: v.isoformat() for k, v in self.temp_blocked_users.items()},
            "permanently_blocked_users": list(self.permanently_blocked_users),
            "last_creations_reset": self.last_creations_reset.isoformat(),
            "user_file_history": self.user_file_history,
            "user_lang": self.user_lang,
            "user_referrals": self.user_referrals,
            "user_referral_bonus": self.user_referral_bonus,
            "tasks": self.tasks,
            "user_completed_tasks": {k: list(v) for k, v in self.user_completed_tasks.items()}
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
        try:
            return int(user_id) == 8566608157
        except:
            return False
    
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

    def get_user_lang(self, user_id: int) -> str:
        return self.user_lang.get(str(user_id), "ru")

    def set_user_lang(self, user_id: int, lang: str):
        self.user_lang[str(user_id)] = lang
        self.save_data()

    def tr(self, user_id: int, key: str, **kwargs) -> str:
        lang = self.get_user_lang(user_id)
        text = LANG.get(lang, LANG["ru"]).get(key, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except:
                return text
        return text

    def get_reset_time_left(self) -> str:
        """Возвращает время до следующего сброса лимитов (ЧЧ:ММ)"""
        self.check_and_reset_creations()
        elapsed = datetime.now() - self.last_creations_reset
        remaining = timedelta(hours=5) - elapsed
        
        if remaining.total_seconds() < 0:
            return "00:00"
            
        seconds = int(remaining.total_seconds())
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"

    def check_and_reset_creations(self):
        """Сброс лимитов каждые 5 часов"""
        if datetime.now() - self.last_creations_reset >= timedelta(hours=5):
            self.user_creations.clear()
            self.last_creations_reset = datetime.now()
            self.save_data()
            print(f"🔄 Лимиты креаций сброшены: {self.last_creations_reset}")

    def add_to_history(self, user_id: int, file_path: str, file_name: str):
        history = self.user_file_history.get(user_id, [])
        history.append({
            "name": file_name,
            "path": file_path,
            "timestamp": datetime.now().isoformat()
        })
        # Храним последние 5
        if len(history) > 5:
            old = history.pop(0)
            # Если файл еще в ОС, не удаляем тут, так как execute_code сам рулил temp_work.
            # Но для истории мы можем захотеть сохранить файлы подольше.
            # Для простоты: файлы живут в temp_work пока работает бот.
        self.user_file_history[user_id] = history
        self.save_data()

    def get_max_creations(self, user_id: int) -> int:
        plan_name = self.get_user_plan(user_id)
        max_c = PLANS[plan_name]["max_creations"]
        
        # Проверка бонуса реферала
        bonus_expires = self.user_referral_bonus.get(user_id)
        if bonus_expires:
            if datetime.now() < datetime.fromisoformat(bonus_expires):
                if max_c == float('inf'): return max_c
                return max_c + 2
            else:
                del self.user_referral_bonus[user_id]
                self.save_data()
        return max_c

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
# Все возможные тексты кнопок меню (для игнорирования в handle_text_code)
ALL_MENU_BUTTONS = set()
for lang_dict in LANG.values():
    for key in ["gen_btn", "files_btn", "prem_btn", "ref_btn", 
                "info_btn", "tutor_btn", "lang_btn", "tasks_btn"]:
        ALL_MENU_BUTTONS.add(lang_dict.get(key, ""))
ALL_MENU_BUTTONS.add("📞 Написать админу")

def btn_texts(key: str) -> set:
    """Возвращает множество текстов кнопки на всех языках"""
    return {LANG[lang][key] for lang in LANG}

def get_kb(user_id: int) -> ReplyKeyboardMarkup:
    """Генерирует локализованную клавиатуру"""
    user_id = int(str(user_id))
    t = lambda key: bot_data.tr(user_id, key)
    # Прямая проверка ID для 100% надежности
    is_adm = (user_id == 8566608157)
    
    rows = [
        [KeyboardButton(text=t("gen_btn"))],
        [KeyboardButton(text=t("files_btn")), KeyboardButton(text=t("tasks_btn"))],
        [KeyboardButton(text=t("prem_btn")), KeyboardButton(text=t("ref_btn"))],
        [KeyboardButton(text=t("info_btn")), KeyboardButton(text=t("tutor_btn")), KeyboardButton(text=t("lang_btn"))],
    ]
    
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder="...")

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=LANG["ru"]["gen_btn"])],
        [KeyboardButton(text=LANG["ru"]["files_btn"]), KeyboardButton(text=LANG["ru"]["prem_btn"])],
        [KeyboardButton(text=LANG["ru"]["ref_btn"]), KeyboardButton(text=LANG["ru"]["lang_btn"])],
        [KeyboardButton(text=LANG["ru"]["info_btn"]), KeyboardButton(text=LANG["ru"]["tutor_btn"])]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие..."
)

# Админ меню
admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=LANG["ru"]["gen_btn"])],
        [KeyboardButton(text=LANG["ru"]["files_btn"]), KeyboardButton(text=LANG["ru"]["prem_btn"])],
        [KeyboardButton(text=LANG["ru"]["ref_btn"]), KeyboardButton(text=LANG["ru"]["lang_btn"])],
        [KeyboardButton(text=LANG["ru"]["info_btn"]), KeyboardButton(text=LANG["ru"]["tutor_btn"])]
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

# Премиум клавиатура (выбор способа)
def get_premium_choice_kb(user_id):
    t = lambda key: bot_data.tr(user_id, key)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("prem_choice_stars"), callback_data="prem_stars")],
        [InlineKeyboardButton(text=t("prem_choice_contact"), url="https://t.me/Visaaai")]
    ])

# Премиум клавиатура (планы)
def get_premium_plans_kb(user_id):
    t = lambda key: bot_data.tr(user_id, key)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("prem_plan_pro"), callback_data="buy_pro")],
        [InlineKeyboardButton(text=t("prem_plan_ultra"), callback_data="buy_ultra")]
    ])

lang_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
    [InlineKeyboardButton(text="🇺🇦 Українська", callback_data="set_lang_ua")],
    [InlineKeyboardButton(text="🇺🇸 English", callback_data="set_lang_en")]
])


# --- 🛡️ ФУНКЦИЯ БЕЗОПАСНОСТИ ---
def is_safe_code(code: str) -> bool:
    """Все библиотеки разрешены."""
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
        await message.answer(f"⛔ **Код заблокирован!**\nНайдена запрещенная команда: `{banned_word}`.", parse_mode="Markdown")
        shutil.rmtree(task_dir)
        return

    try:
        # 0. Сброс лимитов если пора
        bot_data.check_and_reset_creations()

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
        
        # Проверка кол-ва использований (с учетом бонусов)
        max_creations = bot_data.get_max_creations(user_id)
        if bot_data.user_creations[user_id] >= max_creations:
            await status_msg.edit_text(
                f"🚫 Вы исчерпали лимит на {plan['name']}!\n"
                f"Создано файлов: {bot_data.user_creations[user_id]}/{max_creations}\n\n"
                f"Обновите план для бесконечных созданий (или подождите сброса каждые 5 часов) 💳"
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
                
                # Добавляем в историю
                bot_data.add_to_history(user_id, result_file, generated_files[0])

                max_creations = bot_data.get_max_creations(user_id)
                await status_msg.edit_text(
                    f"✅ Готово! Файл создан: {generated_files[0]}\n"
                    f"Использовано: {bot_data.user_creations[user_id]}/{max_creations}", 
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
    
    # Реферальная система: проверка deep link
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            inviter_id = int(args[1].replace("ref_", ""))
            # Проверяем что не сам себя и что юзер реально новый (регистрация выше просто добавляет время если нет)
            # Но в bot_data.register_user мы уже добавили. 
            # Для честности проверим был ли он в системе до этого.
            # Но так как register_user вызывается всегда, проверим прямо тут.
            if inviter_id != user_id and user_id not in bot_data.user_referrals:
                # Добавляем реферала
                if user_id not in [item for sublist in bot_data.user_referrals.values() for item in sublist]:
                    bot_data.user_referrals[inviter_id].append(user_id)
                    # Бонус на 7 дней
                    bot_data.user_referral_bonus[inviter_id] = (datetime.now() + timedelta(days=7)).isoformat()
                    bot_data.save_data()
                    try:
                        await bot.send_message(inviter_id, f"🎉 По вашей ссылке зарегистировался новый пользователь! Вам начислен бонус: +2 креации на 7 дней.")
                    except: pass
        except: pass

    # Выбираем локализованную клавиатуру
    kb = get_kb(user_id)
    
    status = "Обычный пользователь"
    if user_id == 8566608157:
        status = "Владелец (Администратор)"
    
    reg_text = bot_data.tr(user_id, "start") + f"\n\n👤 **Статус:** {status}\n🆔 **Ваш ID:** `{user_id}`"
    
    await message.answer(reg_text, reply_markup=kb, parse_mode="Markdown")

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
        f"  • Ultra: {plans_count['ultra']}"
    )

    admin_kb_inline = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Выдать Премиум", callback_data="admin_add_premium")],
        [InlineKeyboardButton(text="❌ Забрать Премиум", callback_data="admin_remove_premium")],
        [InlineKeyboardButton(text="🚫 Забанить (ID)", callback_data="admin_block_user")],
        [InlineKeyboardButton(text="✅ Разбанить (ID)", callback_data="admin_unblock_user")],
        [InlineKeyboardButton(text="📋 Список забаненных", callback_data="admin_list_blocked")],
        [InlineKeyboardButton(text="🎁 Управление заданиями", callback_data="admin_tasks_manage")],
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add_manager")]
    ])
    
    await message.answer(admin_text, parse_mode="Markdown", reply_markup=admin_kb_inline)

# ═══════════════════════════════════════════════════════════════
# 💳 КОНТАКТЫ
# ═══════════════════════════════════════════════════════════════

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
    admin_contact = "Visaaai"  # Telegram username админа
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

# ═══════════════════════════════════════════════════════════════
# 💳 ОПЛАТА TELEGRAM STARS
# ═══════════════════════════════════════════════════════════════

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy_premium(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    plan_key = callback.data.split("_")[1]
    
    prices = {
        "pro": {"label": "Pro Plan", "amount": 100},
        "ultra": {"label": "Ultra Plan", "amount": 300}
    }
    
    plan = prices.get(plan_key)
    if not plan: return

    await callback.message.answer_invoice(
        title=f"Подписка {plan_key.upper()}",
        description=f"Активация плана {plan_key.upper()} в GlaGen Bot",
        prices=[LabeledPrice(label=plan["label"], amount=plan["amount"])],
        payload=f"pay_{plan_key}",
        currency="XTR",  # Telegram Stars
        provider_token="" # Пусто для Stars
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def process_successful_payment(message: types.Message):
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload
    plan_key = payload.split("_")[1]
    
    bot_data.set_user_plan(user_id, plan_key)
    bot_data.user_creations[user_id] = 0
    
    await message.answer(
        bot_data.tr(user_id, "pay_success", plan=PLANS[plan_key]['name']),
        parse_mode="Markdown"
    )

    # Уведомление администратора об оплате
    try:
        admin_id = 8566608157
        user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID: {user_id}"
        await bot.send_message(
            admin_id,
            f"💰 **Новая оплата!**\n\n"
            f"👤 От: {user_info}\n"
            f"💎 План: **{PLANS[plan_key]['name']}**\n"
            f"⭐ Сумма: {message.successful_payment.total_amount} Stars",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Ошибка уведомления админа: {e}")

# ═══════════════════════════════════════════════════════════════
# 📋 НОВЫЕ ХЕНДЛЕРЫ КНОПОК
# ═══════════════════════════════════════════════════════════════

@dp.message(F.text.in_(btn_texts("ref_btn")))
async def cmd_ref_btn(message: types.Message):
    user_id = message.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    count = len(bot_data.user_referrals.get(user_id, []))
    
    text = bot_data.tr(user_id, "ref_info", link=ref_link, count=count)
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text.in_(btn_texts("lang_btn")))
async def cmd_lang_btn(message: types.Message):
    user_id = message.from_user.id
    await message.answer(bot_data.tr(user_id, "lang_select"), reply_markup=lang_kb)

@dp.callback_query(F.data.startswith("set_lang_"))
async def callback_set_lang(callback: types.CallbackQuery):
    lang = callback.data.split("_")[2]
    user_id = callback.from_user.id
    bot_data.set_user_lang(user_id, lang)
    
    # Обновляем меню с локализованными кнопками
    kb = get_kb(user_id)
    await callback.message.answer(bot_data.tr(user_id, "lang_changed"), reply_markup=kb)
    await callback.answer()

@dp.message(F.text.in_(btn_texts("files_btn")))
async def cmd_myfiles_btn(message: types.Message):
    user_id = message.from_user.id
    history = bot_data.user_file_history.get(user_id, [])
    
    if not history:
        await message.answer(bot_data.tr(user_id, "no_files"))
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for idx, item in enumerate(history):
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"📁 {item['name']}", callback_data=f"hist_{idx}")])
        
    await message.answer(bot_data.tr(user_id, "my_files"), reply_markup=kb)

@dp.callback_query(F.data.startswith("hist_"))
async def callback_hist_download(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    idx = int(callback.data.split("_")[1])
    history = bot_data.user_file_history.get(user_id, [])
    
    if idx < len(history):
        item = history[idx]
        if os.path.exists(item['path']):
            await callback.message.answer_document(FSInputFile(item['path']), caption=f"Файл из истории: {item['name']}")
        else:
            await callback.answer("Файл уже удален с сервера", show_alert=True)
    else:
        await callback.answer("Ошибка индекса", show_alert=True)
    await callback.answer()

@dp.message(Command("mystats"))
async def cmd_mystats(message: types.Message):
    await cmd_mystats_btn(message)

@dp.message(Command("ref"))
async def cmd_ref(message: types.Message):
    await cmd_ref_btn(message)

@dp.message(Command("blocked_list"))
async def cmd_blocked_list(message: types.Message):
    user_id = message.from_user.id
    if not bot_data.is_admin(user_id): return
    
    blocked = list(bot_data.permanently_blocked_users)
    if not blocked:
        await message.answer(bot_data.tr(user_id, "no_blocked"))
        return
    
    text = bot_data.tr(user_id, "blocked_list")
    for b_id in blocked:
        text += f"• `{b_id}`\n"
    
    await message.answer(text, parse_mode="Markdown")

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
# ═══════════════════════════════════════════════════════════════

@dp.callback_query(F.data == "admin_list_blocked")
async def callback_admin_list_blocked(callback: types.CallbackQuery):
    if not bot_data.is_admin(callback.from_user.id): return
    
    blocked = list(bot_data.permanently_blocked_users)
    if not blocked:
        await callback.message.answer("✅ В системе нет заблокированных пользователей.")
    else:
        text = "🚫 **Список заблокированных пользователей:**\n\n"
        for b_id in blocked:
            text += f"• `{b_id}`\n"
        await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_add_manager")
async def callback_admin_add_manager(callback: types.CallbackQuery, state: FSMContext):
    if not bot_data.is_admin(callback.from_user.id): return
    await callback.message.answer("🆔 Введите ID пользователя, которого хотите сделать администратором:")
    await state.set_state(AdminStates.waiting_user_id_to_add_admin)
    await callback.answer()

@dp.message(AdminStates.waiting_user_id_to_add_admin)
async def receive_admin_id(message: types.Message, state: FSMContext):
    if not bot_data.is_admin(message.from_user.id): return
    try:
        target_id = int(message.text)
        bot_data.add_admin(target_id)
        await message.answer(f"✅ Пользователь `{target_id}` теперь администратор.", parse_mode="Markdown")
    except:
        await message.answer("❌ Ошибка. Введите числовой ID.")
    await state.clear()

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

# ═══════════════════════════════════════════════════════════════
# 🎁 СИСТЕМА ЗАДАНИЙ (АДМИН)
# ═══════════════════════════════════════════════════════════════

@dp.callback_query(F.data == "admin_tasks_manage")
async def callback_admin_tasks_manage(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not bot_data.is_admin(user_id): return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_task_add")],
        [InlineKeyboardButton(text="📋 Список заданий", callback_data="admin_task_list")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text("🎁 **Управление заданиями**\n\nЗдесь вы можете создавать задания для пользователей.", 
                                    reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "admin_task_add")
async def callback_admin_task_add(callback: types.CallbackQuery, state: FSMContext):
    if not bot_data.is_admin(callback.from_user.id): return
    await callback.message.answer("📝 Введите текст задания (например: Подпишись на наш канал):")
    await state.set_state(AdminStates.waiting_task_text)
    await callback.answer()

@dp.message(AdminStates.waiting_task_text)
async def admin_receive_task_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписка на канал", callback_data="type_sub")],
        [InlineKeyboardButton(text="✅ Ручное подтверждение", callback_data="type_manual")]
    ])
    await message.answer(" Выберите тип задания:", reply_markup=kb)
    await state.set_state(AdminStates.waiting_task_type)

@dp.callback_query(AdminStates.waiting_task_type)
async def admin_receive_task_type(callback: types.CallbackQuery, state: FSMContext):
    task_type = callback.data.split("_")[1]
    await state.update_data(type=task_type)
    
    if task_type == "sub":
        await callback.message.answer(bot_data.tr(callback.from_user.id, "admin_task_target_tip"))
        await state.set_state(AdminStates.waiting_task_target)
    else:
        await state.update_data(target="none")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Доп. лимиты", callback_data="reward_creations")],
            [InlineKeyboardButton(text="💎 Temp Premium (Pro)", callback_data="reward_premium")]
        ])
        await callback.message.answer("🎁 Выберите тип награды:", reply_markup=kb)
        await state.set_state(AdminStates.waiting_reward_type)
    await callback.answer()

@dp.message(AdminStates.waiting_task_target)
async def admin_receive_task_target(message: types.Message, state: FSMContext):
    target = message.text.strip()
    
    # Автоматическая очистка ссылок
    if "t.me/" in target:
        target = target.split("t.me/")[-1]
        if not target.startswith("@") and not target.isdigit() and not target.startswith("-"):
            target = "@" + target
    elif not target.startswith("@") and not target.isdigit() and not target.startswith("-"):
        target = "@" + target
        
    await state.update_data(target=target)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Доп. лимиты", callback_data="reward_creations")],
        [InlineKeyboardButton(text="💎 Temp Premium (Pro)", callback_data="reward_premium")]
    ])
    await message.answer(f"✅ Цель сохранена как: `{target}`\n\n🎁 Выберите тип награды:", reply_markup=kb, parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_reward_type)

@dp.callback_query(AdminStates.waiting_reward_type)
async def admin_receive_reward_type(callback: types.CallbackQuery, state: FSMContext):
    reward_type = callback.data.split("_")[1]
    await state.update_data(reward_type=reward_type)
    
    if reward_type == "creations":
        await callback.message.answer("🔢 Сколько дополнительных креаций выдать?")
    else:
        await callback.message.answer("⏳ На сколько дней выдать PRO статус?")
    
    await state.set_state(AdminStates.waiting_reward_value)
    await callback.answer()

@dp.message(AdminStates.waiting_reward_value)
async def admin_receive_reward_value(message: types.Message, state: FSMContext):
    try:
        val = int(message.text)
        data = await state.get_data()
        
        task_id = str(uuid.uuid4())[:8]
        new_task = {
            "id": task_id,
            "text": data['text'],
            "type": data['type'],
            "target": data['target'],
            "reward_type": data['reward_type'],
            "reward_value": val
        }
        
        bot_data.tasks.append(new_task)
        bot_data.save_data()
        
        await message.answer(f"✅ **Задание создано!**\n\nID: `{task_id}`\nТекст: {data['text']}\nТип: {data['type']}\nНаграда: {val} {'креаций' if data['reward_type'] == 'creations' else 'дней PRO'}", parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число!")

@dp.callback_query(F.data == "admin_task_list")
async def callback_admin_task_list(callback: types.CallbackQuery):
    if not bot_data.is_admin(callback.from_user.id): return
    
    if not bot_data.tasks:
        await callback.message.answer("❌ Заданий пока нет.")
        await callback.answer()
        return
        
    text = "📋 **Список заданий:**\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for t in bot_data.tasks:
        text += f"• `{t['id']}`: {t['text']} ({t['reward_value']} {t['reward_type']})\n"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"🗑 Удалить {t['id']}", callback_data=f"admin_task_del_{t['id']}")])
    
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_tasks_manage")])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_task_del_"))
async def callback_admin_task_del(callback: types.CallbackQuery):
    if not bot_data.is_admin(callback.from_user.id): return
    task_id = callback.data.split("_")[3]
    
    bot_data.tasks = [t for t in bot_data.tasks if t['id'] != task_id]
    bot_data.save_data()
    
    await callback.answer("✅ Задание удалено", show_alert=True)
    await callback_admin_task_list(callback)

# ═══════════════════════════════════════════════════════════════
# 🎁 СИСТЕМА ЗАДАНИЙ (ЮЗЕР)
# ═══════════════════════════════════════════════════════════════

@dp.message(F.text.in_(btn_texts("tasks_btn")))
async def cmd_tasks_menu(message: types.Message):
    user_id = message.from_user.id
    
    # Фильтруем задания, которые пользователь еще не выполнил
    completed = bot_data.user_completed_tasks.get(user_id, set())
    available_tasks = [t for t in bot_data.tasks if t['id'] not in completed]
    
    if not available_tasks:
        await message.answer("🎁 **Задания**\n\nНа данный момент новых заданий нет. Заходи позже! 😊", parse_mode="Markdown")
        return
        
    text = bot_data.tr(user_id, "tasks_menu")
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    
    for t in available_tasks:
        reward_text = ""
        if t['reward_type'] == "creations":
            reward_text = bot_data.tr(user_id, "task_reward_creations", count=t['reward_value'])
        else:
            reward_text = bot_data.tr(user_id, "task_reward_premium", days=t['reward_value'])
            
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"{t['text']} ({reward_text})", callback_data=f"task_view_{t['id']}")])
        
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("task_view_"))
async def callback_task_view(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    task_id = callback.data.split("_")[2]
    
    task = next((t for t in bot_data.tasks if t['id'] == task_id), None)
    if not task:
        await callback.answer("Задание не найдено", show_alert=True)
        return
        
    reward_text = ""
    if task['reward_type'] == "creations":
        reward_text = bot_data.tr(user_id, "task_reward_creations", count=task['reward_value'])
    else:
        reward_text = bot_data.tr(user_id, "task_reward_premium", days=task['reward_value'])
        
    text = (
        f"📋 **Задание:**\n{task['text']}\n\n"
        f"🎁 **Награда:** {reward_text}\n\n"
        f"Нажми кнопку ниже, чтобы подтвердить выполнение!"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Проверить выполнение", callback_data=f"task_check_{task_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="tasks_back")]
    ])
    
    if task['type'] == "sub" and task['target'].startswith("@"):
        kb.inline_keyboard.insert(0, [InlineKeyboardButton(text="📢 Перейти к каналу", url=f"https://t.me/{task['target'][1:]}")])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "tasks_back")
async def callback_tasks_back(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_tasks_menu(callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("task_check_"))
async def callback_task_check(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    task_id = callback.data.split("_")[2]
    
    task = next((t for t in bot_data.tasks if t['id'] == task_id), None)
    if not task:
        await callback.answer("Задание не найдено", show_alert=True)
        return
        
    if task_id in bot_data.user_completed_tasks.get(user_id, set()):
        await callback.answer(bot_data.tr(user_id, "task_already_done"), show_alert=True)
        return
        
    # Проверка выполнения
    is_done = False
    if task['type'] == "sub":
        try:
            member = await bot.get_chat_member(chat_id=task['target'], user_id=user_id)
            if member.status in ["member", "administrator", "creator"]:
                is_done = True
            else:
                # Вместо алерта - обновляем текст сообщения
                error_text = bot_data.tr(user_id, "task_not_subbed", target=task['target'])
                
                # Повторно генерируем кнопки
                reward_text = ""
                if task['reward_type'] == "creations":
                    reward_text = bot_data.tr(user_id, "task_reward_creations", count=task['reward_value'])
                else:
                    reward_text = bot_data.tr(user_id, "task_reward_premium", days=task['reward_value'])
                
                info_text = (
                    f"📋 **Задание:**\n{task['text']}\n\n"
                    f"🎁 **Награда:** {reward_text}\n\n"
                    f"{error_text}"
                )
                
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Проверить выполнение", callback_data=f"task_check_{task_id}")],
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="tasks_back")]
                ])
                if task['type'] == "sub" and task['target'].startswith("@"):
                    kb.inline_keyboard.insert(0, [InlineKeyboardButton(text="📢 Перейти к каналу", url=f"https://t.me/{task['target'][1:]}")])
                
                try:
                    await callback.message.edit_text(info_text, reply_markup=kb, parse_mode="Markdown")
                except:
                    pass # Сообщение может не измениться
                
                await callback.answer("❌ Вы еще не подписаны")
                return
        except Exception as e:
            await callback.answer(f"Ошибка проверки подписки: {e}", show_alert=True)
            return
    else:
        # Для ручных заданий считаем нажатие кнопки подтверждением (в простых ботах)
        is_done = True
        
    if is_done:
        # Выдаем награду
        reward_msg = ""
        if task['reward_type'] == "creations":
            # Просто уменьшаем счетчик использованных креаций ИЛИ увеличиваем лимит.
            # В нашей логике user_creations сбрасывается каждые 5 часов. 
            # Лучше всего выдать бонус как в рефералке - на время.
            # Но для простоты: просто вычтем из текущего счетчика.
            # Хотя лимиты жесткие в get_max_creations.
            # Давайте добавим в BotData метод выдачи награды.
            bot_data.user_creations[user_id] = max(0, bot_data.user_creations[user_id] - task['reward_value'])
            reward_msg = bot_data.tr(user_id, "task_reward_creations", count=task['reward_value'])
        else:
            # Выдаем Pro на X дней
            # У рефералки есть user_referral_bonus (срок окончания). Используем похожую логику.
            expiry = datetime.now() + timedelta(days=task['reward_value'])
            bot_data.user_referral_bonus[user_id] = expiry.isoformat()
            bot_data.set_user_plan(user_id, "pro")
            reward_msg = bot_data.tr(user_id, "task_reward_premium", days=task['reward_value'])
            
        bot_data.user_completed_tasks[user_id].add(task_id)
        bot_data.save_data()
        
        await callback.message.edit_text(bot_data.tr(user_id, "task_completed", reward=reward_msg), parse_mode="Markdown")
        await callback.answer("🎉 Поздравляем!", show_alert=True)

@dp.callback_query(F.data == "admin_back")
async def callback_admin_back(callback: types.CallbackQuery):
    await cmd_admin(callback.message)
    await callback.answer()

@dp.message(F.text.in_(btn_texts("gen_btn")))
async def menu_start_gen(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer(bot_data.tr(user_id, "blocked_perm"))
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(bot_data.tr(user_id, "blocked_temp", hours=hours_left))
        return
    
    await message.answer(bot_data.tr(user_id, "gen_prompt"))

@dp.message(F.text.in_(btn_texts("prem_btn")))
async def menu_premium(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer(bot_data.tr(user_id, "blocked_perm"))
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(bot_data.tr(user_id, "blocked_temp", hours=hours_left))
        return
    
    current_plan = bot_data.get_user_plan(user_id)
    used = bot_data.user_creations[user_id]
    plan_info = PLANS[current_plan]
    
    # Подготавливаем метки активности
    active_label = bot_data.tr(user_id, "prem_active")
    free_active = active_label if current_plan == "free" else ""
    pro_active = active_label if current_plan == "pro" else ""
    ultra_active = active_label if current_plan == "ultra" else ""
    
    text = bot_data.tr(
        user_id, "prem_msg",
        plan=plan_info['name'],
        used=used,
        max=plan_info['max_creations'] if plan_info['max_creations'] != float('inf') else "∞",
        reset_time=bot_data.get_reset_time_left(),
        free_active=free_active,
        pro_active=pro_active,
        ultra_active=ultra_active
    )
    
    await message.answer(text, parse_mode="Markdown", reply_markup=get_premium_choice_kb(user_id))

@dp.callback_query(F.data == "prem_stars")
async def callback_premium_stars(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await callback.message.edit_reply_markup(reply_markup=get_premium_plans_kb(user_id))
    await callback.answer()

@dp.message(F.text.in_(btn_texts("info_btn")))
async def menu_about(message: types.Message):
    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer(bot_data.tr(user_id, "blocked_perm"))
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(bot_data.tr(user_id, "blocked_temp", hours=hours_left))
        return
    
    plan = bot_data.get_user_plan(user_id)
    plan_info = PLANS[plan]
    
    text = bot_data.tr(
        user_id, "info",
        plan_name=plan_info['name'],
        input_size=plan_info['max_input_size'] // 1024,
        input_lines=plan_info['max_input_lines'],
        output_size=plan_info['max_output_size'] // (1024*1024) if plan_info['max_output_size'] != float('inf') else '∞'
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text.in_(btn_texts("tutor_btn")))
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
        await message.answer(bot_data.tr(user_id, "blocked_perm"))
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(bot_data.tr(user_id, "blocked_temp", hours=hours_left))
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
    # Игнорируем команды и кнопки меню (всех языков)
    if message.text.startswith("/"):
        return
    if message.text in ALL_MENU_BUTTONS:
        return

    user_id = message.from_user.id
    
    # Проверяем блокировки
    if bot_data.is_permanently_blocked(user_id):
        await message.answer(bot_data.tr(user_id, "blocked_perm"))
        return
    
    if bot_data.is_temp_blocked(user_id):
        unblock_time = bot_data.temp_blocked_users.get(user_id)
        if unblock_time:
            hours_left = int((unblock_time - datetime.now()).total_seconds() / 3600)
            await message.answer(bot_data.tr(user_id, "blocked_temp", hours=hours_left))
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