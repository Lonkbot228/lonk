import os
from icalendar import Calendar
import time
from telegram import Update
from telegram.ext import Application, CommandHandler
import datetime
import re
from babel.dates import format_date

# Функция для чтения файла iCalendar
def read_ics_file():
    try:
        with open("sa17.ics", "r", encoding="utf-8") as file:
            calendar = Calendar.from_ical(file.read())
        return calendar
    except FileNotFoundError:
        print("Файл sa17.ics не найден.")
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

# Функция для обработки расписания
def format_combined_schedule(target_date):
    calendar = read_ics_file()
    ics_schedule = []
    if calendar:
        ics_schedule = get_schedule_from_ics(calendar, target_date)

    # Формируем расписание
    formatted_schedule = format_schedule(ics_schedule, target_date)
    return formatted_schedule

# Функция для форматирования расписания
def format_schedule(ics_schedule, target_date):
    formatted_schedule = f"📅 <b>{format_date_russian(target_date)}</b>\n\n"
    
    if not ics_schedule:
        formatted_schedule += "Нет данных на этот день."
    else:
        for event in ics_schedule:
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

# Функция для команды /nikas в Telegram
async def nikas(update: Update, context):
    await update.message.reply_text('<b>пошел нахуй</b>', parse_mode="HTML")

# Настройка бота
def main():
    # Получение токена из переменной окружения
    token = os.environ.get("TOKEN")
    application = Application.builder().token(token).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("schedule", schedule))
    application.add_handler(CommandHandler("nikas", nikas))  # Добавлена команда /nikas

    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
