from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from database import init_db, Topic, Question, QuestionOption
import os
from dotenv import load_dotenv
import logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class TestBot:
    def __init__(self, token: str, admin_id: str):
        self.token = token
        self.admin_id = admin_id
        self.db = init_db()
        self.user_states = {}  # Хранит состояние тестирования пользователей
        logger.info("Бот инициализирован")
        self._init_demo_data()

    def get_topics_keyboard(self):
        """Создает клавиатуру с темами тестов"""
        topics = self.db.query(Topic).all()
        keyboard = []
        for topic in topics:
            keyboard.append(
                [InlineKeyboardButton(topic.title, callback_data=f"topic_{topic.id}")]
            )
        return InlineKeyboardMarkup(keyboard)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        welcome_text = (
            "👋 Добро пожаловать в бот для тестирования!\n\n" "Выберите тему теста:"
        )
        await update.message.reply_text(
            welcome_text, reply_markup=self.get_topics_keyboard()
        )

    async def send_test_results(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        username: str,
        topic_title: str,
    ):
        """Отправляет итоговую статистику теста администратору"""
        state = self.user_states[user_id]

        # Подготовка заголовка сообщения
        total_questions = len(state["questions"])
        correct_answers = state["correct_answers"]
        score = (correct_answers / total_questions) * 100

        message = (
            f"📊 Результаты теста\n\n"
            f"👤 Пользователь: {username} (ID: {user_id})\n"
            f"📚 Тема: {topic_title}\n"
            f"✨ Общий результат: {score:.1f}%\n"
            f"📝 Правильных ответов: {correct_answers}/{total_questions}\n\n"
            f"Детальные результаты:\n"
        )

        # Добавление информации по каждому вопросу
        for i, answer in enumerate(state["answers"], 1):
            status = "✅" if answer["is_correct"] else "❌"
            message += f"\n{i}. {status} Вопрос: {answer['question']}\n"

            if answer["is_correct"]:
                message += f"    Ответ: {answer['user_answer']}\n"
            else:
                message += f"   Ответ ученика: {answer['user_answer']}\n"
                message += f"   ✳️ Правильный ответ: {answer['correct_answer']} ✳️\n"

        try:
            await context.bot.send_message(chat_id=self.admin_id, text=message)
            logger.info(f"Статистика отправлена администратору для пользователя {user_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки статистики: {e}")

    @staticmethod
    def generate_progress_bar(current, total, length=10):
        """Генерирует прогресс-бар для отображения результатов"""
        filled = int(length * (current / total))
        empty = length - filled
        return "█" * filled + "░" * empty

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        if query.data == "new_test":
            # Важный момент: мы не полагаемся на состояние пользователя 
            # при выборе нового теста, просто показываем меню
            welcome_text = "Выберите тему теста:"
            await query.edit_message_text(
                welcome_text, reply_markup=self.get_topics_keyboard()
            )
            return

        if query.data.startswith("topic_"):
            # Начало теста по выбранной теме
            topic_id = int(query.data.replace("topic_", ""))

            # Получаем вопросы для темы
            questions = (
                self.db.query(Question).filter(Question.topic_id == topic_id).all()
            )

            if not questions:
                await query.edit_message_text(
                    "К сожалению, для этой темы пока нет вопросов."
                )
                return

            # Подготовка данных для теста
            questions_data = []
            for question in questions:
                options = (
                    self.db.query(QuestionOption)
                    .filter(QuestionOption.question_id == question.id)
                    .all()
                )
                options_data = [
                    {"text": opt.text, "is_correct": opt.is_correct} for opt in options
                ]
                questions_data.append({"text": question.text, "options": options_data})

            # Сохраняем состояние теста пользователя
            self.user_states[user_id] = {
                "questions": questions_data,
                "current_question": 0,
                "correct_answers": 0,
                "topic_id": topic_id,
                "answers": [],
            }

            # Показываем первый вопрос
            await self.show_question(query.message, user_id)

        elif query.data.startswith("answer_"):
            # Обработка ответа на вопрос
            username = query.from_user.username or f"User{user_id}"
            answer_index = int(query.data.replace("answer_", ""))

            if user_id not in self.user_states:
                logger.error(f"Состояние пользователя {user_id} не найдено")
                await query.edit_message_text(
                    "Произошла ошибка. Начните тест заново.", 
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("Начать заново", callback_data="new_test")
                    ]])
                )
                return

            state = self.user_states[user_id]
            current_question = state["questions"][state["current_question"]]

            # Получаем информацию о теме
            topic_id = state.get("topic_id")
            topic = self.db.query(Topic).filter(Topic.id == topic_id).first()
            topic_title = topic.title if topic else "Неизвестная тема"

            # Проверяем правильность ответа
            user_answer = current_question["options"][answer_index]["text"]
            is_correct = current_question["options"][answer_index]["is_correct"]

            correct_answer_text = ""
            for option in current_question["options"]:
                if option["is_correct"]:
                    correct_answer_text = option["text"]
                    break

            state["answers"].append(
                {
                    "question": current_question["text"],
                    "user_answer": user_answer,
                    "is_correct": is_correct,
                    "correct_answer": correct_answer_text,
                }
            )

            if is_correct:
                state["correct_answers"] += 1

            # Переходим к следующему вопросу или показываем результаты
            state["current_question"] += 1
            if state["current_question"] >= len(state["questions"]):
                # Сохраним копию данных перед очисткой состояния
                result_data = {
                    "total_questions": len(state["questions"]),
                    "correct_answers": state["correct_answers"],
                    "topic_title": topic_title
                }
                
                # Отправляем результаты администратору
                await self.send_test_results(context, user_id, username, topic_title)
                
                # Показываем результаты пользователю и очищаем состояние
                await self.show_results(query.message, user_id, result_data)
            else:
                await self.show_question(query.message, user_id)

    async def show_question(self, message, user_id):
        """Показывает текущий вопрос теста"""
        if user_id not in self.user_states:
            logger.error(f"Состояние пользователя {user_id} не найдено при показе вопроса")
            await message.edit_text(
                "Произошла ошибка. Начните тест заново.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Начать заново", callback_data="new_test")
                ]])
            )
            return
            
        state = self.user_states[user_id]
        question = state["questions"][state["current_question"]]

        if "topic_id" not in state:
            topic = (
                self.db.query(Topic)
                .filter(Topic.questions.any(text=question["text"]))
                .first()
            )
            if topic:
                state["topic_id"] = topic.id

        # Создаем текст вопроса с вариантами ответов
        question_text = (
            f"Вопрос {state['current_question'] + 1} из {len(state['questions'])}:\n\n"
            f"{question['text']}\n\n"
            f"Варианты ответов:\n"
        )
        
        # Добавляем варианты с буквами A, B, C, D
        letters = ['A', 'B', 'C', 'D']
        for i, option in enumerate(question["options"]):
            question_text += f"{letters[i]}. {option['text']}\n"

        # Создаем кнопки только с буквами
        keyboard = []
        for i in range(len(question["options"])):
            keyboard.append(
                [InlineKeyboardButton(letters[i], callback_data=f"answer_{i}")]
            )

        try:
            await message.edit_text(
                question_text, reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Ошибка при показе вопроса: {e}")
            await message.edit_text(
                "Произошла ошибка при показе вопроса. Начните тест заново.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Начать заново", callback_data="new_test")
                ]])
            )

    async def show_results(self, message, user_id, result_data=None):
        """Показывает результаты теста"""
        if result_data is None:
            if user_id not in self.user_states:
                logger.error(f"Состояние пользователя {user_id} не найдено при показе результатов")
                await message.edit_text(
                    "Произошла ошибка. Начните тест заново.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("Начать заново", callback_data="new_test")
                    ]])
                )
                return
                
            state = self.user_states[user_id]
            total_questions = len(state["questions"])
            correct_answers = state["correct_answers"]
        else:
            total_questions = result_data["total_questions"]
            correct_answers = result_data["correct_answers"]
            
        score = (correct_answers / total_questions) * 100
        progress_bar = self.generate_progress_bar(correct_answers, total_questions)

        result_text = (
            "🎯 Тест завершен!\n\n"
            f"Прогресс: {progress_bar}\n"
            f"Правильных ответов: {correct_answers} из {total_questions}\n"
            f"Ваш результат: {score:.1f}%\n\n"
        )

        keyboard = [
            [InlineKeyboardButton("📝 Выбрать другой тест", callback_data="new_test")]
        ]

        try:
            await message.edit_text(
                result_text, reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"Результаты показаны пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при показе результатов: {e}")
            await message.edit_text(
                "Произошла ошибка при показе результатов. Начните тест заново.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Начать заново", callback_data="new_test")
                ]])
            )

        # Очищаем состояние пользователя
        if user_id in self.user_states:
            del self.user_states[user_id]
            logger.info(f"Состояние пользователя {user_id} очищено")

    def _init_demo_data(self):
        """Инициализация демонстрационных данных"""
        if not self.db.query(Topic).first():
            from demo_data import DEMO_DATA

            for topic_data in DEMO_DATA["topics"]:
                topic = Topic(title=topic_data["title"])
                self.db.add(topic)
                self.db.commit()

                for question_data in topic_data["questions"]:
                    question = Question(topic_id=topic.id, text=question_data["text"])
                    self.db.add(question)
                    self.db.commit()

                    for option_data in question_data["options"]:
                        option = QuestionOption(
                            question_id=question.id,
                            text=option_data["text"],
                            is_correct=option_data["is_correct"],
                        )
                        self.db.add(option)
                    self.db.commit()


def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    admin_id = os.getenv("ADMIN_TELEGRAM_ID")

    if not token:
        raise ValueError("Не найден TELEGRAM_BOT_TOKEN в переменных окружения")

    if not admin_id:
        raise ValueError("Не найден ADMIN_TELEGRAM_ID в переменных окружения")

    bot = TestBot(token, admin_id)
    application = Application.builder().token(bot.token).build()

    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CallbackQueryHandler(bot.button_handler))

    print("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()
