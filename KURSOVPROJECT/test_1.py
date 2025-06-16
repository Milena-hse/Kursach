import unittest
from unittest.mock import MagicMock, patch
import sqlite3
from datetime import datetime, timedelta
import pytz
import telebot

# Импортируем всех необходимых функций из файла bot.py
from bot import (
    start, add_deadline, title, handle_calendar, handle_time, handle_minutes,
    confirm_time, process_description, process_photo, skip_photo, skip_description, reminder,
    view_deadlines, select_deadline, handle_deadline_action, delete_deadline,
    delete_choice, confirm_delete, handle_delete_confirmation, handle_support,
    handle_faq, handle_contact_support, cancel, init_db, send_notification,
    schedule_notification, TIMEZONE,
    main_menu, support_button, faq_keyboard,
    calendar, calendar_callback,
)

class TestTelegramBot(unittest.TestCase):

    def setUp(self):
        self.mock_bot = patch('bot.bot').start()
        self.mock_calendar_class_instance = patch('bot.Calendar').start()
        self.mock_callback_data_class_instance = patch('bot.CallbackData').start()

        self.mock_bot.reply_to = MagicMock()
        self.mock_bot.send_message = MagicMock()
        self.mock_bot.edit_message_text = MagicMock()
        self.mock_bot.answer_callback_query = MagicMock()
        self.mock_bot.register_next_step_handler = MagicMock()
        self.mock_bot.register_next_step_handler_by_chat_id = MagicMock()
        self.mock_bot.set_state = MagicMock()
        self.mock_bot.delete_state = MagicMock()
        self.mock_bot.send_photo = MagicMock()
        self.mock_bot.delete_message = MagicMock()

        self.mock_bot_retrieve_data_context = MagicMock()
        self.mock_data_dict = {}
        self.mock_bot_retrieve_data_context.__enter__.return_value = self.mock_data_dict
        self.mock_bot.retrieve_data = MagicMock(return_value=self.mock_bot_retrieve_data_context)
        self.mock_bot.get_state = MagicMock(return_value=None)

        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()
        self.cursor.execute(
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
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        patch('bot.bot').stop()
        patch('bot.Calendar').stop()
        patch('bot.CallbackData').stop()
        self.mock_bot.reset_mock()
        self.mock_data_dict.clear()
        self.mock_bot.get_state.reset_mock()

    # --- Тесты для команды /start ---
    def test_start_command(self):
        mock_message = MagicMock()
        mock_message.from_user.first_name = "TestUser"
        mock_message.chat.id = 12345

        start(mock_message)

        self.mock_bot.reply_to.assert_called_once_with(
            mock_message,
            "Привет, TestUser! Я бот для управления дедлайнами.\nВыбери, что хочешь сделать:",
            reply_markup=unittest.mock.ANY
        )
        self.mock_bot.send_message.assert_called_once_with(
            mock_message.chat.id,
            "Если нужна помощь, обращайся в техподдержку:",
            reply_markup=unittest.mock.ANY
        )

    # --- Тесты для добавления дедлайна ---
    def test_add_deadline_initiates_title_input(self):
        mock_message = MagicMock()
        add_deadline(mock_message)
        self.mock_bot.reply_to.assert_called_once_with(
            mock_message,
            "Как называется дедлайн? (например, Курсовая по матанализу)",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            self.mock_bot.reply_to.return_value, title
        )

    def test_title_sets_state_and_asks_for_date(self):
        mock_message = MagicMock()
        mock_message.text = "Мой дедлайн"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        title(mock_message)

        self.mock_bot.set_state.assert_called_once_with(1, "title", 123)
        self.assertEqual(self.mock_data_dict['title'], 'Мой дедлайн')
        self.mock_bot.send_message.assert_called_once_with(
            123, "Выбери дату:", reply_markup=unittest.mock.ANY
        )
        self.mock_bot.register_next_step_handler.assert_not_called()

    def test_title_handles_empty_input(self):
        mock_message = MagicMock()
        mock_message.text = ""
        mock_message.chat.id = 123

        title(mock_message)

        self.mock_bot.reply_to.assert_called_once_with(
            mock_message, "Название не может быть пустым. Попробуй снова:"
        )
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            mock_message, title
        )
        self.mock_bot.set_state.assert_not_called()

    @patch('bot.datetime')
    def test_handle_calendar_day_selection(self, mock_datetime_class):
        mock_call = MagicMock()
        mock_call.data = calendar_callback.new("DAY", 2025, 6, 15)
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 14, 10, 0, 0))
        mock_datetime_class.strptime = datetime.strptime

        self.mock_data_dict.clear()
        self.mock_data_dict['user_id'] = 1

        handle_calendar(mock_call)

        self.mock_bot.send_message.assert_called_once_with(
            123, "Выбери время (обязательно):", reply_markup=unittest.mock.ANY
        )
        expected_date = TIMEZONE.localize(datetime(2025, 6, 15, 0, 0, 0))
        self.assertEqual(self.mock_data_dict['date'].date(), expected_date.date())
        self.mock_bot.edit_message_text.assert_called_once_with(
            unittest.mock.ANY, 123, 456
        )

    @patch('bot.datetime')
    def test_handle_time_sets_hour(self, mock_datetime_class):
        mock_call = MagicMock()
        mock_call.data = "time_14"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        selected_date_no_time = TIMEZONE.localize(datetime(2025, 6, 15, 0, 0, 0))
        self.mock_data_dict = {
            'date': selected_date_no_time,
            'user_id': 1
        }
        mock_datetime_class.strptime = datetime.strptime

        handle_time(mock_call)

        self.assertEqual(self.mock_data_dict['hour'], 14)
        self.mock_bot.edit_message_text.assert_called_once_with(
            "Выбери минуты (обязательно):", 123, 456, reply_markup=unittest.mock.ANY
        )
        self.mock_bot.set_state.assert_called_once_with(1, 'hour', 123)

    @patch('bot.datetime')
    def test_handle_minutes_sets_minutes_and_confirms(self, mock_datetime_class):
        mock_call = MagicMock()
        mock_call.data = "minutes_14_30"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        selected_date = TIMEZONE.localize(datetime(2025, 6, 15, 0, 0, 0))
        self.mock_data_dict = {
            'date': selected_date,
            'hour': 14,
            'user_id': 1
        }
        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 14, 10, 0, 0))
        mock_datetime_class.strptime = datetime.strptime

        handle_minutes(mock_call)

        expected_date = TIMEZONE.localize(datetime(2025, 6, 15, 14, 30, 0))
        self.assertEqual(self.mock_data_dict['date'], expected_date)
        self.mock_bot.edit_message_text.assert_called_once_with("Время выбрано!", 123, 456)
        self.mock_bot.send_message.assert_called_once_with(
            123,
            f"Выбрано время: {expected_date.strftime('%d.%m.%Y %H:%M')}. Подтверди выбор:",
            reply_markup=unittest.mock.ANY
        )
        self.mock_bot.set_state.assert_called_once_with(1, 'minutes', 123)

    @patch('bot.datetime')
    def test_handle_minutes_past_date_error(self, mock_datetime_class):
        mock_call = MagicMock()
        mock_call.data = "minutes_10_00"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        past_date = TIMEZONE.localize(datetime(2025, 6, 10, 0, 0, 0))
        self.mock_data_dict = {
            'date': past_date,
            'hour': 10,
            'user_id': 1
        }
        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 14, 10, 0, 0))
        mock_datetime_class.strptime = datetime.strptime

        handle_minutes(mock_call)

        self.mock_bot.edit_message_text.assert_called_once_with(
            "Дата в прошлом. Начни заново с /cancel и выбери новую дату.", 123, 456
        )
        self.mock_bot.send_message.assert_not_called()
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    def test_confirm_time_confirm_action(self):
        mock_message = MagicMock()
        mock_message.from_user.id = 1
        mock_message.chat.id = 123
        mock_message.message_id = 456

        selected_time = TIMEZONE.localize(datetime(2025, 6, 15, 14, 30, 0))
        self.mock_data_dict['date'] = selected_time
        self.mock_data_dict['user_id'] = 1

        confirm_time(mock_message, selected_time)

        self.mock_bot.edit_message_text.assert_called_once_with("Время подтверждено ✅!", 123, 456)
        self.mock_bot.set_state.assert_called_once_with(1, "description", 123)
        self.mock_bot.send_message.assert_called_once_with(
            123, "Введи описание (или нажми 'Пропустить'):", reply_markup=unittest.mock.ANY
        )
        self.mock_bot.register_next_step_handler.assert_called_once_with(self.mock_bot.send_message.return_value, process_description)

    def test_confirm_time_cancel_action(self):
        mock_message = MagicMock()
        mock_message.from_user.id = 1
        mock_message.chat.id = 123
        mock_message.message_id = 456

        self.mock_data_dict['user_id'] = 1

        confirm_time(mock_message, None)

        self.mock_bot.edit_message_text.assert_called_once_with("Действие отменено.", 123, 456)
        self.mock_bot.send_message.assert_called_once_with(
            123, "Выбери, что хочешь сделать:", reply_markup=unittest.mock.ANY
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    def test_process_description_with_input(self):
        mock_message = MagicMock()
        mock_message.text = "Это тестовое описание"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.mock_bot.get_state.return_value = "description"
        self.mock_data_dict['user_id'] = 1

        process_description(mock_message)

        self.assertEqual(self.mock_data_dict['description'], 'Это тестовое описание')
        self.mock_bot.set_state.assert_called_once_with(1, "photo", 123)
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Прикрепи фото к описанию (или нажми 'Пропустить'):", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler.assert_called_once_with(mock_message, process_photo)

    def test_process_description_skip_input(self):
        mock_message = MagicMock()
        mock_message.text = "пропустить"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.mock_bot.get_state.return_value = "description"
        self.mock_data_dict['user_id'] = 1

        process_description(mock_message)

        self.assertEqual(self.mock_data_dict['description'], '')
        self.mock_bot.set_state.assert_called_once_with(1, "photo", 123)
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Прикрепи фото к описанию (или нажми 'Пропустить'):", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler.assert_called_once_with(mock_message, process_photo)

    def test_process_photo_with_photo(self):
        mock_message = MagicMock()
        mock_message.photo = [MagicMock(file_id="AgAD_TestPhotoId")]
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.mock_bot.get_state.return_value = "photo"
        self.mock_data_dict['user_id'] = 1

        process_photo(mock_message)

        self.assertEqual(self.mock_data_dict['photo_file_id'], 'AgAD_TestPhotoId')
        self.mock_bot.set_state.assert_called_once_with(1, "reminder", 123)
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Фото сохранено! Когда напомнить?", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler.assert_called_once_with(mock_message, reminder)

    def test_process_photo_without_photo(self):
        mock_message = MagicMock()
        mock_message.photo = []
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.mock_bot.get_state.return_value = "photo"
        self.mock_data_dict['user_id'] = 1

        process_photo(mock_message)

        self.assertNotIn('photo_file_id', self.mock_data_dict)
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Пожалуйста, отправь фото (или нажми 'Пропустить'):", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler.assert_called_once_with(mock_message, process_photo)

    def test_skip_photo(self):
        mock_call = MagicMock()
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        self.mock_data_dict['user_id'] = 1

        skip_photo(mock_call)

        self.assertEqual(self.mock_data_dict['photo_file_id'], None)
        self.mock_bot.set_state.assert_called_once_with(1, "reminder", 123)
        self.mock_bot.edit_message_text.assert_called_once_with("Фото пропущено.", 123, 456)
        self.mock_bot.send_message.assert_called_once_with(123, "Когда напомнить?", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler_by_chat_id.assert_called_once_with(123, reminder)

    def test_skip_description(self):
        mock_call = MagicMock()
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        self.mock_data_dict['user_id'] = 1

        skip_description(mock_call)

        self.assertEqual(self.mock_data_dict['description'], '')
        self.mock_bot.set_state.assert_called_once_with(1, "photo", 123)
        self.mock_bot.edit_message_text.assert_called_once_with("Описание пропущено.", 123, 456)
        self.mock_bot.send_message.assert_called_once_with(123, "Прикрепи фото к описанию (или нажми 'Пропустить'):", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler_by_chat_id.assert_called_once_with(123, process_photo)

    @patch('bot.threading.Timer')
    @patch('bot.datetime')
    @patch('bot.sqlite3.connect')
    def test_reminder_adds_deadline_and_schedules_notifications(self, mock_sqlite_connect, mock_datetime_class, mock_timer):
        mock_sqlite_connect.return_value = self.conn

        mock_message = MagicMock()
        mock_message.text = "За 1 день"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadline_dt = TIMEZONE.localize(datetime(2025, 7, 1, 10, 0, 0))
        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 30, 9, 0, 0))
        mock_datetime_class.strptime = datetime.strptime

        self.mock_data_dict = {
            'title': 'Тестовый дедлайн',
            'date': deadline_dt,
            'description': 'Тестовое описание',
            'photo_file_id': 'photo_123',
            'user_id': 1
        }

        self.mock_bot.get_state.return_value = "reminder"

        reminder(mock_message)

        self.cursor.execute("SELECT * FROM deadlines WHERE user_id = ?", (1,))
        added_deadline = self.cursor.fetchone()
        self.assertIsNotNone(added_deadline)
        self.assertEqual(added_deadline[2], self.mock_data_dict['title'])
        self.assertEqual(added_deadline[3], self.mock_data_dict['date'].strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(added_deadline[4], self.mock_data_dict['description'])
        self.assertEqual(added_deadline[5], 'За 1 день')
        self.assertEqual(added_deadline[6], self.mock_data_dict['photo_file_id'])
        self.assertEqual(added_deadline[7], 0)

        time_to_wait_due = (deadline_dt - mock_datetime_class.now.return_value).total_seconds()
        mock_timer.assert_any_call(time_to_wait_due, send_notification, args=(1, 'Тестовый дедлайн', deadline_dt, 'photo_123', True))
        mock_timer.return_value.start.assert_called()

        reminder_time = deadline_dt - timedelta(days=1)
        time_to_wait_reminder = (reminder_time - mock_datetime_class.now.return_value).total_seconds()
        mock_timer.assert_any_call(time_to_wait_reminder, send_notification, args=(1, 'Тестовый дедлайн', deadline_dt, 'photo_123', False))
        mock_timer.return_value.start.assert_called()

        expected_message = (
            f"Дедлайн '{self.mock_data_dict['title']}' на "
            f"{self.mock_data_dict['date'].strftime('%d.%m.%Y %H:%M')} добавлен! "
            f"Напомню {self.mock_data_dict['reminder']}."
        )
        self.mock_bot.reply_to.assert_called_once_with(
            mock_message,
            expected_message,
            reply_markup=main_menu()
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    # --- Тесты для просмотра и управления дедлайнами ---
    def test_view_deadlines(self):
        mock_message = MagicMock()
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.cursor.execute("INSERT INTO deadlines (user_id, title, date) VALUES (?, ?, ?)", (1, "Дедлайн 1", "2025-06-17 14:00:00"))
        self.conn.commit()

        view_deadlines(mock_message)

        self.mock_bot.send_message.assert_called_once_with(
            123, "Твой список дедлайнов:\n- Дедлайн 1 (17.06.2025 14:00)", reply_markup=unittest.mock.ANY
        )

    def test_select_deadline(self):
        mock_call = MagicMock()
        mock_call.data = "select_1"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        self.cursor.execute("INSERT INTO deadlines (id, user_id, title, date) VALUES (?, ?, ?, ?)", (1, 1, "Дедлайн 1", "2025-06-17 14:00:00"))
        self.conn.commit()

        select_deadline(mock_call)

        self.mock_bot.edit_message_text.assert_called_once_with(
            "Выбрано: Дедлайн 1\nЧто сделать?", 123, 456, reply_markup=unittest.mock.ANY
        )
        self.assertEqual(self.mock_data_dict['selected_deadline_id'], 1)

    def test_handle_deadline_action_complete(self):
        mock_call = MagicMock()
        mock_call.data = "complete_1"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        self.cursor.execute("INSERT INTO deadlines (id, user_id, title, date) VALUES (?, ?, ?, ?)", (1, 1, "Дедлайн 1", "2025-06-17 14:00:00"))
        self.conn.commit()

        handle_deadline_action(mock_call)

        self.cursor.execute("SELECT completed FROM deadlines WHERE id = ?", (1,))
        completed = self.cursor.fetchone()[0]
        self.assertEqual(completed, 1)
        self.mock_bot.edit_message_text.assert_called_once_with(
            "Дедлайн 'Дедлайн 1' отмечен как выполненный!", 123, 456, reply_markup=unittest.mock.ANY
        )

    def test_delete_deadline(self):
        mock_call = MagicMock()
        mock_call.data = "delete_1"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        self.cursor.execute("INSERT INTO deadlines (id, user_id, title, date) VALUES (?, ?, ?, ?)", (1, 1, "Дедлайн 1", "2025-06-17 14:00:00"))
        self.conn.commit()

        delete_deadline(mock_call)

        self.mock_bot.edit_message_text.assert_called_once_with(
            "Удалить дедлайн 'Дедлайн 1'?", 123, 456, reply_markup=unittest.mock.ANY
        )
        self.assertEqual(self.mock_data_dict['selected_deadline_id'], 1)

    def test_delete_choice_confirm(self):
        mock_call = MagicMock()
        mock_call.data = "confirm_delete_1"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        self.cursor.execute("INSERT INTO deadlines (id, user_id, title, date) VALUES (?, ?, ?, ?)", (1, 1, "Дедлайн 1", "2025-06-17 14:00:00"))
        self.conn.commit()

        delete_choice(mock_call)

        self.cursor.execute("SELECT * FROM deadlines WHERE id = ?", (1,))
        self.assertIsNone(self.cursor.fetchone())
        self.mock_bot.edit_message_text.assert_called_once_with(
            "Дедлайн 'Дедлайн 1' удалён.", 123, 456, reply_markup=main_menu()
        )

    def test_delete_choice_cancel(self):
        mock_call = MagicMock()
        mock_call.data = "cancel_delete_1"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        delete_choice(mock_call)

        self.mock_bot.edit_message_text.assert_called_once_with(
            "Удаление отменено.", 123, 456, reply_markup=main_menu()
        )

    # --- Тесты для поддержки и FAQ ---
    def test_handle_support(self):
        mock_message = MagicMock()
        mock_message.chat.id = 123

        handle_support(mock_message)

        self.mock_bot.send_message.assert_called_once_with(
            123, "Выбери действие:", reply_markup=support_button()
        )

    def test_handle_faq(self):
        mock_message = MagicMock()
        mock_message.chat.id = 123

        handle_faq(mock_message)

        self.mock_bot.send_message.assert_called_once_with(
            123, "Часто задаваемые вопросы:\n1. Как добавить дедлайн? - Используй /add", reply_markup=faq_keyboard()
        )

    def test_handle_contact_support(self):
        mock_message = MagicMock()
        mock_message.chat.id = 123

        handle_contact_support(mock_message)

        self.mock_bot.send_message.assert_called_once_with(
            123, "Напишите нам: support@example.com", reply_markup=main_menu()
        )

    # --- Тесты для отмены ---
    def test_cancel(self):
        mock_message = MagicMock()
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        cancel(mock_message)

        self.mock_bot.reply_to.assert_called_once_with(
            mock_message, "Действие отменено.", reply_markup=main_menu()
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

if __name__ == "__main__":
    unittest.main()