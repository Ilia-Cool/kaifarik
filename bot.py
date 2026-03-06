import asyncio
import logging
import os
import math
import json
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

import aiohttp
import matplotlib.pyplot as plt
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ===================== КОНФИГУРАЦИЯ =====================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не установлен!")

bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# Файл для хранения администраторов
ADMINS_FILE = "admins.json"

# ===================== РАБОТА С ФАЙЛОМ АДМИНОВ =====================
def load_admins() -> Set[int]:
    """Загружает список админов из JSON-файла"""
    if not os.path.exists(ADMINS_FILE):
        # Если файла нет, создаём пустой
        with open(ADMINS_FILE, "w") as f:
            json.dump([], f)
        return set()
    with open(ADMINS_FILE, "r") as f:
        data = json.load(f)
        return set(data)

def save_admins(admins: Set[int]):
    """Сохраняет список админов в JSON-файл"""
    with open(ADMINS_FILE, "w") as f:
        json.dump(list(admins), f, indent=2)

def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь админом (загружаем свежий список)"""
    return user_id in load_admins()

# ===================== ХРАНИЛИЩЕ ПОИСКА МОДОВ =====================
user_search_results: Dict[int, List[dict]] = {}
user_current_page: Dict[int, int] = {}

# ===================== СТАТИСТИКА СООБЩЕНИЙ =====================
# Счётчики: для групп – по chat_id, для лички – по user_id
message_stats = {}  # ключ: chat_id или user_id (int), значение: количество

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================
def get_user_mention(user: types.User) -> str:
    if user.username:
        return f"@{user.username}"
    return f"<a href='tg://user?id={user.id}'>{user.full_name}</a>"

# ===================== ОБНОВЛЁННЫЙ КОНВЕРТЕР ВАЛЮТ =====================
currency_cache = {}
last_cache_update = None

async def get_exchange_rates() -> Optional[Dict[str, float]]:
    """
    Возвращает словарь {валюта: курс в USD за 1 единицу}
    Пример: 'USD': 1.0, 'RUB': 0.011, 'BTC': 65000.0
    """
    global currency_cache, last_cache_update
    now = datetime.now()
    if last_cache_update and (now - last_cache_update).seconds < 3600:
        return currency_cache

    async with aiohttp.ClientSession() as session:
        try:
            # 1. Фиатные курсы (exchangerate-api.com даёт количество валюты за 1 USD)
            async with session.get("https://api.exchangerate-api.com/v4/latest/USD") as resp:
                if resp.status != 200:
                    return currency_cache or {}
                data = await resp.json()
                fiat_rates = data.get("rates", {})  # {'RUB': 90.0} означает 90 RUB за 1 USD

            # 2. Криптокурсы (CoinGecko – цена в USD за 1 монету)
            crypto_ids = ["bitcoin", "ethereum", "binancecoin", "solana", "cardano"]
            crypto_map = {
                "bitcoin": "BTC",
                "ethereum": "ETH",
                "binancecoin": "BNB",
                "solana": "SOL",
                "cardano": "ADA"
            }
            crypto_rates = {}
            for crypto_id in crypto_ids:
                async with session.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": crypto_id, "vs_currencies": "usd"}
                ) as cr_resp:
                    if cr_resp.status == 200:
                        cr_data = await cr_resp.json()
                        if crypto_id in cr_data:
                            symbol = crypto_map[crypto_id]
                            crypto_rates[symbol] = cr_data[crypto_id]["usd"]  # USD за 1 монету

            # 3. Собираем общий словарь: все курсы в USD за единицу
            rates = {"USD": 1.0}
            # Фиат: конвертируем из кол-ва валюты за USD в USD за единицу
            for code, value in fiat_rates.items():
                if value > 0:
                    rates[code] = 1.0 / value  # USD за 1 единицу
            # Крипта (уже USD за единицу)
            rates.update(crypto_rates)

            currency_cache = rates
            last_cache_update = now
            return rates
        except Exception as e:
            logging.error(f"Ошибка получения курсов: {e}")
            return currency_cache  # возвращаем старое, если есть

@dp.message(Command("currency"))
async def cmd_currency(message: types.Message, command: CommandObject):
    args = command.args
    if not args:
        await message.answer(
            "❌ Использование:\n"
            "/currency 100 USD RUB\n"
            "/currency 0.5 BTC USD\n"
            "/currency 1 ETH BTC\n\n"
            "Доступные валюты: USD, EUR, RUB, GBP, JPY, CNY, BTC, ETH, BNB, SOL, ADA"
        )
        return

    parts = args.split()
    if len(parts) != 3:
        await message.answer("❌ Нужно: сумма исходная_валюта целевая_валюта")
        return

    try:
        amount = float(parts[0])
        from_curr = parts[1].upper()
        to_curr = parts[2].upper()

        rates = await get_exchange_rates()
        if not rates:
            await message.answer("❌ Не удалось получить курсы. Попробуйте позже.")
            return

        if from_curr not in rates:
            await message.answer(f"❌ Валюта {from_curr} не поддерживается")
            return
        if to_curr not in rates:
            await message.answer(f"❌ Валюта {to_curr} не поддерживается")
            return

        # Конвертация: сумма в USD = amount * курс(from)
        usd_amount = amount * rates[from_curr]
        # Сумма в целевой = usd_amount / курс(to)
        result = usd_amount / rates[to_curr]

        # Форматирование
        if result < 0.01:
            result_str = f"{result:.8f}"
        elif result < 1:
            result_str = f"{result:.4f}"
        else:
            result_str = f"{result:.2f}"

        # Обратный курс для информации
        inverse_rate = rates[from_curr] / rates[to_curr]

        await message.answer(
            f"💱 <b>{amount} {from_curr}</b> = <b>{result_str} {to_curr}</b>\n"
            f"Курс: 1 {from_curr} = {inverse_rate:.4f} {to_curr}",
            parse_mode="HTML"
        )

    except ValueError:
        await message.answer("❌ Сумма должна быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ===================== КОМАНДЫ МОДЕРАЦИИ (без изменений) =====================
# ... (весь блок с kick, ban, mute, unmute, clear остаётся как в предыдущем ответе)
# Для краткости я не копирую их сюда, но в реальном файле они должны быть.
# В финальном ответе я предоставлю полный код со всеми функциями.

# ===================== НОВАЯ КОМАНДА /TRY =====================
@dp.message(Command("try"))
async def cmd_try(message: types.Message):
    answers = [
        "Повезло!",
        "Не повезло.",
        "Удача сегодня на Вашей стороне!",
        "К сожалению, сегодня не Ваш день."
    ]
    await message.answer(random.choice(answers))

# ===================== НОВАЯ КОМАНДА /WHOIS =====================
@dp.message(Command("whois"))
async def cmd_whois(message: types.Message, command: CommandObject):
    if message.chat.type == "private":
        await message.answer("❌ Эта команда работает только в группах!")
        return

    role = command.args
    if not role:
        await message.answer("❌ Укажите роль. Пример: /whois идиот")
        return

    try:
        # Получаем список участников (не более 200 для избежания таймаутов)
        members = []
        async for member in bot.get_chat_members(message.chat.id, limit=200):
            if not member.user.is_bot:  # исключаем ботов
                members.append(member.user)

        if not members:
            await message.answer("❌ В чате нет участников (кроме ботов).")
            return

        chosen = random.choice(members)
        mention = get_user_mention(chosen)
        await message.answer(f"{mention} сегодня {role}", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ===================== УПРАВЛЕНИЕ АДМИНАМИ =====================
def require_admin(func):
    """Декоратор для проверки прав администратора"""
    async def wrapper(message: types.Message, *args, **kwargs):
        if not is_admin(message.from_user.id):
            await message.answer("❌ У вас нет прав администратора бота.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

@dp.message(Command("addadmin"))
@require_admin
async def cmd_addadmin(message: types.Message, command: CommandObject):
    args = command.args
    if not args:
        await message.answer("❌ Укажите ID пользователя. Пример: /addadmin 123456789")
        return
    try:
        new_id = int(args)
        admins = load_admins()
        if new_id in admins:
            await message.answer("⚠️ Этот пользователь уже является администратором.")
        else:
            admins.add(new_id)
            save_admins(admins)
            await message.answer(f"✅ Пользователь с ID {new_id} добавлен в администраторы.")
    except ValueError:
        await message.answer("❌ ID должен быть числом.")

@dp.message(Command("removeadmin"))
@require_admin
async def cmd_removeadmin(message: types.Message, command: CommandObject):
    args = command.args
    if not args:
        await message.answer("❌ Укажите ID пользователя. Пример: /removeadmin 123456789")
        return
    try:
        rem_id = int(args)
        admins = load_admins()
        if rem_id not in admins:
            await message.answer("⚠️ Этот пользователь не является администратором.")
        else:
            admins.remove(rem_id)
            save_admins(admins)
            await message.answer(f"✅ Пользователь с ID {rem_id} удалён из администраторов.")
    except ValueError:
        await message.answer("❌ ID должен быть числом.")

@dp.message(Command("listadmins"))
@require_admin
async def cmd_listadmins(message: types.Message):
    admins = load_admins()
    if not admins:
        await message.answer("Список администраторов пуст.")
        return
    lines = ["📋 Список администраторов:"]
    for admin_id in admins:
        # Попробуем получить имя (если бот знает этого юзера)
        try:
            user = await bot.get_chat(admin_id)
            name = user.full_name
        except:
            name = "Неизвестный"
        lines.append(f"• {name} (ID: {admin_id})")
    await message.answer("\n".join(lines))

# ===================== СТАТИСТИКА СООБЩЕНИЙ =====================
# Хендлер, который считает все сообщения
@dp.message()
async def count_messages(message: types.Message):
    key = message.chat.id if message.chat.type != "private" else message.from_user.id
    message_stats[key] = message_stats.get(key, 0) + 1

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.chat.type == "private":
        key = message.from_user.id
        total = message_stats.get(key, 0)
        await message.answer(f"📊 Вы отправили мне {total} сообщений.")
    else:
        key = message.chat.id
        total = message_stats.get(key, 0)
        await message.answer(f"📊 В этом чате отправлено {total} сообщений с момента запуска бота.")

# ===================== ОСТАЛЬНЫЕ КОМАНДЫ =====================
# Здесь размещаются команды /calc, /mod, /start, /help и всё остальное
# (из предыдущей версии, с небольшими корректировками)

# ===================== ЗАПУСК =====================
async def main():
    # При старте убедимся, что файл админов существует
    load_admins()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
