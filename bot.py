import asyncio
import logging
import os
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import aiohttp
import matplotlib.pyplot as plt
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Токен берется из переменных окружения
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")

# ID администраторов (можно указать через запятую в переменной окружения)
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",") if id]

bot = Bot(token=TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# ===================== ХРАНИЛИЩЕ ДАННЫХ =====================
# Временное хранение результатов поиска модов (в реальном проекте лучше использовать БД)
user_search_results: Dict[int, List[dict]] = {}
user_current_page: Dict[int, int] = {}

# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================
def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in ADMIN_IDS

def get_user_mention(user: types.User) -> str:
    """Получить упоминание пользователя"""
    if user.username:
        return f"@{user.username}"
    return f"<a href='tg://user?id={user.id}'>{user.full_name}</a>"

# ===================== КОМАНДЫ МОДЕРАЦИИ =====================
async def check_admin_rights(message: types.Message) -> bool:
    """Проверка прав администратора в чате"""
    if not message.reply_to_message:
        await message.answer("❌ Эта команда должна быть ответом на сообщение пользователя!")
        return False
    
    if message.chat.type == "private":
        await message.answer("❌ Команды модерации работают только в группах!")
        return False
    
    chat_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if chat_member.status not in ["administrator", "creator"]:
        await message.answer("❌ У вас нет прав администратора в этом чате!")
        return False
    
    return True

@dp.message(Command("kick"))
async def cmd_kick(message: types.Message):
    """Кикнуть пользователя"""
    if not await check_admin_rights(message):
        return
    
    user_to_kick = message.reply_to_message.from_user
    
    try:
        await bot.kick_chat_member(message.chat.id, user_to_kick.id)
        await bot.unban_chat_member(message.chat.id, user_to_kick.id)  # Разбаниваем сразу, чтобы мог вернуться
        await message.answer(f"👢 Пользователь {get_user_mention(user_to_kick)} был кикнут.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("ban"))
async def cmd_ban(message: types.Message, command: CommandObject):
    """Забанить пользователя (навсегда)"""
    if not await check_admin_rights(message):
        return
    
    user_to_ban = message.reply_to_message.from_user
    
    try:
        await bot.kick_chat_member(message.chat.id, user_to_ban.id)
        await message.answer(f"🔨 Пользователь {get_user_mention(user_to_ban)} был забанен навсегда.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("mute"))
async def cmd_mute(message: types.Message, command: CommandObject):
    """Замутить пользователя (временный мут)"""
    if not await check_admin_rights(message):
        return
    
    args = command.args
    if not args:
        await message.answer("❌ Укажите время мута (например: /mute 10m или /mute 2h)")
        return
    
    user_to_mute = message.reply_to_message.from_user
    
    # Парсим время
    time_str = args.lower().strip()
    duration_map = {
        'm': 60,
        'h': 3600,
        'd': 86400
    }
    
    try:
        if time_str[-1] in duration_map:
            value = int(time_str[:-1])
            unit = time_str[-1]
            duration = value * duration_map[unit]
            until_date = datetime.now() + timedelta(seconds=duration)
        else:
            await message.answer("❌ Неправильный формат. Используйте: /mute 10m, /mute 2h, /mute 1d")
            return
    except:
        await message.answer("❌ Неправильный формат времени")
        return
    
    try:
        permissions = types.ChatPermissions(can_send_messages=False)
        await bot.restrict_chat_member(
            message.chat.id, 
            user_to_mute.id, 
            permissions=permissions,
            until_date=until_date
        )
        await message.answer(
            f"🔇 Пользователь {get_user_mention(user_to_mute)} "
            f"замучен на {value}{'минут' if unit=='m' else 'часов' if unit=='h' else 'дней'}."
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("unmute"))
async def cmd_unmute(message: types.Message):
    """Размутить пользователя"""
    if not await check_admin_rights(message):
        return
    
    user_to_unmute = message.reply_to_message.from_user
    
    try:
        permissions = types.ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        await bot.restrict_chat_member(
            message.chat.id, 
            user_to_unmute.id, 
            permissions=permissions
        )
        await message.answer(f"🔊 Пользователь {get_user_mention(user_to_unmute)} размучен.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("clear"))
async def cmd_clear(message: types.Message, command: CommandObject):
    """Очистить сообщения (нужно право на удаление)"""
    if message.chat.type == "private":
        await message.answer("❌ Команда работает только в группах!")
        return
    
    args = command.args
    if not args:
        await message.answer("❌ Укажите количество сообщений для удаления (например: /clear 10)")
        return
    
    try:
        count = int(args)
        if count < 1 or count > 100:
            await message.answer("❌ Количество должно быть от 1 до 100")
            return
        
        # Удаляем команду
        await message.delete()
        
        # Удаляем указанное количество сообщений
        async for msg in bot.get_chat_history(message.chat.id, limit=count):
            try:
                await msg.delete()
            except:
                pass
        
        confirm = await message.answer(f"✅ Удалено {count} сообщений")
        await asyncio.sleep(3)
        await confirm.delete()
    except ValueError:
        await message.answer("❌ Укажите число!")

# ===================== КАЛЬКУЛЯТОР =====================
@dp.message(Command("calc"))
async def cmd_calc(message: types.Message, command: CommandObject):
    """Калькулятор с поддержкой сложных операций"""
    expression = command.args
    if not expression:
        await message.answer(
            "❌ Введите выражение для вычисления.\n"
            "Примеры:\n"
            "/calc 2+2*2\n"
            "/calc sqrt(16)\n"
            "/calc 2^10\n"
            "/calc sin(30)\n"
            "/calc log(100)"
        )
        return
    
    # Заменяем ^ на ** для возведения в степень
    expression = expression.replace('^', '**')
    
    # Добавляем математические функции
    allowed_names = {
        k: v for k, v in math.__dict__.items() if not k.startswith("__")
    }
    allowed_names.update({"abs": abs, "round": round})
    
    # Безопасное вычисление
    try:
        # Компилируем выражение
        code = compile(expression, "<string>", "eval")
        
        # Проверяем, что используются только разрешенные имена
        for name in code.co_names:
            if name not in allowed_names:
                await message.answer(f"❌ Использование '{name}' запрещено!")
                return
        
        result = eval(code, {"__builtins__": {}}, allowed_names)
        
        # Форматируем результат
        if isinstance(result, float):
            if result.is_integer():
                result = int(result)
            else:
                result = round(result, 10)  # Округляем до 10 знаков
        
        await message.answer(f"🧮 Результат: `{expression} = {result}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка в выражении: {e}")

# ===================== ПОИСК МОДОВ НА MODRINTH =====================
@dp.message(Command("mod"))
async def cmd_mod(message: types.Message, command: CommandObject):
    """Поиск модов на Modrinth"""
    query = command.args
    if not query:
        await message.answer("❌ Введите название мода для поиска (например: /mod sodium)")
        return
    
    await message.answer(f"🔍 Ищу моды по запросу '{query}'...")
    
    async with aiohttp.ClientSession() as session:
        try:
            # API Modrinth для поиска
            params = {
                "query": query,
                "limit": 20,  # Получаем побольше для пагинации
                "index": "relevance"
            }
            async with session.get("https://api.modrinth.com/v2/search", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    hits = data.get("hits", [])
                    
                    if not hits:
                        await message.answer("❌ Ничего не найдено.")
                        return
                    
                    # Сохраняем результаты для пользователя
                    user_id = message.from_user.id
                    user_search_results[user_id] = hits[:20]  # Сохраняем до 20
                    user_current_page[user_id] = 0
                    
                    await send_mod_page(message, user_id, 0)
                else:
                    await message.answer("❌ Ошибка при обращении к Modrinth API")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

async def send_mod_page(message: types.Message, user_id: int, page: int):
    """Отправить страницу с модами"""
    results = user_search_results.get(user_id, [])
    if not results or page < 0 or page >= len(results):
        return
    
    mod = results[page]
    
    # Формируем сообщение
    text = f"📦 <b>{mod['title']}</b>\n"
    text += f"👤 Автор: {mod['author']}\n"
    text += f"⬇️ Скачиваний: {mod['downloads']:,}\n"
    text += f"⭐ Версия: {mod.get('latest_version', 'N/A')}\n"
    text += f"📝 {mod.get('description', 'Нет описания')[:200]}...\n\n"
    text += f"🔗 <a href='https://modrinth.com/mod/{mod['slug']}'>Открыть на Modrinth</a>"
    
    # Клавиатура для навигации
    keyboard = InlineKeyboardBuilder()
    
    if page > 0:
        keyboard.button(text="◀️ Назад", callback_data=f"mod_prev_{page}")
    if page < len(results) - 1:
        keyboard.button(text="Вперед ▶️", callback_data=f"mod_next_{page}")
    
    keyboard.button(text="❌ Закрыть", callback_data="mod_close")
    keyboard.adjust(2)
    
    await message.answer(text, reply_markup=keyboard.as_markup(), parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("mod_"))
async def mod_callback(callback: types.CallbackQuery):
    """Обработка навигации по модам"""
    user_id = callback.from_user.id
    data = callback.data
    
    if data == "mod_close":
        await callback.message.delete()
        await callback.answer()
        return
    
    parts = data.split("_")
    action = parts[1]  # prev или next
    current_page = int(parts[2])
    
    if action == "prev":
        new_page = current_page - 1
    else:  # next
        new_page = current_page + 1
    
    user_current_page[user_id] = new_page
    
    # Обновляем сообщение
    await callback.message.delete()
    await send_mod_page(callback.message, user_id, new_page)
    await callback.answer()

# ===================== КОНВЕРТЕР ВАЛЮТ =====================
# Кэш для курсов валют
currency_cache = {}
last_cache_update = None

async def get_exchange_rates() -> Optional[Dict]:
    """Получение курсов валют (фиат + крипто)"""
    global currency_cache, last_cache_update
    
    # Обновляем кэш раз в час
    if last_cache_update and (datetime.now() - last_cache_update).seconds < 3600:
        return currency_cache
    
    async with aiohttp.ClientSession() as session:
        try:
            # Получаем курсы фиатных валют (относительно USD)
            async with session.get("https://api.exchangerate-api.com/v4/latest/USD") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rates = data.get("rates", {})
                    
                    # Добавляем криптовалюты (относительно USD)
                    crypto_ids = ["bitcoin", "ethereum", "binancecoin", "solana", "cardano"]
                    crypto_rates = {}
                    
                    # Получаем курсы криптовалют с CoinGecko
                    for crypto in crypto_ids:
                        async with session.get(
                            f"https://api.coingecko.com/api/v3/simple/price",
                            params={"ids": crypto, "vs_currencies": "usd"}
                        ) as crypto_resp:
                            if crypto_resp.status == 200:
                                crypto_data = await crypto_resp.json()
                                if crypto in crypto_data:
                                    # Конвертируем в название валюты (BTC, ETH и т.д.)
                                    symbol = {
                                        "bitcoin": "BTC",
                                        "ethereum": "ETH",
                                        "binancecoin": "BNB",
                                        "solana": "SOL",
                                        "cardano": "ADA"
                                    }.get(crypto, crypto.upper())
                                    crypto_rates[symbol] = crypto_data[crypto]["usd"]
                    
                    # Объединяем все курсы
                    rates.update(crypto_rates)
                    currency_cache = rates
                    last_cache_update = datetime.now()
                    return rates
        except Exception as e:
            logging.error(f"Ошибка получения курсов: {e}")
            return currency_cache  # Возвращаем старый кэш если есть

@dp.message(Command("currency"))
async def cmd_currency(message: types.Message, command: CommandObject):
    """Конвертер валют"""
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
        await message.answer("❌ Неправильный формат. Нужно: сумма исходная_валюта целевая_валюта")
        return
    
    try:
        amount = float(parts[0])
        from_currency = parts[1].upper()
        to_currency = parts[2].upper()
        
        rates = await get_exchange_rates()
        if not rates:
            await message.answer("❌ Не удалось получить курсы валют. Попробуйте позже.")
            return
        
        # Конвертируем через USD (базовая валюта)
        if from_currency == "USD":
            usd_amount = amount
        elif from_currency in rates:
            usd_amount = amount / rates[from_currency]
        else:
            await message.answer(f"❌ Валюта {from_currency} не найдена")
            return
        
        if to_currency == "USD":
            result = usd_amount
        elif to_currency in rates:
            result = usd_amount * rates[to_currency]
        else:
            await message.answer(f"❌ Валюта {to_currency} не найдена")
            return
        
        # Форматируем результат
        if result < 0.01:
            result_str = f"{result:.8f}"
        elif result < 1:
            result_str = f"{result:.4f}"
        else:
            result_str = f"{result:.2f}"
        
        await message.answer(
            f"💱 <b>{amount} {from_currency}</b> = <b>{result_str} {to_currency}</b>\n"
            f"Курс: 1 {from_currency} = {rates.get(from_currency, 1) / rates.get(to_currency, 1):.4f} {to_currency}",
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer("❌ Сумма должна быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ===================== КОМАНДА ПОМОЩИ =====================
@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    """Помощь по командам"""
    text = (
        "🤖 <b>Многофункциональный бот</b>\n\n"
        
        "<b>🛡 Модерация (только для админов в группах):</b>\n"
        "/kick - кикнуть (ответом на сообщение)\n"
        "/ban - забанить навсегда (ответом)\n"
        "/mute 10m - замутить (10m, 2h, 1d)\n"
        "/unmute - размутить (ответом)\n"
        "/clear 10 - удалить сообщения\n\n"
        
        "<b>🧮 Калькулятор:</b>\n"
        "/calc 2+2*2\n"
        "/calc sqrt(16)\n"
        "/calc 2^10\n"
        "/calc sin(30)\n\n"
        
        "<b>🎮 Поиск модов на Modrinth:</b>\n"
        "/mod sodium - поиск модов\n"
        "(можно листать результаты)\n\n"
        
        "<b>💱 Конвертер валют:</b>\n"
        "/currency 100 USD RUB\n"
        "/currency 0.5 BTC USD\n"
        "/currency 1 ETH BTC\n\n"
        
        "<b>ℹ️ Информация:</b>\n"
        "/help - это сообщение"
    )
    
    await message.answer(text, parse_mode="HTML")

# ===================== ЗАПУСК БОТА =====================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
