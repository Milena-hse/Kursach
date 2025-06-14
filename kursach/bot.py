"""
Telegram-бот для управления дедлайнами с интерактивным календарем и FAQ.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
import telebot
from telebot import types
from telebot_calendar import Calendar, CallbackData
import threading
import time
import pytz  # Для работы с часовыми поясами

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = telebot.TeleBot("7714541769:AAEPy1a2v40pVqhRsRHZzJMVlA8DpXBpmz4")

# Устанавливаем часовой пояс для Перми (Asia/Yekaterinburg, UTC+5)
TIMEZONE = pytz.timezone("Asia/Yekaterinburg")

# Инициализация календаря
calendar = Calendar()
calendar_callback = CallbackData("calendar", "action", "year", "month", "day")


# Инициализация базы данных
def init_db():
    """Создаёт таблицы для хранения дедлайнов и добавляет отсутствующие столбцы."""
    conn = sqlite3.connect("deadlines.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            description TEXT,
            reminder TEXT,
            photo_file_id TEXT,
            completed INTEGER DEFAULT 0
        )
        """
    )

    cursor.execute("PRAGMA table_info(deadlines)")
    columns = [column[1] for column in cursor.fetchall()]
    if "photo_file_id" not in columns:
        cursor.execute("ALTER TABLE deadlines ADD COLUMN photo_file_id TEXT")

    conn.commit()
    conn.close()


# Главное меню
def main_menu():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("Добавить дедлайн", "Удалить дедлайн")
    keyboard.row("Посмотреть дедлайны")
    return keyboard


# Кнопка техподдержки
def support_button():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("❓ Техподдержка", callback_data="support")
    )
    return keyboard


# FAQ клавиатура
def faq_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("Как добавить дедлайн?", callback_data="faq_add_deadline"),
        types.InlineKeyboardButton("Как удалить дедлайн?", callback_data="faq_delete_deadline")
    )
    keyboard.row(
        types.InlineKeyboardButton("Как работает напоминание?", callback_data="faq_reminder")
    )
    keyboard.row(
        types.InlineKeyboardButton("📩 Написать разработчикам", callback_data="contact_support")
    )
    return keyboard


# Команда /start
@bot.message_handler(commands=["start"])
def start(message):
    user = message.from_user
    bot.reply_to(
        message,
        f"Привет, {user.first_name}! Я бот для управления дедлайнами.\nВыбери, что хочешь сделать:",
        reply_markup=main_menu(),
    )
    bot.send_message(
        message.chat.id,
        "Если нужна помощь, обращайся в техподдержку:",
        reply_markup=support_button(),
    )


# Просмотр дедлайнов (с сортировкой по дате и выбором номера)
@bot.message_handler(func=lambda message: message.text == "Посмотреть дедлайны")
def view_deadlines(message):
    user_id = message.from_user.id
    conn = sqlite3.connect("deadlines.db")
    cursor = conn.cursor()
    # Сортируем дедлайны по дате (ближайшие первыми)
    cursor.execute(
        "SELECT id, title, date, description, reminder, photo_file_id, completed FROM deadlines WHERE user_id = ? ORDER BY date ASC",
        (user_id,),
    )
    deadlines = cursor.fetchall()
    conn.close()

    if not deadlines:
        bot.reply_to(message, "У тебя нет дедлайнов.", reply_markup=main_menu())
        return

    response = "Твои дедлайны:\n"
    for idx, deadline in enumerate(deadlines, 1):
        deadline_date = datetime.strptime(deadline[2], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE)
        status = "✅ Выполнено" if deadline[6] == 1 else "⏳ Не выполнено"
        response += (
            f"{idx}. {deadline[1]} — {deadline_date.strftime('%d.%m.%Y %H:%M')}, "
            f"{deadline[3] or 'без описания'}, Напоминание: {deadline[4] or 'нет'}, {status}\n"
        )

        if deadline[5]:
            bot.send_photo(message.chat.id, deadline[5], caption=response)
            response = ""  # Сбрасываем текст, чтобы не дублировать
        else:
            bot.send_message(message.chat.id, response)
            response = ""

    # Создаём клавиатуру с номерами дедлайнов
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for idx in range(1, len(deadlines) + 1):
        keyboard.add(str(idx))
    keyboard.add("Назад")

    # Очищаем состояние
    bot.delete_state(user_id, message.chat.id)
    logger.info(f"Пользователь {user_id}: дедлайны получены, всего {len(deadlines)} дедлайнов")

    msg = bot.send_message(
        message.chat.id,
        "Выбери номер дедлайна для изменения статуса:",
        reply_markup=keyboard
    )
    # Передаём данные о дедлайнах напрямую в select_deadline
    bot.register_next_step_handler(msg, lambda m: select_deadline(m, deadlines))
    logger.info(f"Пользователю {user_id} отправлен запрос на выбор номера дедлайна")


