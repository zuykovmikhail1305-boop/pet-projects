import os
import requests
from bs4 import BeautifulSoup
from langchain_gigachat import GigaChat
from langchain_core.messages import HumanMessage
from langchain.prompts import PromptTemplate
from pydantic import BaseModel, Field
from datetime import datetime
import json
from typing import Dict, Any, List, Optional
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
import re
import telebot

# Вставь сюда свой токен, полученный от @BotFather.
BOT_TOKEN = '8284495790:AAEpXS4x7fUvV2n6OYmukPfDwc3jNjacAu4'
bot = telebot.TeleBot(BOT_TOKEN)

# ======================
# Настройки
# ======================

API_KEY = "MDE5OWRlNGQtODZmMy03NTBiLWFhMGMtOTg4OTZkMWVhZjRjOjgwYjM4OTc3LWYxMTktNDM2YS05NDU1LTU0YTM2ZmE0YmExZg=="

# Путь к файлу данных — в той же директории, где лежит скрипт
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "requests.json")

llm = GigaChat(
    credentials=API_KEY,
    scope="GIGACHAT_API_PERS",
    auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",  # убран пробел в конце
    verify_ssl_certs=False
)

# ======================
# Модели данных
# ======================

class SubjectAnalysis(BaseModel):
    date: str = Field(description="Дата в формате ГГГГ-ММ-ДД")
    subject: str = Field(description="Предмет")
    original_link: str = Field(description="Ссылка")

class AgentState(TypedDict):
    user_input: str
    intent: str  # "classify", "retrieve", "unknown"
    url: Optional[str]
    subject_filter: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    result: Dict[str, Any]

# ======================
# Вспомогательные функции
# ======================

def write_to_json_file( dict[str, Any], filename: str = DATA_FILE) -> None:
    try:
        # Создаём папку, если вдруг путь содержит подкаталоги (на всякий случай)
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing = []
        if not isinstance(existing, list):
            existing = []
        existing.append(data)
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ОШИБКА ЗАПИСИ В ФАЙЛ {filename}]: {e}")

def load_saved_data(filename: str = DATA_FILE) -> List[Dict[str, Any]]:
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ФАЙЛ НЕ НАЙДЕН ИЛИ ПОВРЕЖДЁН {filename}]: {e}")
        return []

def truncate_by_characters(text: str, max_chars: int = 1000) -> str:
    return text[:max_chars] if len(text) > max_chars else text

