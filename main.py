import os
import io
import logging
import pandas as pd
from datetime import datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ────────────────────────────────────────────────────────────
#  Настройки для Google Drive API
# ────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_ID = "1kUYiSAafghhYR0ARyXwPW1HZPpHcFIag"  # ← Замените своим ID папки

# ────────────────────────────────────────────────────────────
#  Логирование
# ────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
#  Функции для работы с Google Drive
# ────────────────────────────────────────────────────────────


def authenticate_drive() -> "googleapiclient.discovery.Resource":
    """
    Авторизуемся в Google Drive. Если token.json уже есть — используем его.
    Иначе запускаем поток run_console(), чтобы получить код авторизации вручную
    и сохранить token.json для будущих запусков.
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            # В среде без GUI (Docker) используем run_console()
            creds = flow.run_console()
        with open("token.json", "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def get_latest_xlsx_file_id(service) -> dict:
    """
    Ищем самый свежий .xlsx в заданном FOLDER_ID.
    """
    query = (
        f"'{FOLDER_ID}' in parents and trashed = false and "
        "mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'"
    )
    results = (
        service.files()
        .list(
            q=query,
            pageSize=5,
            fields="files(id, name, modifiedTime)",
            orderBy="modifiedTime desc",
        )
        .execute()
    )
    files = results.get("files", [])
    if not files:
        raise FileNotFoundError("В папке не найдено ни одного .xlsx-файла.")
    return files[0]


def download_xlsx_to_memory(service, file_id: str) -> io.BytesIO:
    """
    Скачиваем файл по file_id в BytesIO, возвращаем поток.
    """
    request = service.files().get_media(fileId=file_id)
    bio = io.BytesIO()
    downloader = MediaIoBaseDownload(bio, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    bio.seek(0)
    return bio


def parse_schedule_from_xlsx(xlsx_stream: io.BytesIO) -> list:
    """
    Читаем все листы Excel, ищем ячейки со значением "СА-17" и собираем записи.
    Возвращает список dict'ов вида {'subject': ..., 'teacher': ..., 'cabinet': ...}.
    """
    all_sheets: dict = pd.read_excel(
        xlsx_stream, sheet_name=None, header=None, dtype=str
    )
    entries = []
    for sheet_name, df in all_sheets.items():
        df = df.fillna("")
        n_rows, n_cols = df.shape
        for i in range(n_rows):
            for j in range(n_cols):
                if str(df.iat[i, j]).strip() == "СА-17":
                    if j == 1:
                        cabinet = df.iat[i, 0] if n_cols > 0 else ""
                        teacher = df.iat[i, 2] if n_cols > 2 else ""
                        entries.append(
                            {"subject": sheet_name, "teacher": teacher, "cabinet": cabinet}
                        )
                    elif j == 4:
                        cabinet = df.iat[i, 3] if n_cols > 3 else ""
                        teacher = df.iat[i, 5] if n_cols > 5 else ""
                        entries.append(
                            {"subject": sheet_name, "teacher": teacher, "cabinet": cabinet}
                        )
    return entries


# ────────────────────────────────────────────────────────────
#  Утилиты для форматирования даты из имени файла
# ────────────────────────────────────────────────────────────


def format_date_from_filename(filename: str) -> str:
    """
    Из имени файла формата "DD.MM.YYYY.xlsx" возвращает строку "D <месяц по‑русски>, <день недели>".
    """
    name, _ = os.path.splitext(filename)
    try:
        date_obj = datetime.strptime(name, "%d.%m.%Y")
    except ValueError:
        return ""
    months = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    weekdays = [
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота",
        "воскресенье",
    ]
    day = date_obj.day
    month_name = months[date_obj.month - 1]
    weekday_name = weekdays[date_obj.weekday()]
    return f"{day} {month_name}, {weekday_name}"


# ────────────────────────────────────────────────────────────
#  Handlers Telegram‑бота (PTB v20+ async)
# ────────────────────────────────────────────────────────────


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start — привествие. Отправляем ответ в ту же тему, если она есть.
    """
    chat = update.effective_chat
    thread_id = update.effective_message.message_thread_id
    text = "Дарова, пиши /schedule, а я тебе кину актуальное расписание, понял?"
    if thread_id:
        await context.bot.send_message(
            chat_id=chat.id, text=text, parse_mode="Markdown", message_thread_id=thread_id
        )
    else:
        await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /help — справка. Отправляем ответ в ту же тему, если она есть.
    """
    chat = update.effective_chat
    thread_id = update.effective_message.message_thread_id
    text = (
        "Бот для получения расписания.\n\n"
        "Доступные команды:\n"
        "/start — показать приветствие\n"
        "/schedule — получить расписание\n"
        "/help — показать это сообщение"
    )
    if thread_id:
        await context.bot.send_message(
            chat_id=chat.id, text=text, parse_mode="Markdown", message_thread_id=thread_id
        )
    else:
        await update.message.reply_text(text)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Ловим все неизвестные команды. Отправляем ответ в ту же тему, если она есть.
    """
    chat = update.effective_chat
    thread_id = update.effective_message.message_thread_id
    text = "окак. Используй /help для списка доступных комманд."
    if thread_id:
        await context.bot.send_message(chat_id=chat.id, text=text, message_thread_id=thread_id)
    else:
        await update.message.reply_text(text)


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /schedule — шлём один ChatAction.TYPING, скачиваем и парсим расписание, затем отправляем ответ.
    """
    chat = update.effective_chat
    thread_id = update.effective_message.message_thread_id
    chat_id = chat.id

    # 1) Шлём ChatAction.TYPING один раз
    if thread_id:
        await context.bot.send_chat_action(
            chat_id=chat_id, action=ChatAction.TYPING, message_thread_id=thread_id
        )
    else:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # 2) Авторизация и поиск файла в Google Drive
        drive_service = authenticate_drive()
        latest_file = get_latest_xlsx_file_id(drive_service)
        file_name = latest_file["name"]

        # 3) Скачиваем xlsx в память
        xlsx_stream = download_xlsx_to_memory(drive_service, latest_file["id"])

        # 4) Парсим расписание
        entries = parse_schedule_from_xlsx(xlsx_stream)

        # 5) Формируем текст ответа
        date_str = format_date_from_filename(file_name)
        header = f"*📅 {date_str}*\n\n" if date_str else "*📅*\n\n"

        if not entries:
            full_response = header + "❗ Расписание пустое."
        else:
            blocks = []
            for e in entries:
                blocks.append(
                    f"*{e['subject']}*\n"
                    f"✍️ {e['teacher']}\n"
                    f"🏫 {e['cabinet']}"
                )
            full_response = header + "\n\n".join(blocks)

        # 6) Отправляем окончательный ответ (или разбиваем на части, если слишком длинный)
        MAX_LEN = 4000  # Telegram позволяет до ~4096 символов
        if len(full_response) <= MAX_LEN:
            if thread_id:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=full_response,
                    parse_mode="Markdown",
                    message_thread_id=thread_id,
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, text=full_response, parse_mode="Markdown"
                )
        else:
            # Разбиваем на несколько сообщений
            chunks = []
            current = ""
            for line in full_response.split("\n"):
                if len(current) + len(line) + 1 > MAX_LEN:
                    chunks.append(current)
                    current = line + "\n"
                else:
                    current += line + "\n"
            if current:
                chunks.append(current)

            # Отправляем все части
            for part in chunks:
                if thread_id:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=part,
                        parse_mode="Markdown",
                        message_thread_id=thread_id,
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id, text=part, parse_mode="Markdown"
                    )

    except Exception as e:
        error_text = f"❌ Произошла ошибка при получении расписания:\n{e}"
        logger.exception("Ошибка в schedule_command")
        if thread_id:
            await context.bot.send_message(chat_id=chat_id, text=error_text, message_thread_id=thread_id)
        else:
            await context.bot.send_message(chat_id=chat_id, text=error_text)


# ────────────────────────────────────────────────────────────
#  Основная функция — создаём и запускаем Application
# ────────────────────────────────────────────────────────────

def main() -> None:
    # Получаем токен из переменной окружения
    token = os.environ.get("TOKEN")
    if not token:
        logger.error("Переменная окружения TOKEN не установлена")
        return

    # Строим приложение с указанным токеном
    app = ApplicationBuilder().token(token).build()

    # Регистрируем хендлеры
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("schedule", schedule_command))
    # Ловим все другие неизвестные команды
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # Запускаем бота (поллинг)
    logger.info("Бот запущен и ожидает команд.")
    app.run_polling()


if __name__ == "__main__":
    main()