# Обработка выбора дедлайна
def select_deadline(message, deadlines):
    choice = message.text
    user_id = message.from_user.id
    chat_id = message.chat.id

    logger.info(f"Пользователь {user_id} выбрал: {choice}")

    if choice.lower() == "назад":
        bot.reply_to(message, "Вернулся в главное меню.", reply_markup=main_menu())
        bot.delete_state(user_id, chat_id)
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(deadlines):
            deadline = deadlines[idx]

            deadline_date = datetime.strptime(deadline[2], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE)
            bot.reply_to(
                message,
                f"Выбран дедлайн: {deadline[1]} — {deadline_date.strftime('%d.%m.%Y %H:%M')}",
                reply_markup=types.ReplyKeyboardRemove()
            )

            # Создаём клавиатуру для выбора действия (внизу экрана)
            action_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
            action_keyboard.row("Отметить как выполненное", "Отметить как невыполненное")
            action_keyboard.row("Назад")

            msg = bot.send_message(
                chat_id,
                "Выберите, что хотите сделать с выбранным дедлайном:",
                reply_markup=action_keyboard
            )
            # Передаём данные напрямую в handle_deadline_action
            bot.register_next_step_handler(
                msg,
                lambda m: handle_deadline_action(m, deadlines, idx)
            )
            logger.info(f"Пользователю {user_id} отправлено сообщение с кнопками действий (внизу)")
        else:
            keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
            for idx in range(1, len(deadlines) + 1):
                keyboard.add(str(idx))
            keyboard.add("Назад")
            msg = bot.reply_to(message, "Неверный номер. Попробуй снова:", reply_markup=keyboard)
            bot.register_next_step_handler(msg, lambda m: select_deadline(m, deadlines))
            logger.info(f"Пользователь {user_id} ввёл неверный номер, запрошен повторный выбор")
    except ValueError:
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for idx in range(1, len(deadlines) + 1):
            keyboard.add(str(idx))
        keyboard.add("Назад")
        msg = bot.reply_to(message, "Пожалуйста, выбери номер дедлайна или 'Назад':", reply_markup=keyboard)
        bot.register_next_step_handler(msg, lambda m: select_deadline(m, deadlines))
        logger.info(f"Пользователь {user_id} ввёл некорректное значение, запрошен повторный выбор")


