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

from telegram import Update, ChatAction
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ────────────────────────────────────────────────────────────
#  Настройки для Google Drive API
# ────────────────────────────────────────────────────────────

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
FOLDER_ID = '1kUYiSAafghhYR0ARyXwPW1HZPpHcFIag'  # ← Замените своим ID папки

# ────────────────────────────────────────────────────────────
#  Telegram-токен (API key) из переменной окружения
# ────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ.get("TOKEN")
if not TELEGRAM_TOKEN:
    logging.error("Переменная окружения TOKEN не установлена.")
    exit(1)

# ────────────────────────────────────────────────────────────
#  Устанавливаем логирование
# ────────────────────────────────────────────────────────────

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
#  Функции для работы с Google Drive
# ────────────────────────────────────────────────────────────

def authenticate_drive() -> 'googleapiclient.discovery.Resource':
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w', encoding='utf-8') as token_file:
            token_file.write(creds.to_json())

    return build('drive', 'v3', credentials=creds)


def get_latest_xlsx_file_id(service) -> dict:
    query = (
        f"'{FOLDER_ID}' in parents and trashed = false and "
        "mimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'"
    )
    results = service.files().list(
        q=query,
        pageSize=5,
        fields="files(id, name, modifiedTime)",
        orderBy="modifiedTime desc"
    ).execute()
    files = results.get('files', [])
    if not files:
        raise FileNotFoundError("В папке не найдено ни одного .xlsx-файла.")
    return files[0]


def download_xlsx_to_memory(service, file_id: str) -> io.BytesIO:
    request = service.files().get_media(fileId=file_id)
    bio = io.BytesIO()
    downloader = MediaIoBaseDownload(bio, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    bio.seek(0)
    return bio


def parse_schedule_from_xlsx(xlsx_stream: io.BytesIO) -> list:
    all_sheets: dict = pd.read_excel(
        xlsx_stream,
        sheet_name=None,
        header=None,
        dtype=str
    )

    entries = []
    for sheet_name, df in all_sheets.items():
        df = df.fillna('')
        n_rows, n_cols = df.shape
        for i in range(n_rows):
            for j in range(n_cols):
                if str(df.iat[i, j]).strip() == "СА-17":
                    if j == 1:
                        cabinet = df.iat[i, 0] if n_cols > 0 else ''
                        teacher = df.iat[i, 2] if n_cols > 2 else ''
                        entries.append({'subject': sheet_name, 'teacher': teacher, 'cabinet': cabinet})
                    elif j == 4:
                        cabinet = df.iat[i, 3] if n_cols > 3 else ''
                        teacher = df.iat[i, 5] if n_cols > 5 else ''
                        entries.append({'subject': sheet_name, 'teacher': teacher, 'cabinet': cabinet})
    return entries


# ────────────────────────────────────────────────────────────
#  Утилиты для форматирования даты из имени файла
# ────────────────────────────────────────────────────────────

def format_date_from_filename(filename: str) -> str:
    name, _ = os.path.splitext(filename)
    try:
        date_obj = datetime.strptime(name, "%d.%m.%Y")
    except ValueError:
        return ""
    months = [
        "января", "февраля", "марта", "апреля",
        "мая", "июня", "июля", "августа",
        "сентября", "октября", "ноября", "декабря"
    ]
    weekdays = [
        "понедельник", "вторник", "среда",
        "четверг", "пятница", "суббота", "воскресенье"
    ]
    day = date_obj.day
    month_name = months[date_obj.month - 1]
    weekday_name = weekdays[date_obj.weekday()]
    return f"{day} {month_name}, {weekday_name}"


# ────────────────────────────────────────────────────────────
#  Handlers Telegram-бота
# ────────────────────────────────────────────────────────────

def start_command(update: Update, context: CallbackContext) -> None:
    chat = update.effective_chat
    thread_id = getattr(update.effective_message, 'message_thread_id', None)
    text = (
        "Дарова, пиши /schedule или\n"
        "/расписание, а я тебе кину актуальное расписание, понял?"
    )
    if thread_id:
        context.bot.send_message(chat_id=chat.id, text=text, parse_mode='Markdown', message_thread_id=thread_id)
    else:
        update.message.reply_text(text)


def _typing_job(context: CallbackContext) -> None:
    """
    Это функция, которая будет вызываться JobQueue каждые несколько секунд,
    чтобы послать ChatAction.TYPING в тот же чат (и тред, если есть).
    """
    job_data = context.job.context  # в job.context мы храним кортеж (chat_id, thread_id)
    chat_id, thread_id = job_data
    if thread_id:
        context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING, message_thread_id=thread_id)
    else:
        context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


