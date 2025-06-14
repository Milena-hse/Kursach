import unittest
from unittest.mock import MagicMock, patch
import sqlite3
from datetime import datetime, timedelta # Импортируем реальный datetime здесь для использования в моках
import pytz

# Импортируем ВСЕ необходимые функции и константы из вашего файла bot.py
from bot import (
    start, add_deadline, title, handle_calendar, handle_time, handle_minutes,
    confirm_time,
    process_description, process_photo, skip_photo, skip_description, reminder,
    view_deadlines, select_deadline, handle_deadline_action, delete_deadline,
    delete_choice, confirm_delete, handle_delete_confirmation, handle_support,
    handle_faq, handle_contact_support, cancel, init_db, send_notification,
    schedule_notification, TIMEZONE,
    main_menu, support_button, faq_keyboard,
    calendar, calendar_callback # Оставляем, так как они используются в Keyboard Markup
)

# Глобальные патчи для объектов, которые часто используются
patch_bot = patch('bot.bot')
patch_calendar_class = patch('bot.Calendar')
patch_callback_data_class = patch('bot.CallbackData')

class TestTelegramBot(unittest.TestCase):

    def setUp(self):
        """
        Метод, который выполняется перед каждым тестом.
        Здесь мы настраиваем моки и имитируем базу данных.
        """
        self.mock_bot = patch_bot.start()
        self.mock_calendar_class_instance = patch_calendar_class.start()
        self.mock_callback_data_class_instance = patch_callback_data_class.start()

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
        # Этот мок имитирует контекстный менеджер (with bot.retrieve_data(...)),
        # поэтому у него должен быть __enter__ метод, возвращающий словарь.
        # А затем этот словарь должен быть моком, поддерживающим setitem.
        self.mock_data_dict = {} # Это будет фактический словарь для данных
        self.mock_bot_retrieve_data_context.__enter__.return_value = self.mock_data_dict
        self.mock_bot.retrieve_data = MagicMock(return_value=self.mock_bot_retrieve_data_context)
        self.mock_bot.get_state = MagicMock(return_value=None)


        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()
        self.patch_sqlite_connect = patch('sqlite3.connect', return_value=self.conn).start()

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
        """
        Метод, который выполняется после каждого теста.
        Очищаем состояние и останавливаем патчи.
        """
        self.conn.close()
        patch_bot.stop()
        patch_calendar_class.stop()
        patch_callback_data_class.stop()
        self.patch_sqlite_connect.stop()

        # Сброс моков, чтобы они были чистыми для следующего теста
        self.mock_bot.reset_mock()
        # Для mock_bot_retrieve_data_context и mock_data_dict нужно очищать вручную,
        # так как это не глобальные патчи.
        self.mock_data_dict.clear()
        self.mock_bot.get_state.reset_mock()

    # --- Тесты для команды /start ---
    def test_start_command(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.from_user.first_name = "TestUser"
        mock_message.chat.id = 12345

        # Act
        start(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(
            mock_message,
            "Привет, TestUser! Я бот для управления дедлайнами.\nВыбери, что хочешь сделать:",
            reply_markup=main_menu()
        )
        self.mock_bot.send_message.assert_called_once_with(
            mock_message.chat.id,
            "Если нужна помощь, обращайся в техподдержку:",
            reply_markup=support_button()
        )

    # --- Тесты для добавления дедлайна ---
    def test_add_deadline_initiates_title_input(self):
        # Arrange
        mock_message = MagicMock()

        # Act
        add_deadline(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Введи название дедлайна:")
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            self.mock_bot.reply_to.return_value, title
        )

    def test_title_sets_state_and_asks_for_date(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "Мой дедлайн"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        # Act
        title(mock_message)

        # Assert
        self.mock_bot.set_state.assert_called_once_with(1, "title", 123)
        # Проверяем, что значение установлено в mock_data_dict
        self.assertEqual(self.mock_data_dict['title'], 'Мой дедлайн')
        self.mock_bot.reply_to.assert_called_once()


    def test_title_handles_empty_input(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = ""
        mock_message.chat.id = 123

        # Act
        title(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Название не может быть пустым. Попробуй снова:")
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            self.mock_bot.reply_to.return_value, title
        )
        self.mock_bot.set_state.assert_not_called()

    # ИЗМЕНЕНИЕ ЗДЕСЬ: Правильный патчинг datetime
    @patch('bot.datetime') # Патчим класс datetime в bot.py
    def test_handle_calendar_day_selection(self, mock_datetime_class): # mock_datetime_class теперь имитирует класс datetime
        # Arrange
        mock_call = MagicMock()
        mock_call.data = calendar_callback.new("DAY", 2025, 6, 15)
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        # Мокируем datetime.now() для вашего патченного класса
        mock_datetime_class.now.return_value = datetime(2025, 6, 14, 10, 0, 0, tzinfo=TIMEZONE)
        # Делаем так, чтобы strptime на патченном классе вызывал реальный datetime.strptime
        mock_datetime_class.strptime = datetime.strptime # ЭТО КЛЮЧЕВОЕ ИЗМЕНЕНИЕ

        self.mock_data_dict.clear() # Очищаем словарь для этого теста

        # Act
        handle_calendar(mock_call)

        # Assert
        self.mock_bot.send_message.assert_called_once()
        args, kwargs = self.mock_bot.send_message.call_args
        self.assertEqual(args[0], 123)
        self.assertEqual(args[1], "Выбери время (обязательно):")
        expected_date = TIMEZONE.localize(datetime(2025, 6, 15, 23, 59, 0))
        # Проверяем, что значение установлено в mock_data_dict
        self.assertEqual(self.mock_data_dict['date'], expected_date)
        self.mock_bot.edit_message_text.assert_called_once()


    # ИЗМЕНЕНИЕ ЗДЕСЬ: Правильный патчинг datetime
    @patch('bot.datetime')
    def test_handle_time_sets_hour(self, mock_datetime_class):
        # Arrange
        mock_call = MagicMock()
        mock_call.data = "time_14"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        selected_date_no_time = TIMEZONE.localize(datetime(2025, 6, 15, 0, 0, 0))
        self.mock_data_dict = { # Используем mock_data_dict
            'date': selected_date_no_time
        }
        # Убедимся, что strptime вызывается на реальном datetime
        mock_datetime_class.strptime = datetime.strptime # ЭТО КЛЮЧЕВОЕ ИЗМЕНЕНИЕ

        # Act
        handle_time(mock_call)

        # Assert
        # Проверяем, что значение установлено в mock_data_dict
        self.assertEqual(self.mock_data_dict['hour'], 14)
        self.mock_bot.edit_message_text.assert_called_once_with(
            "Выбери минуты (обязательно):", 123, 456, reply_markup=unittest.mock.ANY
        )

    # ИЗМЕНЕНИЕ ЗДЕСЬ: Правильный патчинг datetime
    @patch('bot.datetime')
    def test_handle_minutes_sets_minutes_and_confirms(self, mock_datetime_class):
        # Arrange
        mock_call = MagicMock()
        mock_call.data = "minutes_14_30"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        selected_date = TIMEZONE.localize(datetime(2025, 6, 15, 0, 0, 0))
        self.mock_data_dict = { # Используем mock_data_dict
            'date': selected_date,
            'hour': 14
        }
        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 14, 10, 0, 0))
        mock_datetime_class.strptime = datetime.strptime # ЭТО КЛЮЧЕВОЕ ИЗМЕНЕНИЕ

        # Act
        handle_minutes(mock_call)

        # Assert
        expected_date = TIMEZONE.localize(datetime(2025, 6, 15, 14, 30, 0))
        # Проверяем, что значение установлено в mock_data_dict
        self.assertEqual(self.mock_data_dict['date'], expected_date)
        self.mock_bot.edit_message_text.assert_called_once_with("Время выбрано!", 123, 456)
        self.mock_bot.send_message.assert_called_once_with(
            123,
            f"Выбрано время: {expected_date.strftime('%d.%m.%Y %H:%M')}. Подтверди выбор:",
            reply_markup=unittest.mock.ANY
        )

    # ИЗМЕНЕНИЕ ЗДЕСЬ: Правильный патчинг datetime
    @patch('bot.datetime')
    def test_handle_minutes_past_date_error(self, mock_datetime_class):
        # Arrange
        mock_call = MagicMock()
        mock_call.data = "minutes_10_00"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        past_date = TIMEZONE.localize(datetime(2025, 6, 10, 0, 0, 0))
        self.mock_data_dict = { # Используем mock_data_dict
            'date': past_date,
            'hour': 10
        }
        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 14, 10, 0, 0))
        mock_datetime_class.strptime = datetime.strptime # ЭТО КЛЮЧЕВОЕ ИЗМЕНЕНИЕ

        # Act
        handle_minutes(mock_call)

        # Assert
        self.mock_bot.edit_message_text.assert_called_once_with(
            "Дата в прошлом. Начни заново с /cancel и выбери новую дату.", 123, 456
        )
        self.mock_bot.send_message.assert_not_called()

    def test_confirm_time_confirm_action(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.data = "confirm_time"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        # Act
        confirm_time(mock_call)

        # Assert
        self.mock_bot.edit_message_text.assert_called_once_with("Время подтверждено ✅!", 123, 456)
        self.mock_bot.set_state.assert_called_once_with(1, "description", 123)
        self.mock_bot.send_message.assert_called_once()
        self.mock_bot.register_next_step_handler.assert_called_once()

    def test_confirm_time_cancel_action(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.data = "cancel_time"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        # Act
        confirm_time(mock_call)

        # Assert
        self.mock_bot.edit_message_text.assert_called_once_with("Действие отменено.", 123, 456)
        self.mock_bot.send_message.assert_called_once_with(
            123, "Выбери, что хочешь сделать:", reply_markup=main_menu()
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)


    def test_process_description_with_input(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "Это тестовое описание"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.mock_bot.get_state.return_value = "description"
        # Act
        process_description(mock_message)

        # Assert
        self.assertEqual(self.mock_data_dict['description'], 'Это тестовое описание')
        self.mock_bot.set_state.assert_called_once_with(1, "photo", 123)
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Прикрепи фото к описанию (или нажми 'Пропустить'):", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler.assert_called_once_with(self.mock_bot.reply_to.return_value, process_photo)

    def test_process_description_skip_input(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "пропустить"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.mock_bot.get_state.return_value = "description"
        # Act
        process_description(mock_message)

        # Assert
        self.assertEqual(self.mock_data_dict['description'], '')
        self.mock_bot.set_state.assert_called_once_with(1, "photo", 123)
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Прикрепи фото к описанию (или нажми 'Пропустить'):", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler.assert_called_once_with(self.mock_bot.reply_to.return_value, process_photo)

    def test_process_photo_with_photo(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.photo = [MagicMock(file_id="AgAD_TestPhotoId")]
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.mock_bot.get_state.return_value = "photo"
        # Act
        process_photo(mock_message)

        # Assert
        self.assertEqual(self.mock_data_dict['photo_file_id'], 'AgAD_TestPhotoId')
        self.mock_bot.set_state.assert_called_once_with(1, "reminder", 123)
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Фото сохранено! Когда напомнить?", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler.assert_called_once_with(self.mock_bot.reply_to.return_value, reminder)

    def test_process_photo_without_photo(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.photo = []
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.mock_bot.get_state.return_value = "photo"
        # Act
        process_photo(mock_message)

        # Assert
        self.assertNotIn('photo_file_id', self.mock_data_dict) # Убедимся, что ничего не установилось
        self.mock_bot.set_state.assert_not_called()
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Пожалуйста, отправь фото (или нажми 'Пропустить'):", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler.assert_called_once_with(self.mock_bot.reply_to.return_value, process_photo)


    def test_skip_photo(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        # Act
        skip_photo(mock_call)

        # Assert
        self.assertEqual(self.mock_data_dict['photo_file_id'], None)
        self.mock_bot.set_state.assert_called_once_with(1, "reminder", 123)
        self.mock_bot.edit_message_text.assert_called_once_with("Фото пропущено.", 123, 456)
        self.mock_bot.send_message.assert_called_once_with(123, "Когда напомнить?", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler_by_chat_id.assert_called_once_with(123, reminder)


    def test_skip_description(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        # Act
        skip_description(mock_call)

        # Assert
        self.assertEqual(self.mock_data_dict['description'], '')
        self.mock_bot.set_state.assert_called_once_with(1, "photo", 123)
        self.mock_bot.edit_message_text.assert_called_once_with("Описание пропущено.", 123, 456)
        self.mock_bot.send_message.assert_called_once_with(123, "Прикрепи фото к описанию (или нажми 'Пропустить'):", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler_by_chat_id.assert_called_once_with(123, process_photo)

    @patch('bot.schedule_notification')
    @patch('bot.datetime') # Патчим класс datetime в bot.py
    def test_reminder_adds_deadline_and_schedules_notifications(self, mock_datetime_class, mock_schedule_notification): # mock_datetime_class теперь имитирует класс datetime
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "За 1 день"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadline_dt = TIMEZONE.localize(datetime(2025, 7, 1, 10, 0, 0))
        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 30, 9, 0, 0))
        mock_datetime_class.strptime = datetime.strptime # ЭТО КЛЮЧЕВОЕ ИЗМЕНЕНИЕ

        self.mock_data_dict = { # Используем mock_data_dict
            'title': 'Тестовый дедлайн',
            'date': deadline_dt,
            'description': 'Тестовое описание',
            'photo_file_id': 'photo_123',
            'user_id': 1
        }

        self.mock_bot.get_state.return_value = "reminder"
        # Act
        reminder(mock_message)

        # Assert
        self.cursor.execute("SELECT * FROM deadlines WHERE user_id = ?", (1,))
        added_deadline = self.cursor.fetchone()
        self.assertIsNotNone(added_deadline)
        self.assertEqual(added_deadline[2], 'Тестовый дедлайн')
        self.assertEqual(added_deadline[3], deadline_dt.strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(added_deadline[4], 'Тестовое описание')
        self.assertEqual(added_deadline[5], 'За 1 день')
        self.assertEqual(added_deadline[6], 'photo_123')
        self.assertEqual(added_deadline[7], 0)

        self.assertEqual(mock_schedule_notification.call_count, 2)

        call_args_due = mock_schedule_notification.call_args_list[0].kwargs
        self.assertEqual(call_args_due['user_id'], 1)
        self.assertEqual(call_args_due['title'], 'Тестовый дедлайн')
        self.assertEqual(call_args_due['date'], deadline_dt)
        self.assertEqual(call_args_due['photo_file_id'], 'photo_123')
        self.assertEqual(call_args_due['reminder_time'], deadline_dt)
        self.assertTrue(call_args_due['is_due'])

        call_args_reminder = mock_schedule_notification.call_args_list[1].kwargs
        self.assertEqual(call_args_reminder['user_id'], 1)
        self.assertEqual(call_args_reminder['title'], 'Тестовый дедлайн')
        self.assertEqual(call_args_reminder['date'], deadline_dt)
        self.assertEqual(call_args_reminder['photo_file_id'], 'photo_123')
        self.assertEqual(call_args_reminder['reminder_time'], deadline_dt - timedelta(days=1))
        self.assertFalse(call_args_reminder['is_due'])

        self.mock_bot.reply_to.assert_called_once_with(
            mock_message,
            f"Дедлайн '{self.mock_data_dict['title']}' успешно добавлен!", # Используем mock_data_dict
            reply_markup=main_menu()
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    @patch('bot.schedule_notification')
    @patch('bot.datetime') # Патчим класс datetime в bot.py
    def test_reminder_no_notification(self, mock_datetime_class, mock_schedule_notification): # mock_datetime_class теперь имитирует класс datetime
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "Без напоминания"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadline_dt = TIMEZONE.localize(datetime(2025, 7, 1, 10, 0, 0))
        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 30, 9, 0, 0))
        mock_datetime_class.strptime = datetime.strptime # ЭТО КЛЮЧЕВОЕ ИЗМЕНЕНИЕ

        self.mock_data_dict = { # Используем mock_data_dict
            'title': 'Дедлайн без напоминания',
            'date': deadline_dt,
            'description': 'Без описания',
            'photo_file_id': None,
            'user_id': 1
        }

        self.mock_bot.get_state.return_value = "reminder"
        # Act
        reminder(mock_message)

        # Assert
        self.assertEqual(mock_schedule_notification.call_count, 1)
        call_args_due = mock_schedule_notification.call_args_list[0].kwargs
        self.assertTrue(call_args_due['is_due'])

        self.mock_bot.reply_to.assert_called_once()
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    def test_reminder_invalid_input(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "Какой-то текст"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.mock_bot.get_state.return_value = "reminder"
        # Act
        reminder(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Пожалуйста, выбери один из предложенных вариантов напоминания:", reply_markup=unittest.mock.ANY)
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            self.mock_bot.reply_to.return_value, reminder
        )
        self.cursor.execute("SELECT * FROM deadlines WHERE user_id = ?", (1,))
        self.assertIsNone(self.cursor.fetchone())

    # --- Тесты для просмотра дедлайнов ---
    def test_view_deadlines_no_deadlines(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        # Act
        view_deadlines(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "У тебя нет дедлайнов.", reply_markup=main_menu())
        self.mock_bot.delete_state.assert_called_once_with(1, 123)


    def test_view_deadlines_with_deadlines(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.cursor.execute(
            "INSERT INTO deadlines (user_id, title, date, description, reminder, completed) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "Дедлайн 1", datetime(2025, 6, 15, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc 1", "За 1 час", 0)
        )
        self.cursor.execute(
            "INSERT INTO deadlines (user_id, title, date, description, reminder, completed) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "Дедлайн 2", datetime(2025, 6, 20, 15, 30, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc 2", "Без напоминания", 1)
        )
        self.conn.commit()

        # Act
        view_deadlines(mock_message)

        # Assert
        self.assertEqual(self.mock_bot.send_message.call_count, 3)

        self.mock_bot.send_message.assert_any_call(
            123,
            unittest.mock.ANY
        )
        self.mock_bot.send_message.assert_any_call(
            123,
            "Выбери номер дедлайна для изменения статуса:",
            reply_markup=unittest.mock.ANY
        )
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            unittest.mock.ANY,
            unittest.mock.ANY
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    # --- Тесты для выбора и действия с дедлайном ---
    def test_select_deadline_valid_choice(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "1"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadlines = [
            (1, 1, "Дедлайн 1", datetime(2025, 6, 15, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc 1", "За 1 час", 0)
        ]
        self.mock_data_dict = {"deadlines": deadlines} # Используем mock_data_dict

        # Act
        select_deadline(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(
            mock_message,
            f"Выбран дедлайн: Дедлайн 1 — {datetime(2025, 6, 15, 10, 0, 0).strftime('%d.%m.%Y %H:%M')}",
            reply_markup=unittest.mock.ANY
        )
        self.mock_bot.send_message.assert_called_once()
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            unittest.mock.ANY, handle_deadline_action
        )

    def test_select_deadline_invalid_choice(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "99"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadlines = [
            (1, 1, "Дедлайн 1", datetime(2025, 6, 15, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc 1", "За 1 час", 0)
        ]
        self.mock_data_dict = {"deadlines": deadlines} # Используем mock_data_dict

        # Act
        select_deadline(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Неверный номер. Попробуй снова:")
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            self.mock_bot.reply_to.return_value, select_deadline
        )

    def test_select_deadline_back_choice(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "Назад"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadlines = [
            (1, 1, "Дедлайн 1", datetime(2025, 6, 15, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc 1", "За 1 час", 0)
        ]
        self.mock_data_dict = {"deadlines": deadlines} # Используем mock_data_dict


        # Act
        select_deadline(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Вернулся в главное меню.", reply_markup=main_menu())
        self.mock_bot.delete_state.assert_called_once_with(1, 123)


    def test_handle_deadline_action_mark_completed(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "Отметить как выполненное"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadlines = [
            (101, 1, "Дедлайн для выполнения", datetime(2025, 6, 15, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Описание", "Нет", 0)
        ]
        self.mock_data_dict = { # Используем mock_data_dict
            "deadlines": deadlines,
            "selected_deadline_idx": 0
        }

        self.cursor.execute(
            "INSERT INTO deadlines (id, user_id, title, date, description, reminder, completed) VALUES (?, ?, ?, ?, ?, ?, ?)",
            deadlines[0]
        )
        self.conn.commit()

        # Act
        handle_deadline_action(mock_message)

        # Assert
        self.cursor.execute("SELECT completed FROM deadlines WHERE id = ?", (101,))
        updated_status = self.cursor.fetchone()[0]
        self.assertEqual(updated_status, 1)

        self.mock_bot.reply_to.assert_called_once_with(
            mock_message,
            "Дедлайн 'Дедлайн для выполнения' отмечен как выполненным ✅!",
            reply_markup=main_menu()
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)


    def test_handle_deadline_action_mark_uncompleted(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "Отметить как невыполненное"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadlines = [
            (102, 1, "Дедлайн для невыполнения", datetime(2025, 6, 15, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Описание", "Нет", 1)
        ]
        self.mock_data_dict = { # Используем mock_data_dict
            "deadlines": deadlines,
            "selected_deadline_idx": 0
        }

        self.cursor.execute(
            "INSERT INTO deadlines (id, user_id, title, date, description, reminder, completed) VALUES (?, ?, ?, ?, ?, ?, ?)",
            deadlines[0]
        )
        self.conn.commit()

        # Act
        handle_deadline_action(mock_message)

        # Assert
        self.cursor.execute("SELECT completed FROM deadlines WHERE id = ?", (102,))
        updated_status = self.cursor.fetchone()[0]
        self.assertEqual(updated_status, 0)

        self.mock_bot.reply_to.assert_called_once_with(
            mock_message,
            "Дедлайн 'Дедлайн для невыполнения' отмечен как невыполненным ⏳!",
            reply_markup=main_menu()
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    def test_handle_deadline_action_invalid_action(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "Неверное действие"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadlines = [
            (103, 1, "Тестовый дедлайн", datetime(2025, 6, 15, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Описание", "Нет", 0)
        ]
        self.mock_data_dict = { # Используем mock_data_dict
            "deadlines": deadlines,
            "selected_deadline_idx": 0
        }

        # Act
        handle_deadline_action(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(
            mock_message,
            "Пожалуйста, выбери одно из предложенных действий:",
            reply_markup=unittest.mock.ANY
        )
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            self.mock_bot.reply_to.return_value, handle_deadline_action
        )

    # --- Тесты для удаления дедлайна ---
    def test_delete_deadline_no_deadlines(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        # Act
        delete_deadline(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "У тебя нет дедлайнов для удаления.", reply_markup=main_menu())
        self.mock_bot.delete_state.assert_called_once_with(1, 123)


    def test_delete_deadline_with_deadlines_displays_options(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        self.cursor.execute(
            "INSERT INTO deadlines (user_id, title, date, completed) VALUES (?, ?, ?, ?)",
            (1, "Удалить дедлайн 1", datetime(2025, 7, 1, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), 0)
        )
        self.cursor.execute(
            "INSERT INTO deadlines (user_id, title, date, completed) VALUES (?, ?, ?, ?)",
            (1, "Удалить дедлайн 2", datetime(2025, 7, 2, 11, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), 1)
        )
        self.conn.commit()

        # Act
        delete_deadline(mock_message)

        # Assert
        self.mock_bot.set_state.assert_called_once_with(1, "delete_deadline", 123)
        # Проверяем, что deadlines были сохранены в mock_data_dict
        self.assertIn("deadlines", self.mock_data_dict)
        self.assertEqual(len(self.mock_data_dict["deadlines"]), 2)
        self.mock_bot.reply_to.assert_called_once()
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            unittest.mock.ANY, delete_choice
        )

    def test_delete_choice_valid_selection(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "1"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123
        mock_message.message_id = 456

        deadlines_data = [
            (1001, 1, "Удаляемый дедлайн", datetime(2025, 7, 1, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc", "Rem", 0)
        ]
        self.mock_data_dict = {"deadlines": deadlines_data} # Используем mock_data_dict

        # Act
        delete_choice(mock_message)

        # Assert
        self.assertEqual(self.mock_data_dict['selected_deadline_idx'], 0) # Проверяем, что индекс сохранен
        self.mock_bot.send_message.assert_called_once()
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            unittest.mock.ANY, handle_delete_confirmation
        )


    def test_delete_choice_cancel(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "Отмена"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        # Act
        delete_choice(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Удаление отменено.", reply_markup=main_menu())
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    def test_delete_choice_invalid_number(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.text = "999"
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        deadlines_data = [
            (1001, 1, "Дедлайн", datetime(2025, 7, 1, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc", "Rem", 0)
        ]
        self.mock_data_dict = {"deadlines": deadlines_data} # Используем mock_data_dict

        # Act
        delete_choice(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Неверный номер. Попробуй снова:")
        self.mock_bot.register_next_step_handler.assert_called_once_with(
            self.mock_bot.reply_to.return_value, delete_choice
        )

    def test_handle_delete_confirmation_confirm(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.data = "confirm_delete"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        deadline_to_delete = (1005, 1, "Дедлайн для удаления", datetime(2025, 7, 1, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc", "Rem", 0)
        self.mock_data_dict = { # Используем mock_data_dict
            "selected_deadline_idx": 0,
            "deadlines": [deadline_to_delete]
        }
        self.cursor.execute(
            "INSERT INTO deadlines (id, user_id, title, date, description, reminder, completed) VALUES (?, ?, ?, ?, ?, ?, ?)",
            deadline_to_delete
        )
        self.conn.commit()

        # Act
        handle_delete_confirmation(mock_call)

        # Assert
        self.cursor.execute("SELECT * FROM deadlines WHERE id = ?", (1005,))
        deleted_deadline = self.cursor.fetchone()
        self.assertIsNone(deleted_deadline)

        self.mock_bot.edit_message_text.assert_called_once_with(
            "Дедлайн 'Дедлайн для удаления' удалён ✅!", 123, 456
        )
        self.mock_bot.send_message.assert_called_once_with(
            123, "Выбери, что хочешь сделать:", reply_markup=main_menu()
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    def test_handle_delete_confirmation_cancel(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.data = "cancel_delete"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        # Act
        handle_delete_confirmation(mock_call)

        # Assert
        self.mock_bot.edit_message_text.assert_called_once_with("Удаление отменено.", 123, 456)
        self.mock_bot.send_message.assert_called_once_with(
            123, "Выбери, что хочешь сделать:", reply_markup=main_menu()
        )
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    def test_handle_delete_confirmation_clear(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.data = "clear_delete"
        mock_call.from_user.id = 1
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        deadlines_data = [
            (1001, 1, "Дедлайн 1", datetime(2025, 7, 1, 10, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc", "Rem", 0),
            (1002, 1, "Дедлайн 2", datetime(2025, 7, 2, 11, 0, 0).strftime("%Y-%m-%d %H:%M:%S"), "Desc", "Rem", 1)
        ]
        self.mock_data_dict = { # Используем mock_data_dict
            "selected_deadline_idx": 0,
            "deadlines": deadlines_data
        }

        # Act
        handle_delete_confirmation(mock_call)

        # Assert
        self.mock_bot.delete_message.assert_called_once_with(123, 456)
        self.mock_bot.send_message.assert_called_once_with(
            123, unittest.mock.ANY, reply_markup=unittest.mock.ANY
        )
        self.mock_bot.register_next_step_handler_by_chat_id.assert_called_once_with(123, delete_choice)


    # --- Тесты для техподдержки/FAQ ---
    def test_handle_support_displays_faq_keyboard(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.id = 123
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        # Act
        handle_support(mock_call)

        # Assert
        self.mock_bot.answer_callback_query.assert_called_once_with(mock_call.id)
        self.mock_bot.edit_message_text.assert_called_once_with(
            "📖 Часто задаваемые вопросы (FAQ):\nВыбери вопрос или напиши разработчикам:",
            123,
            456,
            reply_markup=faq_keyboard()
        )

    def test_handle_faq_add_deadline(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.id = 123
        mock_call.data = "faq_add_deadline"
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        # Act
        handle_faq(mock_call)

        # Assert
        self.mock_bot.answer_callback_query.assert_called_once_with(mock_call.id)
        self.mock_bot.edit_message_text.assert_called_once()
        args, kwargs = self.mock_bot.edit_message_text.call_args
        self.assertIn("Как добавить дедлайн?", args[0])
        self.assertEqual(args[1], 123)
        self.assertEqual(args[2], 456)
        self.assertEqual(kwargs['reply_markup'], faq_keyboard())

    def test_handle_contact_support(self):
        # Arrange
        mock_call = MagicMock()
        mock_call.id = 123
        mock_call.message.chat.id = 123
        mock_call.message.message_id = 456

        # Act
        handle_contact_support(mock_call)

        # Assert
        self.mock_bot.answer_callback_query.assert_called_once_with(mock_call.id)
        self.mock_bot.edit_message_text.assert_called_once_with(
            "Связаться с разработчиком: [@MILAVIA](https://t.me/MILAVIA)",
            123,
            456,
            parse_mode="Markdown"
        )

    # --- Тест для команды /cancel ---
    def test_cancel_command(self):
        # Arrange
        mock_message = MagicMock()
        mock_message.from_user.id = 1
        mock_message.chat.id = 123

        # Act
        cancel(mock_message)

        # Assert
        self.mock_bot.reply_to.assert_called_once_with(mock_message, "Действие отменено.", reply_markup=main_menu())
        self.mock_bot.delete_state.assert_called_once_with(1, 123)

    # --- Тесты для функций уведомлений ---
    @patch('bot.threading.Timer')
    @patch('bot.datetime') # Патчим класс datetime в bot.py
    def test_schedule_notification_future_time(self, mock_datetime_class, mock_timer): # Порядок аргументов важен!
        # Arrange
        user_id = 1
        title = "Тестовый дедлайн"
        date = TIMEZONE.localize(datetime(2025, 6, 16, 10, 0, 0))
        photo_file_id = "test_photo_id"
        reminder_time = TIMEZONE.localize(datetime(2025, 6, 16, 9, 0, 0))
        is_due = False

        # Мокируем datetime.now()
        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 15, 10, 0, 0))
        # Делаем так, чтобы strptime на патченном классе вызывал реальный datetime.strptime
        mock_datetime_class.strptime = datetime.strptime # ЭТО КЛЮЧЕВОЕ ИЗМЕНЕНИЕ

        # Act
        schedule_notification(user_id, title, date, photo_file_id, reminder_time, is_due)

        # Assert
        mock_timer.assert_called_once()
        args, kwargs = mock_timer.call_args
        self.assertGreater(args[0], 0)
        self.assertEqual(args[1], send_notification)
        self.assertEqual(args[2], (user_id, title, date, photo_file_id, is_due))

    @patch('bot.threading.Timer')
    @patch('bot.datetime') # Патчим класс datetime в bot.py
    def test_schedule_notification_past_time_not_scheduled(self, mock_datetime_class, mock_timer): # Порядок аргументов важен!
        # Arrange
        user_id = 1
        title = "Прошедший дедлайн"
        date = TIMEZONE.localize(datetime(2025, 6, 10, 10, 0, 0))
        photo_file_id = None
        reminder_time = TIMEZONE.localize(datetime(2025, 6, 9, 9, 0, 0))
        is_due = False

        # Мокируем datetime.now()
        mock_datetime_class.now.return_value = TIMEZONE.localize(datetime(2025, 6, 15, 10, 0, 0))
        # Делаем так, чтобы strptime на патченном классе вызывал реальный datetime.strptime
        mock_datetime_class.strptime = datetime.strptime # ЭТО КЛЮЧЕВОЕ ИЗМЕНЕНИЕ

        # Act
        schedule_notification(user_id, title, date, photo_file_id, reminder_time, is_due)

        # Assert
        mock_timer.assert_not_called()

    def test_send_notification_with_photo(self):
        # Arrange
        user_id = 123
        title = "Дедлайн с фото"
        date = TIMEZONE.localize(datetime(2025, 6, 15, 10, 0, 0))
        photo_file_id = "AgAD_Photo123"
        is_due = False

        # Act
        send_notification(user_id, title, date, photo_file_id, is_due)

        # Assert
        self.mock_bot.send_photo.assert_called_once_with(
            user_id,
            photo_file_id,
            caption=f"Напоминание: '{title}' скоро! Дата: {date.strftime('%d.%m.%Y %H:%M')}"
        )
        self.mock_bot.send_message.assert_not_called()

    def test_send_notification_without_photo(self):
        # Arrange
        user_id = 123
        title = "Дедлайн без фото"
        date = TIMEZONE.localize(datetime(2025, 6, 15, 10, 0, 0))
        photo_file_id = None
        is_due = True

        # Act
        send_notification(user_id, title, date, photo_file_id, is_due)

        # Assert
        self.mock_bot.send_message.assert_called_once_with(
            user_id,
            f"⏰ Дедлайн '{title}' наступил! Дата: {date.strftime('%d.%m.%Y %H:%M')}"
        )
        self.mock_bot.send_photo.assert_not_called()


if __name__ == '__main__':
    unittest.main()