# Обработка действий с дедлайном (отметить выполненным/невыполненным)
def handle_deadline_action(message, deadlines, selected_deadline_idx):
    action = message.text.strip()  # Убираем возможные пробелы
    user_id = message.from_user.id
    chat_id = message.chat.id

    logger.info(f"Пользователь {user_id} выбрал действие: '{action}'")

    if action.lower() == "назад":
        bot.reply_to(message, "Вернулся в главное меню.", reply_markup=main_menu())
        return

    deadline = deadlines[selected_deadline_idx]
    logger.info(f"Выбранный дедлайн: {deadline[1]} (ID: {deadline[0]})")

    if action == "Отметить как выполненное":
        new_status = 1
        status_text = "выполненным ✅"
    elif action == "Отметить как невыполненное":
        new_status = 0
        status_text = "невыполненным ⏳"
    else:
        # Если выбрано что-то некорректное, запрашиваем снова
        action_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        action_keyboard.row("Отметить как выполненное", "Отметить как невыполненное")
        action_keyboard.row("Назад")
        msg = bot.reply_to(
            message,
            "Пожалуйста, выбери одно из предложенных действий:",
            reply_markup=action_keyboard
        )
        bot.register_next_step_handler(
            msg,
            lambda m: handle_deadline_action(m, deadlines, selected_deadline_idx)
        )
        logger.info(f"Пользователь {user_id} ввёл некорректное действие: '{action}', запрошен повторный выбор")
        return

    conn = sqlite3.connect("deadlines.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE deadlines SET completed = ? WHERE id = ?",
        (new_status, deadline[0])
    )
    conn.commit()
    conn.close()

    bot.reply_to(
        message,
        f"Дедлайн '{deadline[1]}' отмечен как {status_text}!",
        reply_markup=main_menu()
    )
    logger.info(f"Пользователь {user_id} отметил дедлайн '{deadline[1]}' как {status_text}")


