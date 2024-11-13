import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
from telegram import Update
from telegram.ext import Application, CommandHandler
import re

# Настройка Selenium
options = webdriver.ChromeOptions()
options.add_argument('--headless')
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

# Функция для получения расписания
def get_schedule():
    driver.get('https://www.rksi.ru/mobile_schedule')
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, 'group')))
    group_select = driver.find_element(By.NAME, 'group')
    group_select.send_keys('СА-17')
    submit_button = driver.find_element(By.NAME, 'stt')
    submit_button.click()
    time.sleep(3)
    schedule_data = driver.find_element(By.TAG_NAME, 'body').text
    start_index = schedule_data.find('_________________')
    if start_index != -1:
        schedule_data = schedule_data[start_index:]
    schedule_data = schedule_data.replace("_________________", "").replace("На сайт", "")
    return schedule_data

# Функция для форматирования расписания
def format_schedule(data):
    formatted_schedule = ""
    lines = data.split('\n')
    current_date = ""
    first_event_of_day = True

    for line in lines:
        line = line.strip()
        if line == "":
            continue
        if "ауд." in line:
            line += "\n"
        date_match = re.match(r"(\d{1,2} \w+, \w+)", line)
        if date_match:
            if current_date != date_match.group(1):
                current_date = date_match.group(1)
                formatted_schedule += f"\n📅 <b>{current_date}</b>\n\n"
                first_event_of_day = True
        else:
            if first_event_of_day:
                first_event_of_day = False
            formatted_schedule += f"{line}\n"

    return formatted_schedule

# Функция для разбивки длинных сообщений
def split_message(text, max_length=4096):
    messages = []
    while len(text) > max_length:
        split_index = text.rfind('\n', 0, max_length)
        if split_index == -1:
            split_index = max_length
        messages.append(text[:split_index])
        text = text[split_index:].lstrip()
    messages.append(text)
    return messages

# Функция для команды /start в Telegram
async def start(update: Update, context):
    await update.message.reply_text('Привет! Я могу предоставить расписание группы СА-17.')

# Функция для команды /schedule в Telegram
async def schedule(update: Update, context):
    try:
        data = get_schedule()
        formatted_data = format_schedule(data)
        messages = split_message(formatted_data)
        for message in messages:
            await update.message.reply_text(message, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка: {e}")

# Настройка бота
def main():
    # Получение токена из переменной окружения
    token = os.environ.get("TOKEN")
    application = Application.builder().token(token).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("schedule", schedule))

    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
