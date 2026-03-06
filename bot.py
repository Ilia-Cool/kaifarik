import asyncio
import logging
import os
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile

# Токен берется ТОЛЬКО из переменных окружения (их настроит хостинг)
TOKEN = os.getenv("BOT_TOKEN")

# Проверка, что токен вообще есть
if not TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена!")

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Функция получения цен за последние 7 дней с CoinGecko
def get_crypto_prices(coin_id: str, days: int = 7):
    """
    coin_id: 'bitcoin' или 'ethereum'
    """
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {
        'vs_currency': 'usd',
        'days': days,
        'interval': 'daily'
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        prices = data['prices']
        dates = [datetime.fromtimestamp(price[0] / 1000).strftime('%m/%d') for price in prices]
        values = [price[1] for price in prices]
        
        return dates, values
    except Exception as e:
        logging.error(f"Ошибка при получении данных для {coin_id}: {e}")
        return None, None

# Функция создания графика
def create_chart(dates, values, coin_name: str):
    plt.figure(figsize=(10, 5))
    plt.plot(dates, values, marker='o', linestyle='-', 
             color='b' if coin_name == 'Bitcoin' else 'orange')
    plt.title(f'{coin_name} (USD) - Последние 7 дней')
    plt.xlabel('Дата')
    plt.ylabel('Цена (USD)')
    plt.grid(True)
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    filename = f"{coin_name.lower()}_chart.png"
    plt.savefig(filename)
    plt.close()
    return filename

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот для отслеживания курса криптовалют.\n"
        "Используй команды:\n"
        "/bitcoin - график Bitcoin за неделю\n"
        "/ethereum - график Ethereum за неделю"
    )

# Команда /bitcoin
@dp.message(Command("bitcoin"))
async def cmd_bitcoin(message: types.Message):
    await message.answer("📊 Получаю данные по Bitcoin за последнюю неделю...")
    
    dates, values = get_crypto_prices('bitcoin')
    if dates and values:
        chart_file = create_chart(dates, values, 'Bitcoin')
        with open(chart_file, 'rb') as photo:
            await message.answer_photo(
                BufferedInputFile(photo.read(), filename=chart_file),
                caption=f"График Bitcoin (за последние 7 дней)\nТекущая цена: ${values[-1]:,.2f}"
            )
        os.remove(chart_file)
    else:
        await message.answer("❌ Не удалось получить данные. Попробуйте позже.")

# Команда /ethereum
@dp.message(Command("ethereum"))
async def cmd_ethereum(message: types.Message):
    await message.answer("📊 Получаю данные по Ethereum за последнюю неделю...")
    
    dates, values = get_crypto_prices('ethereum')
    if dates and values:
        chart_file = create_chart(dates, values, 'Ethereum')
        with open(chart_file, 'rb') as photo:
            await message.answer_photo(
                BufferedInputFile(photo.read(), filename=chart_file),
                caption=f"График Ethereum (за последние 7 дней)\nТекущая цена: ${values[-1]:,.2f}"
            )
        os.remove(chart_file)
    else:
        await message.answer("❌ Не удалось получить данные. Попробуйте позже.")

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())