def get_text_from_url(url: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return truncate_by_characters(" ".join(text.split()), 1000)
    except Exception as e:
        return f"[Ошибка загрузки страницы: {e}]"

# ======================
# Промпты
# ======================

CLASSIFY_PROMPT_TEMPLATE = (
    "Ты — ассистент для анализа учебных материалов. "
    "Проанализируй содержимое веб-страницы и определи, к какому учебному курсу она относится.\n\n"
    
    "КРИТЕРИИ ОТНЕСЕНИЯ К ПРЕДМЕТАМ:\n"
    "1. **Численные методы**: \n"
    "   - Упоминания: численные методы, вычисления, аппроксимация, интерполяция, дифференциальные уравнения\n"
    "   - Алгоритмы: метод Ньютона, метод Гаусса, Рунге-Кутта, конечные разности\n"
    "   - Темы: математическое моделирование, вычислительная математика, погрешности\n\n"
    
    "2. **Компьютерные сети**: \n"
    "   - Упоминания: сетевые протоколы, TCP/IP, маршрутизация, LAN/WAN, OSI model\n"
    "   - Оборудование: роутеры, коммутаторы, серверы, кабели\n"
    "   - Темы: интернет-технологии, передача данных, сетевые архитектуры\n\n"
    
    "3. **Программирование на Python**: \n"
    "   - Упоминания: Python, код, скрипты, библиотеки (NumPy, Pandas), функции, классы\n"
    "   - Темы: разработка ПО, алгоритмы программирования, синтаксис Python\n"
    "   - Примеры: 'import python', 'def function', 'class MyClass'\n\n"
    
    "4. **Физика**: \n"
    "   - Упоминания: механика, термодинамика, электричество, магнетизм, квантовая физика\n"
    "   - Формулы: F=ma, E=mc², законы Ньютона, уравнения Максвелла\n"
    "   - Темы: физические явления, эксперименты, законы природы\n\n"
    
    "ИНСТРУКЦИЯ ДЛЯ АНАЛИЗА:\n"
    "1. Внимательно изучи текст страницы\n"
    "2. Определи основные темы и ключевые слова\n"
    "3. Сопоставь с критериями выше\n"
    "4. Если текст не подходит ни под один критерий - верни 'Не относится ни к одному из курсов'\n"
    "5. Выбери ТОЛЬКО ОДИН наиболее подходящий предмет\n\n"
    
    "ФОРМАТ ОТВЕТА (строго JSON):\n"
    "{{\n"
    "  \"date\": \"2025-10-15\",\n"
    "  \"subject\": \"название предмета\",\n"
    "  \"original_link\": \"исходная ссылка\"\n"
    "}}\n\n"
    
    "Текст для анализа:\n"
    "{content}\n\n"
    "Ссылка: {url}"
)

classify_prompt = PromptTemplate(template=CLASSIFY_PROMPT_TEMPLATE, input_variables=["content", "url"])

RETRIEVE_PROMPT_TEMPLATE = (
    "Ты - ассистент для поиска учебных материалов. Проанализируй запрос пользователя и извлеки параметры.\n\n"
    
    "ПРАВИЛА ИЗВЛЕЧЕНИЯ:\n"
    "1. **subject**: Должен строго соответствовать одному из: \n"
    "   - 'Численные методы'\n"
    "   - 'Компьютерные сети' \n"
    "   - 'Программирование на python'\n"
    "   - 'Физика'\n"
    "   - 'все' (если предмет не указан или указаны несколько)\n\n"
    
    "2. **Даты**:\n"
    "   - Если указан месяц (например 'октябрь'):\n"
    "     * start_date: первый день месяца в текущем году (2025-10-01)\n"
    "     * end_date: последний день месяца (2025-10-31)\n"
    "   - Если указан период: преобразуй в соответствующие даты\n"
    "   - Если дата не указана: используй start_date='2000-01-01', end_date=сегодня\n\n"
    
    "3. **Анализ запроса**:\n"
    "   - 'материалы по физике' → subject: 'Физика'\n"
    "   - 'ссылки за октябрь' → subject: 'все', start_date: '2025-10-01', end_date: '2025-10-31'\n"
    "   - 'программирование python за последний месяц' → subject: 'Программирование на python', соответствующие даты\n\n"
    
    "Сегодняшняя дата: {today}\n"
    "Запрос пользователя: {query}\n\n"
    
    "Ответь строго в формате JSON:\n"
    "{{\"subject\": \"...\", \"start_date\": \"...\", \"end_date\": \"...\"}}"
)

# ======================
# Узлы графа
# ======================

def detect_intent(state: AgentState) -> str:
    user_input = state["user_input"].strip()
    if re.match(r"^https?://", user_input):
        return "classify"
    elif any(kw in user_input.lower() for kw in ["материал", "ссылк", "покажи", "дай", "по предмету", "за"]):
        return "retrieve"
    else:
        return "unknown"

def classify_node(state: AgentState) -> AgentState:
    url = state["user_input"].strip()
    content = get_text_from_url(url)
    if content.startswith("[Ошибка"):
        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "subject": "Ошибка загрузки",
            "original_link": url
        }
    else:
        prompt_text = classify_prompt.format(content=content, url=url)
        response = llm.invoke([HumanMessage(content=prompt_text)])
        try:
            text = response.content.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(text[start:end])
                result = {
                    "date": data.get("date", datetime.now().strftime("%Y-%m-%d")),
                    "subject": data.get("subject", "Не относится ни к одному из курсов"),
                    "original_link": data.get("original_link", url)
                }
            else:
                raise ValueError("No valid JSON found")
        except Exception as e:
            print(f"[Ошибка парсинга LLM в classify]: {e}")
            result = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "subject": "Не относится ни к одному из курсов",
                "original_link": url
            }
    write_to_json_file(result, filename=DATA_FILE)
    return {"result": result}

