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

    async def send_answer_statistics(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        username: str,
        question: str,
        user_answer: str,
        is_correct: bool,
        topic_title: str,
    ):
        """Отправляет статистику ответа администратору"""
        status = "✅ Правильно" if is_correct else "❌ Неправильно"
        message = (
            f"📊 Новый ответ\n\n"
            f"👤 Пользователь: {username} (ID: {user_id})\n"
            f"📚 Тема: {topic_title}\n"
            f"❓ Вопрос: {question}\n"
            f"📝 Ответ: {user_answer}\n"
            f"📌 Статус: {status}"
        )
        try:
            await context.bot.send_message(chat_id=self.admin_id, text=message)
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

        if query.data == "new_test":
            welcome_text = "Выберите тему теста:"
            await query.edit_message_text(
                welcome_text, reply_markup=self.get_topics_keyboard()
            )
            return

        if query.data.startswith("topic_"):
            # Начало теста по выбранной теме
            topic_id = int(query.data.replace("topic_", ""))
            user_id = query.from_user.id

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
            }

            # Показываем первый вопрос
            await self.show_question(query.message, user_id)

        elif query.data.startswith("answer_"):
            # Обработка ответа на вопрос
            user_id = query.from_user.id
            username = query.from_user.username or f"User{user_id}"
            answer_index = int(query.data.replace("answer_", ""))

            if user_id not in self.user_states:
                await query.edit_message_text("Произошла ошибка. Начните тест заново.")
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

            await self.send_answer_statistics(
                context,
                user_id,
                username,
                current_question["text"],
                user_answer,
                is_correct,
                topic_title,
            )

            if is_correct:
                state["correct_answers"] += 1

            # Переходим к следующему вопросу или показываем результаты
            state["current_question"] += 1
            if state["current_question"] >= len(state["questions"]):
                await self.show_results(query.message, user_id)
            else:
                await self.show_question(query.message, user_id)

    async def show_question(self, message, user_id):
        """Показывает текущий вопрос теста"""
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

        keyboard = []
        for i, option in enumerate(question["options"]):
            keyboard.append(
                [InlineKeyboardButton(option["text"], callback_data=f"answer_{i}")]
            )

        question_text = (
            f"Вопрос {state['current_question'] + 1} из {len(state['questions'])}:\n\n"
            f"{question['text']}"
        )

        await message.edit_text(
            question_text, reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def show_results(self, message, user_id):
        """Показывает результаты теста"""
        state = self.user_states[user_id]
        total_questions = len(state["questions"])
        correct_answers = state["correct_answers"]
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

        await message.edit_text(
            result_text, reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Очищаем состояние пользователя
        del self.user_states[user_id]

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