# Добавление дедлайна
@bot.message_handler(func=lambda message: message.text == "Добавить дедлайн")
def add_deadline(message):
    msg = bot.reply_to(
        message,
        "Как называется дедлайн? (например, Курсовая по матанализу)",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    bot.register_next_step_handler(msg, title)



def title(message):
    title = message.text.strip()
    if not title:
        msg = bot.reply_to(message, "Название не может быть пустым. Попробуй снова:")
        bot.register_next_step_handler(msg, title)
        return
    bot.set_state(message.from_user.id, "title", message.chat.id)
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data["title"] = title
    now = datetime.now(TIMEZONE)
    calendar_keyboard = calendar.create_calendar(
        year=now.year, month=now.month
    )
    bot.reply_to(message, "Выбери дату:", reply_markup=calendar_keyboard)

# Обработка выбора даты
@bot.callback_query_handler(func=lambda call: call.data.startswith("calendar"))
def handle_calendar(call):
    name, action, year, month, day = call.data.split(calendar_callback.sep)
    calendar.calendar_query_handler(
        bot=bot,
        call=call,
        name=name,
        action=action,
        year=int(year),
        month=int(month),
        day=day,
    )
    if action == "DAY":
        try:
            day_int = int(day)
            with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
                # Инициализируем дату с временем 23:59 по умолчанию
                data["date"] = datetime(int(year), int(month), day_int, 23, 59, tzinfo=TIMEZONE)
            hours_keyboard = types.InlineKeyboardMarkup()
            for hour in range(0, 24, 4):
                hours_keyboard.row(*[types.InlineKeyboardButton(f"{h:02d}:00", callback_data=f"time_{h}") for h in
                                     range(hour, min(hour + 4, 24))])
            bot.send_message(call.message.chat.id, "Выбери время (обязательно):", reply_markup=hours_keyboard)
        except ValueError:
            bot.answer_callback_query(call.id, "Пожалуйста, выбери день из календаря.")


# Обработка выбора часа
@bot.callback_query_handler(func=lambda call: call.data.startswith("time_"))
def handle_time(call):
    bot.answer_callback_query(call.id)
    hour = int(call.data.split("_")[1])
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        data["hour"] = hour

    minutes_keyboard = types.InlineKeyboardMarkup()
    for minute in range(0, 60, 20):
        buttons = [
            types.InlineKeyboardButton(f"{m:02d}", callback_data=f"minutes_{hour}_{m}")
            for m in range(minute, min(minute + 20, 60), 5)
        ]
        minutes_keyboard.row(*buttons)
    bot.edit_message_text("Выбери минуты (обязательно):", call.message.chat.id, call.message.message_id,
                          reply_markup=minutes_keyboard)


# Обработка выбора минут
@bot.callback_query_handler(func=lambda call: call.data.startswith("minutes_"))
def handle_minutes(call):
    bot.answer_callback_query(call.id)
    hour, minute = map(int, call.data.split("_")[1:])
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        date = data["date"]
        date = date.replace(hour=hour, minute=minute)
        now = datetime.now(TIMEZONE)
        if date < now:
            bot.edit_message_text("Дата в прошлом. Начни заново с /cancel и выбери новую дату.", call.message.chat.id,
                                  call.message.message_id)
            return
        data["date"] = date  # Обновляем дату с выбранным временем
    bot.edit_message_text("Время выбрано!", call.message.chat.id, call.message.message_id)
    confirm_time(call.message, date)


# Подтверждение времени
def confirm_time(message, selected_time):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data["date"] = selected_time

    confirm_keyboard = types.InlineKeyboardMarkup()
    confirm_keyboard.row(
        types.InlineKeyboardButton("Подтвердить", callback_data="confirm_time"),
        types.InlineKeyboardButton("Очистить", callback_data="clear_time"),
        types.InlineKeyboardButton("Отменить", callback_data="cancel_time")
    )
    bot.send_message(
        message.chat.id,
        f"Выбрано время: {selected_time.strftime('%d.%m.%Y %H:%M')}. Подтверди выбор:",
        reply_markup=confirm_keyboard
    )


# Обработка подтверждения времени
@bot.callback_query_handler(func=lambda call: call.data in ["confirm_time", "clear_time", "cancel_time"])
def handle_time_confirmation(call):
    bot.answer_callback_query(call.id)
    if call.data == "confirm_time":
        bot.edit_message_text("Время подтверждено ✅!", call.message.chat.id, call.message.message_id)
        bot.set_state(call.from_user.id, "description", call.message.chat.id)
        skip_keyboard = types.InlineKeyboardMarkup()
        skip_keyboard.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_description"))
        msg = bot.send_message(call.message.chat.id, "Введи описание (или нажми 'Пропустить'):",
                               reply_markup=skip_keyboard)
        bot.register_next_step_handler(msg, process_description)
    elif call.data == "clear_time":
        with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
            date = data["date"]
        hours_keyboard = types.InlineKeyboardMarkup()
        for hour in range(0, 24, 4):
            hours_keyboard.row(*[types.InlineKeyboardButton(f"{h:02d}:00", callback_data=f"time_{h}") for h in
                                 range(hour, min(hour + 4, 24))])
        bot.edit_message_text("Выбери время заново:", call.message.chat.id, call.message.message_id,
                              reply_markup=hours_keyboard)
    elif call.data == "cancel_time":
        bot.edit_message_text("Действие отменено.", call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "Выбери, что хочешь сделать:", reply_markup=main_menu())
        bot.delete_state(call.from_user.id, call.message.chat.id)


def process_description(message):
    state = bot.get_state(message.from_user.id, message.chat.id)
    if state != "description":
        return

    description = message.text.strip()
    if description.lower() == "пропустить":
        description = ""

    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data["description"] = description

    bot.set_state(message.from_user.id, "photo", message.chat.id)
    skip_keyboard = types.InlineKeyboardMarkup()
    skip_keyboard.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_photo"))
    msg = bot.reply_to(message, "Прикрепи фото к описанию (или нажми 'Пропустить'):", reply_markup=skip_keyboard)
    bot.register_next_step_handler(msg, process_photo)


def process_photo(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    state = bot.get_state(user_id, chat_id)
    if state != "photo":
        return

    if message.photo:
        photo = message.photo[-1]
        file_id = photo.file_id
        with bot.retrieve_data(user_id, chat_id) as data:
            data["photo_file_id"] = file_id

        bot.set_state(user_id, "reminder", chat_id)
        reminder_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        reminder_keyboard.row("За 1 час", "За 1 день")
        reminder_keyboard.row("За 3 дня", "Без напоминания")
        msg = bot.reply_to(message, "Фото сохранено! Когда напомнить?", reply_markup=reminder_keyboard)
        bot.register_next_step_handler(msg, reminder)
    else:
        skip_keyboard = types.InlineKeyboardMarkup()
        skip_keyboard.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_photo"))
        msg = bot.reply_to(message, "Пожалуйста, отправь фото (или нажми 'Пропустить'):", reply_markup=skip_keyboard)
        bot.register_next_step_handler(msg, process_photo)


@bot.callback_query_handler(func=lambda call: call.data == "skip_photo")
def skip_photo(call):
    bot.answer_callback_query(call.id)
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        data["photo_file_id"] = None

    bot.set_state(call.from_user.id, "reminder", call.message.chat.id)
    reminder_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    reminder_keyboard.row("За 1 час", "За 1 день")
    reminder_keyboard.row("За 3 дня", "Без напоминания")
    bot.edit_message_text("Фото пропущено.", call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "Когда напомнить?", reply_markup=reminder_keyboard)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, reminder)


@bot.callback_query_handler(func=lambda call: call.data == "skip_description")
def skip_description(call):
    bot.answer_callback_query(call.id)
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        data["description"] = ""

    bot.set_state(call.from_user.id, "photo", call.message.chat.id)
    skip_keyboard = types.InlineKeyboardMarkup()
    skip_keyboard.add(types.InlineKeyboardButton("Пропустить", callback_data="skip_photo"))
    bot.edit_message_text("Описание пропущено.", call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "Прикрепи фото к описанию (или нажми 'Пропустить'):",
                     reply_markup=skip_keyboard)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, process_photo)


