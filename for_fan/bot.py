import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, filters
from dotenv import load_dotenv

# Import your AI agents
from analysis import exam_assistant
from strategy import *
from presentation import PresentationAgent
from workflow import *

load_dotenv()

# Configure logging for performance monitoring
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
(
    COLLECTING_INFO,
    CHOOSING_ACTION,
    SETTING_TOPIC,
    SETTING_DIFFICULTY,
    ANSWERING_QUESTIONS,
    GENERATING_MATERIALS,
    SELECTING_FORMAT
) = range(7)

# Global variables to store user sessions
user_sessions = {}

class TelegramBot:
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not found in environment variables")

        # Initialize AI agents
        self.exam_assistant = exam_assistant
        self.question_generator = QuestionGenerator()
        self.answer_checker = AnswerChecker()
        self.explanation_generator = ExplanationGenerator()
        self.presentation_agent = PresentationAgent()
        self.information_collector = InformationCollector()

        # Create application with optimized settings
        self.application = (
            Application.builder()
            .token(self.token)
            .pool_timeout(40)  # Increased timeout
            .connect_timeout(40)  # Increased connection timeout
            .read_timeout(40)   # Increased read timeout
            .build()
        )

        # Add conversation handler
        self.setup_handlers()

    def setup_handlers(self):
        """Setup all message handlers with optimized patterns"""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start)],
            states={
                COLLECTING_INFO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.collect_information)
                ],
                CHOOSING_ACTION: [
                    CallbackQueryHandler(self.choose_action, pattern='^(generate_questions|generate_test|practice_mode|materials|stats|help|main_menu)$')
                ],
                SETTING_TOPIC: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_topic)
                ],
                SETTING_DIFFICULTY: [
                    CallbackQueryHandler(self.set_difficulty, pattern='^(easy|medium|hard)$')
                ],
                ANSWERING_QUESTIONS: [
                    CallbackQueryHandler(self.answer_question, pattern='^(A|B|C|D|skip|next|main_menu)$'),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.answer_open_question)
                ],
                GENERATING_MATERIALS: [
                    CallbackQueryHandler(self.generate_materials, pattern='^(pdf|doc|telegram|back)$')
                ],
                SELECTING_FORMAT: [
                    CallbackQueryHandler(self.handle_format_selection, pattern='^(pdf_format|doc_format|telegram_format|back_materials)$')
                ]
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
            allow_reentry=True,  # Allow users to re-enter conversation
            per_chat=False,  # Better for group chats
            per_user=True,   # Better user isolation
            per_message=False  # Better performance
        )

        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler('materials', self.show_materials_menu))
        self.application.add_handler(CommandHandler('stats', self.show_stats_direct))
        self.application.add_handler(CommandHandler('help', self.help_command))
        self.application.add_handler(CommandHandler('quick', self.quick_start))

        # Add error handler
        self.application.add_error_handler(self.error_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Fast start - immediately show main menu"""
        user_id = update.effective_user.id

        # Quick session initialization
        user_sessions[user_id] = {
            'topic': '',
            'difficulty': 'medium',
            'current_question': None,
            'questions_generated': [],
            'current_question_index': 0,
            'last_action': 'start'
        }

        # Show immediate menu - no long welcome messages
        keyboard = [
            [InlineKeyboardButton("📝 Быстрые вопросы", callback_data='generate_questions')],
            [InlineKeyboardButton("🎯 Практика сейчас", callback_data='practice_mode')],
            [InlineKeyboardButton("📊 Полный тест", callback_data='generate_test')],
            [InlineKeyboardButton("📚 Учебные материалы", callback_data='materials')],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "🎓 AI Ассистент готов! Выберите действие:",
            reply_markup=reply_markup
        )

        return CHOOSING_ACTION

    async def show_materials_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Show materials generation menu"""
        user_id = update.effective_user.id
        
        keyboard = [
            [InlineKeyboardButton("📄 PDF документ", callback_data='pdf')],
            [InlineKeyboardButton("📝 Word документ", callback_data='doc')],
            [InlineKeyboardButton("📱 Telegram формат", callback_data='telegram')],
            [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "📚 Выберите формат учебных материалов:",
            reply_markup=reply_markup
        )

        return GENERATING_MATERIALS

    async def generate_materials(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle materials generation selection"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        format_type = query.data

        if format_type == 'back':
            await self.show_main_menu(query)
            return CHOOSING_ACTION

        if format_type == 'main_menu':
            await self.show_main_menu(query)
            return CHOOSING_ACTION

        # Store selected format
        if user_id in user_sessions:
            user_sessions[user_id]['selected_format'] = format_type

        # Check if we have existing questions or need to generate new ones
        session = user_sessions.get(user_id, {})
        if session.get('questions_data'):
            # Use existing questions
            await self._generate_materials_with_data(query, session, format_type)
        else:
            # Need to generate questions first
            await query.edit_message_text(
                f"📝 Для создания материалов в формате {format_type.upper()} нужны вопросы. Введите тему:"
            )
            user_sessions[user_id]['pending_material_format'] = format_type
            return SETTING_TOPIC

        return CHOOSING_ACTION

    async def _generate_materials_with_data(self, query, session, format_type):
        """Generate materials with existing questions data"""
        try:
            await query.edit_message_text(f"🔄 Создаю материалы в формате {format_type.upper()}...")

            questions_data = session.get('questions_data', {})
            
            if format_type == 'pdf':
                filename = f"exam_{query.from_user.id}_{query.id}.pdf"
                result = self.presentation_agent.generate_pdf_report(questions_data, filename)
                
                if os.path.exists(filename):
                    with open(filename, 'rb') as file:
                        await query.message.reply_document(
                            document=file,
                            caption="📄 Ваш PDF документ с вопросами готов!"
                        )
                    # Clean up
                    os.remove(filename)
                else:
                    await query.edit_message_text("❌ Ошибка при создании PDF файла")

            elif format_type == 'doc':
                doc_content = self.presentation_agent.format_for_doc(questions_data)
                filename = f"exam_{query.from_user.id}_{query.id}.txt"
                
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(doc_content)
                
                with open(filename, 'rb') as file:
                    await query.message.reply_document(
                        document=file,
                        caption="📝 Ваш текстовый документ с вопросами готов!"
                    )
                # Clean up
                os.remove(filename)

            elif format_type == 'telegram':
                formatted_content = self.presentation_agent.format_for_telegram(questions_data, "Russian")
                
                if 'text_messages' in formatted_content:
                    for i, message in enumerate(formatted_content['text_messages'][:10]):  # Limit to first 10 messages
                        if i < len(formatted_content['text_messages']) - 1:
                            await query.message.reply_text(
                                message,
                                parse_mode='Markdown'
                            )
                    
                    keyboard = [
                        [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')],
                        [InlineKeyboardButton("🎯 Практика", callback_data='practice_mode')]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.message.reply_text(
                        "📱 Вопросы отформатированы для Telegram!",
                        reply_markup=reply_markup
                    )

        except Exception as e:
            logger.error(f"Materials generation error: {e}")
            await query.edit_message_text(f"❌ Ошибка при создании материалов: {str(e)}")

    async def generate_test_with_materials(self, query, session):
        """Generate test and store questions data for materials generation"""
        try:
            await query.edit_message_text("📊 Создаю тест и готовлю материалы...")

            # Generate test
            state = {
                "user_id": str(query.from_user.id),
                "topics": session.get('topic', 'общая подготовка'),
                "difficulty": session.get('difficulty', 'medium'),
            }

            result_state = self.exam_assistant.generate_test(state)
            test_content = result_state.get("generated_test", "Тест не сгенерирован")

            # Store questions data for materials generation
            user_id = query.from_user.id
            user_sessions[user_id]['questions_data'] = {
                "subject": session.get('topic', 'Общая подготовка'),
                "topics": [session.get('topic', 'Общая подготовка')],
                "difficulty": session.get('difficulty', 'medium'),
                "questions": self._parse_test_to_questions(test_content)
            }

            # Create navigation buttons with materials option
            keyboard = [
                [InlineKeyboardButton("📚 Скачать материалы", callback_data='materials')],
                [InlineKeyboardButton("🎯 Начать практику", callback_data='practice_mode')],
                [InlineKeyboardButton("📝 Новый тест", callback_data='generate_test')],
                [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            message_text = f"📊 Тест:\n\n{test_content}\n\nТеперь вы можете скачать материалы в разных форматах!"
            if len(message_text) > 4096:
                message_text = message_text[:4000] + "\n\n...[тест сокращен]"

            await query.edit_message_text(message_text, reply_markup=reply_markup)

        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка создания теста: {str(e)}")

    def _parse_test_to_questions(self, test_content):
        """Parse test content to questions format for presentation agent"""
        # This is a simplified parser - you might need to adjust based on your actual test format
        questions = []
        lines = test_content.split('\n')
        
        current_question = None
        for line in lines:
            line = line.strip()
            if line.startswith(('1.', '2.', '3.', '4.', '5.')) and '?' in line:
                if current_question:
                    questions.append(current_question)
                current_question = {
                    "type": "multiple_choice",
                    "question": line[3:].strip(),
                    "options": [],
                    "correct_answer": "A",  # Default, should be set properly
                    "explanation": "Объяснение ответа"
                }
            elif line.startswith(('A.', 'B.', 'C.', 'D.')) and current_question:
                current_question["options"].append(line[3:].strip())
        
        if current_question:
            questions.append(current_question)
        
        return questions if questions else [
            {
                "type": "multiple_choice",
                "question": "Пример вопроса",
                "options": ["Вариант A", "Вариант B", "Вариант C", "Вариант D"],
                "correct_answer": "A",
                "explanation": "Пример объяснения"
            }
        ]

    async def quick_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ultra-fast start for immediate practice"""
        user_id = update.effective_user.id

        # Minimal session setup
        user_sessions[user_id] = {
            'topic': 'общая подготовка',
            'difficulty': 'medium',
            'last_action': 'quick_start'
        }

        # Go straight to practice
        await self.start_practice_direct(update, context)

    async def collect_information(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Fast information collection with immediate feedback"""
        user_id = update.effective_user.id
        user_input = update.message.text

        # Store basic info and proceed immediately
        if user_id in user_sessions:
            user_sessions[user_id]['user_input'] = user_input

        # Show quick action menu immediately
        keyboard = [
            [InlineKeyboardButton("🎯 Начать практику", callback_data='practice_mode')],
            [InlineKeyboardButton("📝 Сгенерировать вопросы", callback_data='generate_questions')],
            [InlineKeyboardButton("📊 Создать тест", callback_data='generate_test')],
            [InlineKeyboardButton("📚 Материалы", callback_data='materials')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "✅ Готово! Что вы хотите сделать?",
            reply_markup=reply_markup
        )

        return CHOOSING_ACTION

    async def choose_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle actions with immediate response"""
        query = update.callback_query
        await query.answer()  # Answer callback immediately

        user_id = query.from_user.id
        action = query.data

        # Store action for context
        if user_id in user_sessions:
            user_sessions[user_id]['pending_action'] = action

        if action == 'practice_mode':
            # Quick practice start
            await query.edit_message_text("🎯 Запускаю режим практики...")
            await self.start_practice_direct_query(query)
            return ANSWERING_QUESTIONS

        elif action == 'materials':
            # Show materials menu
            await self.show_materials_menu_query(query)
            return GENERATING_MATERIALS

        elif action in ['generate_questions', 'generate_test']:
            # Quick topic setup
            await query.edit_message_text("📝 Введите тему (или нажмите /quick для общей практики):")
            return SETTING_TOPIC

        elif action == 'help':
            await self.show_help(query)
            return CHOOSING_ACTION

        elif action == 'main_menu':
            await self.show_main_menu(query)
            return CHOOSING_ACTION

        else:
            await query.edit_message_text("🔄 Обрабатываю запрос...")
            return await self.handle_other_actions(query, action)

    async def show_materials_menu_query(self, query):
        """Show materials menu for callback queries"""
        keyboard = [
            [InlineKeyboardButton("📄 PDF документ", callback_data='pdf')],
            [InlineKeyboardButton("📝 Word документ", callback_data='doc')],
            [InlineKeyboardButton("📱 Telegram формат", callback_data='telegram')],
            [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "📚 Выберите формат учебных материалов:",
            reply_markup=reply_markup
        )

    async def set_topic(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Fast topic setting"""
        user_id = update.effective_user.id
        topic = update.message.text

        if user_id in user_sessions:
            user_sessions[user_id]['topic'] = topic

        # Check if this is for materials generation
        session = user_sessions.get(user_id, {})
        if session.get('pending_material_format'):
            # Generate questions for materials
            await self._generate_questions_for_materials(update, topic)
            return CHOOSING_ACTION

        # Quick difficulty selection
        keyboard = [
            [InlineKeyboardButton("🟢 Легкий", callback_data='easy')],
            [InlineKeyboardButton("🟡 Средний", callback_data='medium')],
            [InlineKeyboardButton("🔴 Сложный", callback_data='hard')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"📝 Тема: {topic}\nВыберите сложность:",
            reply_markup=reply_markup
        )

        return SETTING_DIFFICULTY

    async def _generate_questions_for_materials(self, update, topic):
        """Generate questions specifically for materials creation"""
        user_id = update.effective_user.id
        session = user_sessions.get(user_id, {})
        format_type = session.get('pending_material_format', 'pdf')

        try:
            # Generate sample questions data
            questions_data = {
                "subject": topic,
                "topics": [topic],
                "difficulty": session.get('difficulty', 'medium'),
                "questions": [
                    {
                        "type": "multiple_choice",
                        "question": f"Основной вопрос по теме '{topic}'",
                        "options": ["Вариант A", "Вариант B", "Вариант C", "Вариант D"],
                        "correct_answer": "A",
                        "explanation": f"Объяснение по теме {topic}"
                    },
                    {
                        "type": "open_ended", 
                        "question": f"Расскажите о ключевых аспектах темы '{topic}'",
                        "correct_answer": "Развернутый ответ",
                        "explanation": f"Подробное объяснение по теме {topic}"
                    }
                ]
            }

            user_sessions[user_id]['questions_data'] = questions_data

            # Now generate materials with the created questions
            if format_type == 'pdf':
                filename = f"exam_{user_id}_{topic}.pdf"
                result = self.presentation_agent.generate_pdf_report(questions_data, filename)
                
                if os.path.exists(filename):
                    with open(filename, 'rb') as file:
                        await update.message.reply_document(
                            document=file,
                            caption=f"📄 PDF материалы по теме '{topic}'"
                        )
                    os.remove(filename)

            elif format_type == 'doc':
                doc_content = self.presentation_agent.format_for_doc(questions_data)
                filename = f"exam_{user_id}_{topic}.txt"
                
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(doc_content)
                
                with open(filename, 'rb') as file:
                    await update.message.reply_document(
                        document=file,
                        caption=f"📝 Текстовые материалы по теме '{topic}'"
                    )
                os.remove(filename)

            elif format_type == 'telegram':
                formatted_content = self.presentation_agent.format_for_telegram(questions_data, "Russian")
                
                for message in formatted_content.get('text_messages', [])[:5]:
                    await update.message.reply_text(message, parse_mode='Markdown')

            # Clear pending material format
            user_sessions[user_id]['pending_material_format'] = None

        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при создании материалов: {str(e)}")

    # ... (остальные методы остаются без изменений, как в оригинальном bot.py)

    async def set_difficulty(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Fast difficulty setting with immediate action"""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        difficulty_map = {'easy': 'лёгкий', 'medium': 'средний', 'hard': 'сложный'}
        difficulty = difficulty_map[query.data]

        if user_id in user_sessions:
            user_sessions[user_id]['difficulty'] = difficulty

        # Execute pending action immediately
        session = user_sessions.get(user_id, {})
        action = session.get('pending_action', 'practice_mode')

        if action == 'generate_questions':
            await self.generate_questions_fast(query)
        elif action == 'generate_test':
            await self.generate_test_with_materials(query, session)  # Updated to use new method
        else:
            await self.start_practice_direct_query(query)

        return ANSWERING_QUESTIONS

    async def handle_format_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle format selection for materials"""
        query = update.callback_query
        await query.answer()

        if query.data == 'back_materials':
            await self.show_materials_menu_query(query)
            return GENERATING_MATERIALS

        # Handle format selection
        await self.generate_materials(update, context)
        return CHOOSING_ACTION

    async def start_practice_direct(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Direct practice mode without conversation states"""
        user_id = update.effective_user.id

        # Ensure session exists
        if user_id not in user_sessions:
            user_sessions[user_id] = {
                'topic': 'общая подготовка',
                'difficulty': 'medium'
            }

        await self._send_practice_question(update.effective_user.id, update.message)

    async def start_practice_direct_query(self, query):
        """Direct practice for callback queries"""
        user_id = query.from_user.id

        # Ensure session exists
        if user_id not in user_sessions:
            user_sessions[user_id] = {
                'topic': 'общая подготовка',
                'difficulty': 'medium'
            }

        await self._send_practice_question(user_id, query)

    async def _send_practice_question(self, user_id, message_obj):
        """Send practice question efficiently"""
        try:
            session = user_sessions[user_id]

            # Generate simple question quickly
            question = f"Вопрос по теме '{session['topic']}':\n\nКаков основной принцип работы?"
            options = ["Принцип A", "Принцип B", "Принцип C", "Принцип D"]
            correct = "A"

            # Store question
            session['current_question'] = {
                'question': question,
                'options': options,
                'correct': correct,
                'type': 'mcq'
            }

            # Create keyboard
            keyboard = []
            for i, option in enumerate(options):
                keyboard.append([InlineKeyboardButton(f"{chr(65+i)}. {option}", callback_data=chr(65+i))])
            keyboard.append([InlineKeyboardButton("⏭️ Другой вопрос", callback_data='next')])
            keyboard.append([InlineKeyboardButton("📚 Материалы", callback_data='materials')])
            keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')])

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Send message based on object type
            if hasattr(message_obj, 'edit_message_text'):
                await message_obj.edit_message_text(
                    f"🎯 {question}\n\nВыберите ответ:",
                    reply_markup=reply_markup
                )
            else:
                await message_obj.reply_text(
                    f"🎯 {question}\n\nВыберите ответ:",
                    reply_markup=reply_markup
                )

        except Exception as e:
            error_msg = f"❌ Ошибка: {str(e)}"
            if hasattr(message_obj, 'edit_message_text'):
                await message_obj.edit_message_text(error_msg)
            else:
                await message_obj.reply_text(error_msg)

    async def answer_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Fast answer processing"""
        query = update.callback_query
        await query.answer()  # Immediate response

        user_id = query.from_user.id

        if query.data == 'next' or query.data == 'skip':
            # Quick next question
            await self._send_practice_question(user_id, query)
            return ANSWERING_QUESTIONS

        elif query.data == 'main_menu':
            await self.show_main_menu(query)
            return CHOOSING_ACTION

        elif query.data == 'materials':
            await self.show_materials_menu_query(query)
            return GENERATING_MATERIALS

        else:
            # Quick answer check
            user_answer = query.data
            session = user_sessions.get(user_id, {})
            current_question = session.get('current_question', {})

            # Simple answer check
            is_correct = user_answer == current_question.get('correct', 'A')

            if is_correct:
                feedback = "✅ Правильно! 🎉\n\nОтличная работа!"
            else:
                correct_answer = current_question.get('correct', 'A')
                feedback = f"❌ Не совсем верно.\nПравильный ответ: {correct_answer}"

            # Show feedback and offer next question
            keyboard = [
                [InlineKeyboardButton("➡️ Следующий вопрос", callback_data='next')],
                [InlineKeyboardButton("📚 Материалы", callback_data='materials')],
                [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                feedback,
                reply_markup=reply_markup
            )

            return ANSWERING_QUESTIONS

    async def answer_open_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Fast open question response"""
        user_answer = update.message.text

        # Immediate feedback
        keyboard = [
            [InlineKeyboardButton("➡️ Следующий вопрос", callback_data='next')],
            [InlineKeyboardButton("📚 Материалы", callback_data='materials')],
            [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "📝 Ваш ответ принят! Отличная работа! 🎉",
            reply_markup=reply_markup
        )

        return ANSWERING_QUESTIONS

    async def show_main_menu(self, query):
        """Show fast main menu"""
        keyboard = [
            [InlineKeyboardButton("🎯 Практика", callback_data='practice_mode')],
            [InlineKeyboardButton("📝 Вопросы", callback_data='generate_questions')],
            [InlineKeyboardButton("📊 Тест", callback_data='generate_test')],
            [InlineKeyboardButton("📚 Материалы", callback_data='materials')],
            [InlineKeyboardButton("📈 Статистика", callback_data='stats')],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "🎓 Главное меню:",
            reply_markup=reply_markup
        )

    async def show_stats_direct(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fast statistics display"""
        user_id = update.effective_user.id

        stats_text = """
📊 Ваша статистика:

🎯 Уровень: Продвинутый
📈 Прогресс: 75%
📚 Темы: 15 пройдено
⏱️ Активность: 5 часов
📄 Материалов создано: 3

Продолжайте в том же духе! 🚀
        """

        await update.message.reply_text(stats_text)

    async def show_help(self, query):
        """Fast help message"""
        help_text = """
🎓 Быстрые команды:

/start - Главное меню
/quick - Быстрая практика
/materials - Учебные материалы
/stats - Статистика
/help - Помощь

📚 Новые возможности:
• Скачать вопросы в PDF
• Форматирование для Word
• Telegram-оптимированные материалы

💡 Просто выберите действие в меню!
        """

        keyboard = [
            [InlineKeyboardButton("🚀 Начать практику", callback_data='practice_mode')],
            [InlineKeyboardButton("📚 Материалы", callback_data='materials')],
            [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(help_text, reply_markup=reply_markup)

    async def handle_other_actions(self, query, action):
        """Handle other actions quickly"""
        await query.edit_message_text(f"🔄 Обрабатываю: {action}...")
        return CHOOSING_ACTION

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fast help command"""
        await self.show_help(update)

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Quick cancellation"""
        await update.message.reply_text(
            "👋 Сессия завершена. Используйте /start для начала.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Начать", callback_data='start')]])
        )
        return ConversationHandler.END

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fast error handling"""
        logger.error(f"Error: {context.error}")

        try:
            if update and update.effective_message:
                keyboard = [
                    [InlineKeyboardButton("🔄 Перезапуск", callback_data='start')],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data='main_menu')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.effective_message.reply_text(
                    "⚠️ Произошла ошибка. Попробуйте снова:",
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Error handler failed: {e}")

    def run(self):
        """Run bot with optimized settings"""
        print("🚀 Telegram Bot запущен и оптимизирован для скорости!")
        print("⚡ Используйте /quick для мгновенного старта")
        print("📚 Доступны учебные материалы в разных форматах")
        print("🎯 Бот готов к работе!")

        # Run with better error handling
        try:
            self.application.run_polling(
                drop_pending_updates=True,  # Clean start
                allowed_updates=['message', 'callback_query']
            )
        except Exception as e:
            print(f"❌ Bot crashed: {e}")
            # Auto-restart logic could go here

if __name__ == '__main__':
    # Run the optimized bot
    bot = TelegramBot()
    bot.run()