def schedule_command(update: Update, context: CallbackContext) -> None:
    """
    /schedule — показывает «typing…», публикует «⏳ Секундочку…», запускает непрерывное typing… через JobQueue,
    затем скачивает и парсит расписание, после чего обновляет «⏳ Секундочку…» в конечный ответ
    и останавливает JobQueue.
    """
    chat = update.effective_chat
    thread_id = getattr(update.effective_message, 'message_thread_id', None)
    chat_id = chat.id

    # 1) Запускаем первый ChatAction.TYPING (для немедленной реакции)
    if thread_id:
        context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING, message_thread_id=thread_id)
    else:
        context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # 2) Отправляем временное сообщение «⏳ Секундочку…»
    if thread_id:
        msg = context.bot.send_message(
            chat_id=chat_id,
            text="⏳ Секундочку, получаю расписание…",
            message_thread_id=thread_id
        )
    else:
        msg = update.message.reply_text("⏳ Секундочку, получаю расписание…")

    # 3) Запускаем повторяющийся Job, чтобы каждые 4 секунды слать typing…
    #    Сохраним объект Job, чтобы потом отменить
    job = context.job_queue.run_repeating(
        _typing_job,
        interval=4,         # каждые 4 секунды
        first=4,            # первый запуск через 4 секунды
        context=(chat_id, thread_id)
    )

    try:
        # 4) Авторизация и поиск файла
        drive_service = authenticate_drive()
        latest_file = get_latest_xlsx_file_id(drive_service)
        file_name = latest_file['name']

        # 5) Скачивание
        xlsx_stream = download_xlsx_to_memory(drive_service, latest_file['id'])

        # 6) Парсинг
        entries = parse_schedule_from_xlsx(xlsx_stream)

        # 7) Форматирование итогового сообщения
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

        # 8) Остановим Job с typing…, так как мы почти готовы редактировать сообщение
        job.schedule_removal()

        # 9) Проверяем длину и либо редактируем msg, либо разбиваем на части
        MAX_LEN = 4000  # с запасом (Telegram позволяет до ~4096 символов)
        if len(full_response) <= MAX_LEN:
            # просто редактируем единственное сообщение
            if thread_id:
                msg.edit_text(
                    text=full_response,
                    parse_mode='Markdown',
                    message_thread_id=thread_id
                )
            else:
                msg.edit_text(
                    text=full_response,
                    parse_mode='Markdown'
                )
        else:
            # разбиваем на несколько сообщений, но первое — редактируем
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

            # редактируем первое сообщение
            first_chunk = chunks[0]
            if thread_id:
                msg.edit_text(
                    text=first_chunk,
                    parse_mode='Markdown',
                    message_thread_id=thread_id
                )
            else:
                msg.edit_text(
                    text=first_chunk,
                    parse_mode='Markdown'
                )

            # отправляем оставшиеся части как новые сообщения
            for part in chunks[1:]:
                if thread_id:
                    context.bot.send_message(
                        chat_id=chat_id,
                        text=part,
                        parse_mode='Markdown',
                        message_thread_id=thread_id
                    )
                else:
                    context.bot.send_message(
                        chat_id=chat_id,
                        text=part,
                        parse_mode='Markdown'
                    )

    except Exception as e:
        # Если произошла ошибка, отменяем Job, и редактируем «⏳ Секундочку…» на текст об ошибке
        job.schedule_removal()
        error_text = f"❌ Произошла ошибка при получении расписания:\n{e}"
        logger.exception("Ошибка в schedule_command")
        if thread_id:
            msg.edit_text(text=error_text, message_thread_id=thread_id)
        else:
            msg.edit_text(text=error_text)


def russian_schedule_handler(update: Update, context: CallbackContext) -> None:
    """
    /расписание — перенаправляет в schedule_command.
    """
    schedule_command(update, context)


def help_command(update: Update, context: CallbackContext) -> None:
    """
    /help — отправляет справку в тему (если есть).
    """
    chat = update.effective_chat
    thread_id = getattr(update.effective_message, 'message_thread_id', None)
    text = (
        "Бот для получения расписания.\n\n"
        "Доступные команды:\n"
        "/start — показать приветствие\n"
        "/schedule — получить расписание (или /расписание)\n"
        "/help — показать это сообщение"
    )
    if thread_id:
        context.bot.send_message(chat_id=chat.id, text=text, parse_mode='Markdown', message_thread_id=thread_id)
    else:
        update.message.reply_text(text)


def unknown_command(update: Update, context: CallbackContext) -> None:
    """
    Обработчик для неизвестных команд — отвечает в тему (если есть).
    """
    chat = update.effective_chat
    thread_id = getattr(update.effective_message, 'message_thread_id', None)
    text = "окак. Используй /help для списка доступных комманд."
    if thread_id:
        context.bot.send_message(chat_id=chat.id, text=text, message_thread_id=thread_id)
    else:
        update.message.reply_text(text)


# ────────────────────────────────────────────────────────────
#  Основная функция
# ────────────────────────────────────────────────────────────

def main():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Регистрируем команды и обработчики
    dp.add_handler(CommandHandler("start", start_command))
    dp.add_handler(CommandHandler("schedule", schedule_command))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(MessageHandler(Filters.regex(r'^/расписание$'), russian_schedule_handler))
    dp.add_handler(MessageHandler(Filters.command, unknown_command))

    # Здесь мы не делаем ничего с job_queue: он уже встроен в updater
    updater.start_polling()
    logger.info("Бот запущен и ожидает команд.")
    updater.idle()


if __name__ == '__main__':
    main()