# Функция отправки напоминания
def send_notification(user_id, title, date, photo_file_id=None, is_due=False):
    if is_due:
        response = f"⏰ Дедлайн '{title}' наступил! Дата: {date.strftime('%d.%m.%Y %H:%M')}"
    else:
        response = f"Напоминание: '{title}' скоро! Дата: {date.strftime('%d.%m.%Y %H:%M')}"
    try:
        if photo_file_id:
            bot.send_photo(user_id, photo_file_id, caption=response)
        else:
            bot.send_message(user_id, response)
        logger.info(f"Уведомление отправлено пользователю {user_id}: {response}")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")


def schedule_notification(user_id, title, date, photo_file_id, reminder_time, is_due=False):
    now = datetime.now(TIMEZONE)
    if reminder_time <= now:
        logger.warning(f"Время напоминания {reminder_time} уже прошло, уведомление не будет отправлено.")
        return
    seconds_until_notification = (reminder_time - now).total_seconds()
    logger.info(
        f"Запланировано уведомление для {user_id} на {reminder_time} (через {seconds_until_notification} секунд)")
    timer = threading.Timer(
        seconds_until_notification,
        send_notification,
        args=(user_id, title, date, photo_file_id, is_due)
    )
    timer.start()


def reminder(message):
    state = bot.get_state(message.from_user.id, message.chat.id)
    if state != "reminder":
        return

    reminder = message.text
    user_id = message.from_user.id
    valid_reminders = ["За 1 час", "За 1 день", "За 3 дня", "Без напоминания"]
    if reminder not in valid_reminders:
        reminder_keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        reminder_keyboard.row("За 1 час", "За 1 день")
        reminder_keyboard.row("За 3 дня", "Без напоминания")
        msg = bot.reply_to(message, "Пожалуйста, выбери один из предложенных вариантов напоминания:",
                           reply_markup=reminder_keyboard)
        bot.register_next_step_handler(msg, reminder)
        return

    with bot.retrieve_data(user_id, message.chat.id) as data:
        data["reminder"] = reminder
        deadline = data

    conn = sqlite3.connect("deadlines.db")
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO deadlines (user_id, title, date, description, reminder, photo_file_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            deadline["title"],
            deadline["date"].strftime("%Y-%m-%d %H:%M:%S"),
            deadline["description"],
            reminder,
            deadline.get("photo_file_id"),
        ),
    )
    conn.commit()
    conn.close()

    # Планируем уведомление о наступлении дедлайна
    schedule_notification(
        user_id=user_id,
        title=deadline["title"],
        date=deadline["date"],
        photo_file_id=deadline.get("photo_file_id"),
        reminder_time=deadline["date"],
        is_due=True
    )

    # Планируем напоминание (если выбрано)
    if reminder != "Без напоминания":
        reminder_time = {
            "За 1 час": deadline["date"] - timedelta(hours=1),
            "За 1 день": deadline["date"] - timedelta(days=1),
            "За 3 дня": deadline["date"] - timedelta(days=3),
        }[reminder]
        schedule_notification(
            user_id=user_id,
            title=deadline["title"],
            date=deadline["date"],
            photo_file_id=deadline.get("photo_file_id"),
            reminder_time=reminder_time,
            is_due=False
        )

    bot.reply_to(
        message,
        f"Дедлайн '{deadline['title']}' на "
        f"{deadline['date'].strftime('%d.%m.%Y %H:%M')} добавлен! "
        f"Напомню {reminder}.",
        reply_markup=main_menu(),
    )
    bot.delete_state(message.from_user.id, message.chat.id)


