import os
import json
import asyncio
import base64
import aiohttp
import subprocess
import tempfile
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from github import Github, GithubException

# --- Конфигурация ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
REPO_NAME      = "AlexanderRU44/V-Merge.github.io"
CONFIGS_URL    = "https://raw.githubusercontent.com/AlexanderRU44/V-Merge.github.io/refs/heads/main/output/merged.txt"
STATE_PATH     = "bot_state.json"

# --- GitHub клиент (только для состояния) ---
g = Github(GITHUB_TOKEN) if GITHUB_TOKEN else None
repo = g.get_repo(REPO_NAME) if g else None

# --- Глобальное состояние ---
active_pool = []
current_index = 0
is_checking = False

# ============ Работа с GitHub (состояние) ============
def load_state():
    global current_index
    if not repo: return
    try:
        f = repo.get_contents(STATE_PATH, ref="main")
        content = base64.b64decode(f.content).decode("utf-8")
        state = json.loads(content)
        current_index = state.get("index", 0)
        print(f"Восстановлен индекс: {current_index}")
    except Exception as e:
        print(f"Не удалось загрузить состояние: {e}")
        current_index = 0

def save_state():
    if not repo: return
    try:
        content = json.dumps({"index": current_index})
        try:
            f = repo.get_contents(STATE_PATH, ref="main")
            repo.update_file(STATE_PATH, "update bot state", content, sha=f.sha, branch="main")
        except GithubException as e:
            if e.status == 404:
                repo.create_file(STATE_PATH, "init bot state", content, branch="main")
    except Exception as e:
        print(f"Не удалось сохранить состояние: {e}")

# ============ Загрузка конфигов ============
async def load_configs():
    global active_pool
    print(f"Загрузка конфигов из {CONFIGS_URL}...")
    async with aiohttp.ClientSession() as session:
        async with session.get(CONFIGS_URL) as resp:
            if resp.status != 200:
                print(f"Ошибка загрузки: HTTP {resp.status}")
                return
            text = await resp.text()
            
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
            
    active_pool = lines
    print(f"Загружено {len(active_pool)} конфигов.")

# ============ Проверка конфига ============
async def check_config(uri: str) -> bool:
    """
    Проверяет конфиг.
    ВНИМАНИЕ: Для реальной проверки нужен установленный xray-core в системе.
    """
    # --- ЗАГЛУШКА ДЛЯ ТЕСТА ---
    # Пока не настроен xray, бот будет считать рабочими все конфиги.
    # await asyncio.sleep(0.5)
    # return True 
    
    # --- РЕАЛЬНАЯ ПРОВЕРКА (требует xray) ---
    # Пример вызова xray (если бинарник есть в PATH):
    # try:
    #     # Тут нужна логика парсинга URI в JSON формат xray
    #     # ...
    #     proc = await asyncio.create_subprocess_exec(
    #         "xray", "-test", "-config", "stdin:",
    #         stdin=asyncio.subprocess.PIPE,
    #         stdout=asyncio.subprocess.PIPE,
    #         stderr=asyncio.subprocess.PIPE
    #     )
    #     stdout, stderr = await proc.communicate(input=json_config.encode())
    #     return proc.returncode == 0
    # except Exception as e:
    #     print(f"Ошибка проверки: {e}")
    #     return False
    
    # Временно возвращаем True для всех
    return True

# ============ Основная логика ============
async def get_working_config():
    global active_pool, current_index, is_checking
    
    if is_checking:
        return "⏳ Уже идет проверка, подождите..."
    
    if not active_pool:
        await load_configs()
        if not active_pool:
            return "❌ Не удалось загрузить конфиги с GitHub."

    is_checking = True
    try:
        MAX_CHECKS = 10
        
        for _ in range(MAX_CHECKS):
            if not active_pool:
                return "❌ Пул пуст! Все конфиги проверены и нерабочие."

            if current_index >= len(active_pool):
                current_index = 0

            config = active_pool[current_index]
            print(f"Проверяем: {config[:40]}...")
            
            is_working = await check_config(config)
            
            if is_working:
                current_index = (current_index + 1) % len(active_pool)
                save_state()
                return f"✅ Рабочий конфиг:\n\n<code>{config}</code>"
            else:
                print(f"Удален нерабочий: {config[:40]}...")
                active_pool.pop(current_index)
                
        return "⚠️ В этом запросе рабочих не найдено (проверено 10). Попробуйте снова."
    finally:
        is_checking = False

# ============ Telegram Хэндлеры ============
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для выдачи рабочих VPN-конфигов из репозитория V-Merge.\n"
        "Напиши /get, чтобы получить профиль."
    )

@dp.message(Command("get"))
async def cmd_get(message: types.Message):
    status_msg = await message.answer("🔎 Ищу рабочий конфиг...")
    result = await get_working_config()
    await status_msg.edit_text(result, parse_mode="HTML")

@dp.message(Command("reload"))
async def cmd_reload(message: types.Message):
    status_msg = await message.answer("🔄 Перезагружаю список конфигов...")
    await load_configs()
    await status_msg.edit_text(f"✅ Загружено {len(active_pool)} конфигов.")

# ============ Запуск ============
async def main():
    load_state()
    await load_configs()
    
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
