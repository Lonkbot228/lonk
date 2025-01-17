import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from icalendar import Calendar
import datetime
import re
from telegram import Update
from telegram.ext import Application, CommandHandler

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

# Функция для извлечения данных из строки
def extract_data(text, key):
    pattern = rf"{key}:\s*(.+?)\|"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else "Не указано"

# Функция для получения данных из iCalendar
def get_schedule_from_ics(calendar, target_date):
    schedule = []
    for component in calendar.walk():
        if component.name == "VEVENT":
            event_start = component.get("DTSTART").dt.date()
            if event_start == target_date:
                description = component.get("DESCRIPTION", "")
                time = extract_data(description, "Время")
                room = extract_data(description, "Кабинет")
                teacher = extract_data(description, "Преподаватель")

                # Преобразуем время в объект для сортировки
                try:
                    parsed_time = datetime.datetime.strptime(time, "%H:%M").time()
                except ValueError:
                    parsed_time = None

                schedule.append({
                    "time": time,
                    "room": room,
                    "teacher": teacher,
                    "parsed_time": parsed_time,
                })

    # Сортировка по времени (раньше начинается - выше в списке)
    schedule.sort(key=lambda x: x["parsed_time"] if x["parsed_time"] else datetime.time(23, 59))
    return schedule

# Функция для получения расписания через Selenium
def get_schedule_from_web():
    driver.get('https://www.rksi.ru/mobile_schedule')
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, 'group')))
    group_select = driver.find_element(By.NAME, 'group')
    group_select.send_keys('СА-17')
    submit_button = driver.find_element(By.NAME, 'stt')
    submit_button.click()
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
    schedule_data = driver.find_element(By.TAG_NAME, 'body').text
    start_index = schedule_data.find('_________________')
    if start_index != -1:
        schedule_data = schedule_data[start_index:]
    schedule_data = schedule_data.replace("_________________", "").replace("На сайт", "")
    return schedule_data

# Функция для объединения данных расписания
def format_combined_schedule(target_date):
    calendar = read_ics_file()
    ics_schedule = []
    if calendar:
        ics_schedule = get_schedule_from_ics(calendar, target_date)

    web_schedule = get_schedule_from_web()
    formatted_schedule = format_schedule(web_schedule, ics_schedule, target_date)
    return formatted_schedule

# Функция для форматирования расписания
def format_schedule(web_data, ics_schedule, target_date):
    formatted_schedule = f"📅 <b>{target_date.strftime('%d %B, %A')}</b>\n\n"
    lines = web_data.split('\n')
    events = []

    # Старый способ извлечения предметов из веб-расписания
    for i, line in enumerate(lines):
        line = line.strip()
        if "ауд." in line:
            if i >= 3:  # Проверяем, есть ли три строки выше текущей
                time_line = lines[i - 2].strip()  # Время
                subject_line = lines[i - 1].strip()  # Название пары
                events.append({"time": time_line, "subject": subject_line})

    # Объединение данных из ics и веб-расписания
    for event in events:
        # Найдём соответствующее событие из iCalendar по времени
        ics_event = next((e for e in ics_schedule if e["time"] == event["time"]), None)
        formatted_schedule += (
            f"🕒 <b>{event['time']}</b>\n"
            f"📚 {event.get('subject', 'Не указано')}\n"
            f"🏫 {ics_event['room'] if ics_event else 'Не указано'}\n"
            f"✍️ {ics_event['teacher'] if ics_event else 'Не указано'}\n\n"
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
