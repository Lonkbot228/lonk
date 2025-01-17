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
from babel.dates import format_date  # Для преобразования даты в русский формат

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

# Функция для преобразования даты в русский формат
def format_date_russian(date):
    return format_date(date, format="d MMMM, EEEE", locale="ru")

# Функция для получения данных из iCalendar
def get_schedule_from_ics(calendar, target_date):
    schedule = []
    for component in calendar.walk():
        if component.name == "VEVENT":
            event_start = component.get("DTSTART").dt.date()
            if event_start == target_date:
                description = component.get("DESCRIPTION", "")
                time_match = re.search(r"Время:\s*(\d{2}:\d{2})\s*—\s*(\d{2}:\d{2})", description)
                room_match = re.search(r"Кабинет:\s*(.*?)\s*\|", description)
                teacher_match = re.search(r"Преподаватель:\s*(.*?)\s*\|", description)

                if time_match:
                    start_time = time_match.group(1)
                    end_time = time_match.group(2)
                    schedule.append({
                        "time": f"{start_time} — {end_time}",
                        "room": room_match.group(1).strip() if room_match else "Не указано",
                        "teacher": teacher_match.group(1).strip() if teacher_match else "Не указано",
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

# Функция для обработки расписания
def format_combined_schedule(target_date):
    calendar = read_ics_file()
    ics_schedule = []
    if calendar:
        ics_schedule = get_schedule_from_ics(calendar, target_date)

    web_schedule = get_schedule_from_web()
    formatted_schedule = format_schedule(web_schedule, ics_schedule, target_date)
    return formatted_schedule

# Функция для сортировки по времени
def sort_schedule_by_time(events):
    return sorted(events, key=lambda x: datetime.datetime.strptime(x['time'].split(' — ')[0], '%H:%M'))

# Функция для форматирования расписания
def format_schedule(web_data, ics_schedule, target_date):
    formatted_schedule = f"📅 <b>{format_date_russian(target_date)}</b>\n\n"
    lines = web_data.split('\n')
    current_date = ""
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
    for i, event in enumerate(events):
        if i < len(ics_schedule):
            event.update(ics_schedule[i])  # Обновляем данные из ics
        formatted_schedule += (
            f"🕒 <b>{event['time']}</b>\n"
            f"📚 {event.get('subject', 'Не указано')}\n"
            f"🏫 {event.get('room', 'Не указано')}\n"
            f"✍️ {event.get('teacher', 'Не указано')}\n\n"
        )

    # Сортировка расписания по времени
    events_sorted = sort_schedule_by_time(events)
    
    # Переформатирование после сортировки
    formatted_schedule = ""
    for event in events_sorted:
        formatted_schedule += (
            f"🕒 <b>{event['time']}</b>\n"
            f"📚 {event.get('subject', 'Не указано')}\n"
            f"🏫 {event.get('room', 'Не указано')}\n"
            f"✍️ {event.get('teacher', 'Не указано')}\n\n"
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
