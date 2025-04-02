import os
import datetime
import io
import re
import openpyxl
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackContext

# Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# ID папки Google Drive
DRIVE_FOLDER_ID = "1kUYiSAafghhYR0ARyXwPW1HZPpHcFIag"

# Путь к JSON с учетными данными для Google API
SERVICE_ACCOUNT_FILE = "path/to/your-service-account.json"

# Авторизация Google Drive API
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=credentials)


async def find_file_id_by_date(target_date: datetime.date) -> str:
    """Ищет файл в Google Drive по дате. Возвращает file_id, если найден."""
    file_name = target_date.strftime("%d.%m.%Y") + ".xlsx"
    query = f"'{DRIVE_FOLDER_ID}' in parents and name = '{file_name}' and mimeType != 'application/vnd.google-apps.folder'"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


async def download_file(file_id: str) -> bytes:
    """Скачивает файл из Google Drive по file_id и возвращает его содержимое."""
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read()


async def find_target_file() -> tuple[bytes, datetime.date] | tuple[None, None]:
    """Ищет ближайший актуальный файл: сегодня → завтра → послезавтра → вчера."""
    today = datetime.date.today()

    # 1. Сегодня
    file_id = await find_file_id_by_date(today)
    if file_id:
        return await download_file(file_id), today

    # 2. Завтра или послезавтра
    for delta in (1, 2):
        target_date = today + datetime.timedelta(days=delta)
        file_id = await find_file_id_by_date(target_date)
        if file_id:
            return await download_file(file_id), target_date

    # 3. Вчера
    target_date = today - datetime.timedelta(days=1)
    file_id = await find_file_id_by_date(target_date)
    if file_id:
        return await download_file(file_id), target_date

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