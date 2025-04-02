import os
import datetime
import io
import re
import requests
import openpyxl
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackContext

# ID публичной папки Google Drive
DRIVE_FOLDER_ID = "1kUYiSAafghhYR0ARyXwPW1HZPpHcFIag"


def get_file_id_from_folder(target_date: datetime.date) -> str | None:
    """Ищет файл с нужной датой в названии в публичной папке Google Drive."""
    session = requests.Session()
    
    # Google API публичного доступа к папке
    url = f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}?usp=sharing"
    response = session.get(url)
    
    # Проверяем, что ответ корректен
    if response.status_code != 200:
        return None
    
    # Формат имени файла (например, "02.04.2025.xlsx")
    file_name = target_date.strftime("%d.%m.%Y") + ".xlsx"
    
    # Ищем file_id в содержимом
    match = re.search(rf'"([a-zA-Z0-9_-]+)"\s*,\s*\[\["{file_name}"', response.text)
    
    return match.group(1) if match else None


def download_public_file(file_id: str) -> bytes:
    """Скачивает публичный файл из Google Drive."""
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = requests.get(url, allow_redirects=True)
    response.raise_for_status()
    return response.content


async def find_target_file() -> tuple[bytes, datetime.date] | tuple[None, None]:
    """Ищет ближайший актуальный файл: сегодня → завтра → послезавтра → вчера."""
    today = datetime.date.today()

    # 1. Сегодня
    file_id = get_file_id_from_folder(today)
    if file_id:
        return download_public_file(file_id), today

    # 2. Завтра или послезавтра
    for delta in (1, 2):
        target_date = today + datetime.timedelta(days=delta)
        file_id = get_file_id_from_folder(target_date)
        if file_id:
            return download_public_file(file_id), target_date

    # 3. Вчера
    target_date = today - datetime.timedelta(days=1)
    file_id = get_file_id_from_folder(target_date)
    if file_id:
        return download_public_file(file_id), target_date

    return None, None


async def parse_schedule(file_bytes: bytes) -> str:
    """Извлекает расписание из Excel: ищет 'СА-17' и берет номер кабинета + преподавателя."""
    schedule_lines = []
    wb = openpyxl.load_workbook(filename=io.BytesIO(file_bytes), data_only=True)

    # Сортировка листов по порядку пар
    sheet_names = [s for s in wb.sheetnames if re.match(r"Пара\s*\d+", s)]
    sheet_names.sort(key=lambda s: int(re.search(r"\d+", s).group()))

    for sheet_name in sheet_names:
        ws = wb[sheet_name]
        room, teacher = None, None

        for row in ws.iter_rows(values_only=True):
            if row and any(isinstance(cell, str) and "СА-17" in cell for cell in row if cell):
                room = row[0] if row[0] else "N/A"  # Номер кабинета
                teacher = row[2] if len(row) >= 3 and row[2] else "N/A"  # Имя учителя
                break

        if room or teacher:
            schedule_lines.append(f"📎{sheet_name}")
            schedule_lines.append(f"🔑{room}")
            schedule_lines.append(f"✍️{teacher}\n")

    return "\n".join(schedule_lines) if schedule_lines else "⛔ Расписание не найдено."


async def schedule_command(update: Update, context: CallbackContext):
    """Обработчик команды /schedule."""
    file_bytes, file_date = await find_target_file()
    if not file_bytes:
        await update.message.reply_text("⛔ Расписание не найдено за указанные дни.")
        return

    schedule_text = await parse_schedule(file_bytes)

    # Форматирование даты (например: "🗓️2 апреля")
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля",
        5: "мая", 6: "июня", 7: "июля", 8: "августа",
        9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }
    header_date = f"🗓️{file_date.day} {months[file_date.month]}"
    message = f"*{header_date}*\n\n{schedule_text}"

    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


def main():
    """Запуск бота."""
    token = os.environ.get("TOKEN")
    application = Application.builder().token(token).build()

    # Добавляем команду /schedule
    application.add_handler(CommandHandler("schedule", schedule_command))

    # Запускаем бота
    application.run_polling()


if __name__ == "__main__":
    main()