# Удаление дедлайна
@bot.message_handler(func=lambda message: message.text == "Удалить дедлайн")
def delete_deadline(message):
    user_id = message.from_user.id
    conn = sqlite3.connect("deadlines.db")
    cursor = conn.cursor()
    # Добавляем completed в выборку, чтобы отображать статус
    cursor.execute(
        "SELECT id, title, date, completed FROM deadlines WHERE user_id = ?",
        (user_id,),
    )
    deadlines = cursor.fetchall()
    conn.close()

    if not deadlines:
        bot.reply_to(message, "У тебя нет дедлайнов для удаления.", reply_markup=main_menu())
        return

    response = "Выбери дедлайн для удаления:\n"
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for idx, deadline in enumerate(deadlines, 1):
        deadline_date = datetime.strptime(deadline[2], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE)
        status = "✅ Выполнено" if deadline[3] == 1 else "⏳ Не выполнено"
        response += f"{idx}. {deadline[1]} — {deadline_date.strftime('%d.%m.%Y %H:%M')}, {status}\n"
        keyboard.add(str(idx))
    keyboard.add("Отмена")

    bot.set_state(message.from_user.id, "delete_deadline", message.chat.id)
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data["deadlines"] = deadlines

    msg = bot.reply_to(message, response, reply_markup=keyboard)
    bot.register_next_step_handler(msg, delete_choice)


def delete_choice(message):
    choice = message.text
    if choice.lower() == "отмена":
        bot.reply_to(message, "Удаление отменено.", reply_markup=main_menu())
        bot.delete_state(message.from_user.id, message.chat.id)
        return

    try:
        idx = int(choice) - 1
        with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
            if "deadlines" not in data:
                bot.reply_to(message, "Ошибка: данные о дедлайнах потеряны. Попробуй снова.", reply_markup=main_menu())
                bot.delete_state(message.from_user.id, message.chat.id)
                return
            deadlines = data["deadlines"]

        if 0 <= idx < len(deadlines):
            with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
                data["selected_deadline_idx"] = idx
            confirm_delete(message, deadlines[idx])
        else:
            msg = bot.reply_to(message, "Неверный номер. Попробуй снова:")
            bot.register_next_step_handler(msg, delete_choice)
            return
    except ValueError:
        msg = bot.reply_to(message, "Выбери номер дедлайна или 'Отмена':")
        bot.register_next_step_handler(msg, delete_choice)
        return


def confirm_delete(message, deadline):
    deadline_date = datetime.strptime(deadline[2], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE)
    confirm_keyboard = types.InlineKeyboardMarkup()
    confirm_keyboard.row(
        types.InlineKeyboardButton("Подтвердить", callback_data="confirm_delete"),
        types.InlineKeyboardButton("Очистить", callback_data="clear_delete"),
        types.InlineKeyboardButton("Отменить", callback_data="cancel_delete")
    )
    bot.send_message(
        message.chat.id,
        f"Выбран дедлайн для удаления: {deadline[1]} — {deadline_date.strftime('%d.%m.%Y %H:%M')}. Подтверди выбор:",
        reply_markup=confirm_keyboard
    )


