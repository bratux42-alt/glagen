import asyncio
import logging
import os
import shutil
import sys
import subprocess
import uuid
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# --- ⚙️ НАСТРОЙКИ ---
# Бот попробует взять токен из настроек сервера. Если не найдет — возьмет тот, что в кавычках.
TOKEN_ENV = os.getenv("BOT_TOKEN") 
API_TOKEN = TOKEN_ENV if TOKEN_ENV else '8585991229:AAFP14zeZDwBGW02mTSEt_ALJWKcaIcjNZM'

# Папка для временных файлов
BASE_TEMP_DIR = "temp_work"

# --- 🚀 ИНИЦИАЛИЗАЦИЯ ---
logging.basicConfig(level=logging.INFO)
if not API_TOKEN or "ВСТАВЬ" in API_TOKEN:
    print("❌ ОШИБКА: Токен не найден! Укажи BOT_TOKEN в настройках сервера или впиши в код.")
    # sys.exit() # Раскомментируй на сервере, чтобы бот не запускался без токена

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Словарь для хранения путей к файлам: {user_id: (file_path, dir_path)}
users_files = {}

# Очистка мусора при старте
if os.path.exists(BASE_TEMP_DIR):
    shutil.rmtree(BASE_TEMP_DIR)
os.makedirs(BASE_TEMP_DIR, exist_ok=True)

# --- 📱 КЛАВИАТУРЫ ---

# Главное меню (внизу)
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🚀 Начать создание")],
        [KeyboardButton(text="ℹ️ Инфо"), KeyboardButton(text="📹 Тутор")]
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери действие..."
)

# Кнопка под сообщением для скачивания
def get_download_kb(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📂 Скачать файл", callback_data=f"get_file_{user_id}")]])


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
    # 1. Проверка безопасности
    is_safe, banned_word = is_safe_code(code_content)
    if not is_safe:
        await message.answer(f"⛔ **Код заблокирован!**\nНайдена запрещенная команда: `{banned_word}`.\n\nВ целях безопасности запрещены: os, sys, input, интернет.", parse_mode="Markdown")
        shutil.rmtree(task_dir)
        return

    try:
        status_msg = await message.answer("⚙️ Проверка пройдена. Запускаю...")
        
        # 2. Запуск скрипта в отдельном процессе
        # timeout=15 секунд — чтобы никто не вешал сервер надолго
        proc = subprocess.run(
            [sys.executable, "script.py"],
            cwd=task_dir,       
            capture_output=True,
            text=True,
            timeout=15          
        )

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
                users_files[message.from_user.id] = (result_file, task_dir)
                
                await status_msg.edit_text(
                    f"✅ Готово! Файл создан: {generated_files[0]}", 
                    reply_markup=get_download_kb(message.from_user.id)
                )
            else:
                await status_msg.edit_text("🤔 Код сработал без ошибок, но файл не создался.\nТы точно написал `doc.save(...)`?")
                shutil.rmtree(task_dir)

    except subprocess.TimeoutExpired:
        await status_msg.edit_text("⏰ Время вышло! Скрипт работал дольше 15 секунд.")
        shutil.rmtree(task_dir)
    except Exception as e:
        await status_msg.edit_text(f"❌ Системная ошибка: {e}")
        shutil.rmtree(task_dir)


# --- 📨 ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Привет! Я публичный генератор файлов.\nКидай код — получай результат.", reply_markup=main_kb)

@dp.message(F.text == "🚀 Начать создание")
async def menu_start_gen(message: types.Message):
    await message.answer("👇 Просто отправь мне код (текстом или файлом .py).")

@dp.message(F.text == "ℹ️ Инфо")
async def menu_about(message: types.Message):
    text = (
        "🤖 **Bot Generator Public**\n"
        "Безопасная песочница для Python.\n\n"
        "✅ **Можно:** docx, pptx, xlsx, pdf, matplotlib, qrcode.\n"
        "⛔ **Нельзя:** os, sys, input, интернет.\n"
        "⏳ **Лимит:** 15 секунд на выполнение."
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "📹 Тутор")
async def menu_tutorial(message: types.Message):
    if os.path.exists("tutor.mp4"):
        await message.answer_video(FSInputFile("tutor.mp4"), caption="🎥 Как пользоваться ботом")
    else:
        await message.answer("⚠️ Видео 'tutor.mp4' не загружено на сервер.")

# 1. Если прислали ФАЙЛ
@dp.message(F.document)
async def handle_document(message: types.Message):
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

    await execute_code(message, task_dir, content)

# 2. Если прислали ТЕКСТ
@dp.message(F.text)
async def handle_text_code(message: types.Message):
    # Игнорируем нажатия кнопок меню
    if message.text in ["🚀 Начать создание", "ℹ️ Инфо", "📹 Тутор"]: return

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
    
    await execute_code(message, task_dir, code)


# --- 📥 КНОПКА СКАЧИВАНИЯ ---
@dp.callback_query(F.data.startswith("get_file_"))
async def callback_send_file(callback: types.CallbackQuery):
    user_id = callback.from_user.id
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