def retrieve_node(state: AgentState) -> AgentState:
    today = datetime.now().strftime("%Y-%m-%d")
    prompt_templ = PromptTemplate(template=RETRIEVE_PROMPT_TEMPLATE, input_variables=["query", "today"])
    prompt_text = prompt_templ.format(query=state["user_input"], today=today)
    response = llm.invoke([HumanMessage(content=prompt_text)])
    
    try:
        text = response.content.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            params = json.loads(text[start:end])
            subject = params.get("subject", "все")
            start_date = params.get("start_date", "2000-01-01")
            end_date = params.get("end_date", today)
        else:
            raise ValueError("No JSON in retrieve response")
    except Exception as e:
        print(f"[Ошибка парсинга LLM в retrieve]: {e}")
        subject, start_date, end_date = "все", "2000-01-01", today

    all_data = load_saved_data(filename=DATA_FILE)
    filtered = []
    for item in all_
        item_date = item.get("date", "1970-01-01")
        item_subject = item.get("subject", "")
        if subject != "все" and item_subject != subject:
            continue
        if start_date <= item_date <= end_date:
            filtered.append(item)

    # Группировка по предметам
    grouped = {}
    for item in filtered:
        s = item["subject"]
        if s not in grouped:
            grouped[s] = []
        grouped[s].append({
            "date": item["date"],
            "original_link": item["original_link"]
        })

    return {"result": grouped}

def unknown_node(state: AgentState) -> AgentState:
    return {"result": {"error": "Не распознано. Отправьте URL или запрос вида 'материалы по Физике за октябрь'."}}

# ======================
# Сборка графа
# ======================

def route_by_intent(state: AgentState) -> str:
    intent = detect_intent(state)
    if intent == "classify":
        return "classify_node"
    elif intent == "retrieve":
        return "retrieve_node"
    else:
        return "unknown_node"

workflow = StateGraph(AgentState)
workflow.add_node("classify_node", classify_node)
workflow.add_node("retrieve_node", retrieve_node)
workflow.add_node("unknown_node", unknown_node)

workflow.add_conditional_edges(
    START,
    route_by_intent,
    {
        "classify_node": "classify_node",
        "retrieve_node": "retrieve_node",
        "unknown_node": "unknown_node",
    }
)

workflow.add_edge("classify_node", END)
workflow.add_edge("retrieve_node", END)
workflow.add_edge("unknown_node", END)

app = workflow.compile()

# ======================
# Telegram-бот
# ======================

@bot.message_handler(content_types=['text'])
def handle_message(message):
    user_input = message.text.strip()
    print(f"[Получено сообщение от {message.chat.id}]: {user_input}")
    
    try:
        result = app.invoke({
            "user_input": user_input,
            "intent": "",
            "url": None,
            "subject_filter": None,
            "start_date": None,
            "end_date": None,
            "result": {}
        })
        
        output = result.get("result", {})
        response_text = json.dumps(output, ensure_ascii=False, indent=2)
        
        if len(response_text) > 4096:
            for i in range(0, len(response_text), 4096):
                bot.send_message(message.chat.id, response_text[i:i+4096])
        else:
            bot.send_message(message.chat.id, response_text)
            
    except Exception as e:
        error_msg = f"[Ошибка] {e}"
        print(error_msg)
        bot.reply_to(message, error_msg)

# ======================
# Запуск
# ======================

if __name__ == '__main__':
    print(f"Бот запущен. Данные будут сохраняться в: {DATA_FILE}")
    bot.polling(none_stop=True)