@bot.callback_query_handler(func=lambda call: call.data in ["confirm_delete", "clear_delete", "cancel_delete"])
def handle_delete_confirmation(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    with bot.retrieve_data(user_id, chat_id) as data:
        if "selected_deadline_idx" not in data or "deadlines" not in data:
            bot.edit_message_text("Ошибка: данные о дедлайне потеряны. Попробуй снова.", chat_id,
                                  call.message.message_id)
            bot.delete_state(user_id, chat_id)
            return
        idx = data["selected_deadline_idx"]
        deadlines = data["deadlines"]
        deadline = deadlines[idx]

    if call.data == "confirm_delete":
        conn = sqlite3.connect("deadlines.db")
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE deadlines SET completed = 1 WHERE id = ?", (deadline[0],)
        )
        conn.commit()
        conn.close()

        bot.edit_message_text(f"Дедлайн '{deadline[1]}' удалён ✅!", chat_id, call.message.message_id)
        bot.send_message(chat_id, "Выбери, что хочешь сделать:", reply_markup=main_menu())
        bot.delete_state(user_id, chat_id)

    elif call.data == "clear_delete":
        bot.delete_message(chat_id, call.message.message_id)

        response = "Выбери дедлайн для удаления:\n"
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for idx, deadline in enumerate(deadlines, 1):
            deadline_date = datetime.strptime(deadline[2], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE)
            status = "✅ Выполнено" if deadline[3] == 1 else "⏳ Не выполнено"
            response += f"{idx}. {deadline[1]} — {deadline_date.strftime('%d.%m.%Y %H:%M')}, {status}\n"
            keyboard.add(str(idx))
        keyboard.add("Отмена")

        msg = bot.send_message(chat_id, response, reply_markup=keyboard)
        bot.register_next_step_handler(msg, delete_choice)

    elif call.data == "cancel_delete":
        bot.edit_message_text("Удаление отменено.", chat_id, call.message.message_id)
        bot.send_message(chat_id, "Выбери, что хочешь сделать:", reply_markup=main_menu())
        bot.delete_state(user_id, chat_id)


# Обработка кнопки техподдержки
@bot.callback_query_handler(func=lambda call: call.data == "support")
def handle_support(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "📖 Часто задаваемые вопросы (FAQ):\nВыбери вопрос или напиши разработчикам:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=faq_keyboard()
    )


# Обработка FAQ
@bot.callback_query_handler(func=lambda call: call.data.startswith("faq_"))
def handle_faq(call):
    bot.answer_callback_query(call.id)
    faq_answers = {
        "faq_add_deadline": "Чтобы добавить дедлайн:\n1. Нажми 'Добавить дедлайн'.\n2. Введи название.\n3. Выбери дату и время.\n4. Добавь описание и фото (или пропусти).\n5. Укажи, когда напомнить.",
        "faq_delete_deadline": "Чтобы удалить дедлайн:\n1. Нажми 'Удалить дедлайн'.\n2. Выбери дедлайн из списка.\n3. Подтверди удаление.",
        "faq_reminder": "Напоминания работают так:\n- Выбери 'За 1 час', 'За 1 день' или 'За 3 дня' при добавлении дедлайна.\n- Бот отправит тебе сообщение за указанное время до дедлайна, а также в момент наступления дедлайна."
    }
    question = call.data
    answer = faq_answers.get(question, "Ответ на этот вопрос пока не добавлен.")
    bot.edit_message_text(
        f"{answer}\n\n📖 Другие вопросы или написать разработчикам:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=faq_keyboard()
    )


# Обработка "Написать разработчикам"
@bot.callback_query_handler(func=lambda call: call.data == "contact_support")
def handle_contact_support(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "Связаться с разработчиком: [@MILAVIA](https://t.me/MILAVIA)",
        call.message.chat.id,

        call.message.message_id,
        parse_mode="Markdown"
    )


# Отмена
@bot.message_handler(commands=["cancel"])
def cancel(message):
    bot.reply_to(message, "Действие отменено.", reply_markup=main_menu())
    bot.delete_state(message.from_user.id, message.chat.id)


# Запуск бота
def main():
    init_db()
    bot.polling()


if __name__ == "__main__":
    main()


