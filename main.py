import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from icalendar import Calendar
import time
from telegram import Update
from telegram.ext import Application, CommandHandler
import datetime
import re

# Настройка Selenium
options = webdriver.ChromeOptions()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--disable-software-rasterizer')

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

# Функция для чтения файла iCalendar (sa17.ics)
def read_ics_file():
    try:
        with open("sa17.ics", "r", encoding="utf-8") as file:
            calendar = Calendar.from_ical(file.read())
        return calendar
    except FileNotFoundError:
        print("Файл sa17.ics не найден. Используется резервная логика.")
        return None

# Функция для получения расписания из файла iCalendar
def get_schedule_from_ics(calendar, target_date):
    schedule = []
    for component in calendar.walk():
        if component.name == "VEVENT":
            event_start = component.get("DTSTART").dt
            event_end = component.get("DTEND").dt
            summary = component.get("SUMMARY")
            location = component.get("LOCATION", "Не указано")
            description = component.get("DESCRIPTION", "")

            # Проверяем, относится ли событие к целевому дню
            if isinstance(event_start, datetime.datetime):
                event_start = event_start.date()
            if event_start == target_date:
                schedule.append({
                    "start_time": component.get("DTSTART").dt.strftime("%H:%M"),
                    "end_time": component.get("DTEND").dt.strftime("%H:%M"),
                    "summary": summary,
                    "location": location,
                    "description": description,
                })
    return schedule

# Функция для получения расписания через Selenium
def get_schedule_from_web():
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
def format_schedule_from_ics(schedule, date):
    formatted_schedule = f"📅 <b>{date.strftime('%d %B, %A')}</b>\n\n"
    if not schedule:
        formatted_schedule += "Нет данных в календаре для этой даты.\n"
    else:
        for event in schedule:
            formatted_schedule += (
                f"🕒 <b>{event['start_time']} - {event['end_time']}</b>\n"
                f"📚 {event['summary']}\n"
                f"🏫 {event['location']}\n"
                f"✍️ {event['description']}\n\n"
            )
    return formatted_schedule

# Функция для обработки расписания
def format_combined_schedule(target_date):
    calendar = read_ics_file()
    if calendar:
        ics_schedule = get_schedule_from_ics(calendar, target_date)
        if ics_schedule:
            return format_schedule_from_ics(ics_schedule, target_date)
    # Если в календаре нет данных, используется веб-скрапинг
    web_schedule = get_schedule_from_web()
    return format_schedule(web_schedule)

# Переработанная функция для веб-расписания
def format_schedule(data):
    formatted_schedule = ""
    lines = data.split('\n')  # Разбиваем расписание на строки
    current_date = ""         # Хранит текущую дату

    for i, line in enumerate(lines):
        line = line.strip()
        if line == "":
            continue  # Пропускаем пустые строки

        # Проверка на наличие слова "ауд."
        if "ауд." in line:
            if i >= 3:  # Проверяем наличие трёх строк выше текущей
                date_line = lines[i - 3].strip()  # Строка с датой
                time_line = lines[i - 2].strip()  # Строка с временем
                subject_line = lines[i - 1].strip()  # Строка с названием пары
                audience_and_teacher = line.strip()  # Аудитория и преподаватель

                # Если дата изменилась, добавляем её в расписание
                if current_date != date_line:
                    current_date = date_line
                    formatted_schedule += f"\n📅 <b>{current_date}</b>\n\n"

                # Форматируем событие
                formatted_schedule += (
                    f"🕒 <b>{time_line}</b>\n"
                    f"📚 {subject_line}\n"
                    f"🏫 {audience_and_teacher}\n\n"
                )

    return formatted_schedule

# Функция для команды /start в Telegram
async def start(update: Update, context):
    await update.message.reply_text('Привет! Я могу предоставить расписание группы СА-17.')

# Функция для команды /schedule в Telegram
async def schedule(update: Update, context):
    try:
        target_date = datetime.date.today()  # Используем текущую дату
        formatted_data = format_combined_schedule(target_date)
        await update.message.reply_text(formatted_data, parse_mode="HTML")
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