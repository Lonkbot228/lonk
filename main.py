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
from babel.dates import format_date

# Настройка Selenium
options = webdriver.ChromeOptions()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')
options.add_argument('--disable-software-rasterizer')

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

# Функция для чтения файла iCalendar
def read_ics_file():
    try:
        with open("sa17.ics", "r", encoding="utf-8") as file:
            calendar = Calendar.from_ical(file.read())
        return calendar
    except FileNotFoundError:
        print("Файл sa17.ics не найден. Используется резервная логика.")
        return None

# Функция для преобразования даты в русский формат
def format_date_russian(date):
    return format_date(date, format="d MMMM, EEEE", locale="ru")

# Функция для извлечения данных из строки
def extract_data(text, key):
    match = re.search(fr"{key}:\s*(.+?)\s*\|", text)
    return match.group(1).strip() if match else "Не указано"

# Функция для извлечения названия предмета из summary
def extract_subject(summary):
    match = re.search(r"/(.*?)/", summary)
    return match.group(1).strip() if match else "Не указано"

# Функция для получения данных из iCalendar
def get_schedule_from_ics(calendar, target_date):
    schedule = []
    for component in calendar.walk():
        if component.name == "VEVENT":
            event_start = component.get("DTSTART").dt.date()
            if event_start == target_date:
                summary = component.get("SUMMARY", "")
                description = component.get("DESCRIPTION", "")
                subject = extract_subject(summary)  # Извлекаем предмет
                time = extract_data(description, "Время")
                room = extract_data(description, "Кабинет")
                teacher = extract_data(description, "Преподаватель")

                schedule.append({
                    "subject": subject,
                    "time": time,
                    "room": room,
                    "teacher": teacher,
                })
    return sorted(schedule, key=lambda x: x["time"])  # Сортируем по времени

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

# Функция для обработки расписания
def format_combined_schedule(target_date):
    calendar = read_ics_file()
    ics_schedule = []
    if calendar:
        ics_schedule = get_schedule_from_ics(calendar, target_date)

    # Если расписание за target_date не найдено в iCalendar, используем Selenium
    if not ics_schedule:
        web_schedule = get_schedule_from_web()
        formatted_schedule = format_schedule(web_schedule, [], target_date)
    else:
        web_schedule = ""  # Пустая строка, так как данные из веба не нужны
        formatted_schedule = format_schedule(web_schedule, ics_schedule, target_date)

    return formatted_schedule

# Функция для форматирования расписания
def format_schedule(web_data, ics_schedule, target_date):
    formatted_schedule = f"📅 <b>{format_date_russian(target_date)}</b>\n\n"
    lines = web_data.split('\n')
    events = []

    # Извлечение данных из веб-расписания
    for line in lines:
        line = line.strip()
        if "Кабинет:" in line:
            time = extract_data(line, "Время")
            room = extract_data(line, "Кабинет")
            teacher = extract_data(line, "Преподаватель")
            events.append({"time": time, "room": room, "teacher": teacher})

    # Если расписание из iCalendar пустое, используем только данные из веба
    if not ics_schedule:
        combined_schedule = sorted(events, key=lambda x: x["time"])
    else:
        # Объединение и сортировка
        combined_schedule = sorted(events + ics_schedule, key=lambda x: x["time"])

    for event in combined_schedule:
        subject = event.get("subject", "Предмет не указан")
        formatted_schedule += (
            f"🕒 <b>{event['time']}</b>\n"  # Время пары
            f"📘 {subject}\n"              # Название предмета (не жирным)
            f"✍️ {event['teacher']}\n"     # Преподаватель
            f"🏫 {event['room']}\n\n"      # Кабинет
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
