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

# ======================
# Настройки
# ======================

API_KEY = "MDE5OWRlNGQtODZmMy03NTBiLWFhMGMtOTg4OTZkMWVhZjRjOjgwYjM4OTc3LWYxMTktNDM2YS05NDU1LTU0YTM2ZmE0YmExZg=="

llm = GigaChat(
    credentials=API_KEY,
    scope="GIGACHAT_API_PERS",
    auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
    verify_ssl_certs=False
)

# ======================
# Модели данных (для справки, не используется напрямую в StateGraph)
# ======================

class SubjectAnalysis(BaseModel):
    date: str = Field(description="Дата добавления в формате ГГГГ-ММ-ДД")
    subject: str = Field(description="Предмет")
    original_link: str = Field(description="Ссылка")

# ======================
# Состояние агента
# ======================

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

def write_to_json_file(data: Dict[str, Any]) -> None:
    filename = "requests.json"
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

def load_saved_data() -> List[Dict[str, Any]]:
    try:
        with open("requests.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
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
    "  \"subject\": \"название предмета\"\n"
    "}}\n\n"
    
    "Текст для анализа:\n"
    "{content}"
)

classify_prompt = PromptTemplate(template=CLASSIFY_PROMPT_TEMPLATE, input_variables=["content"])

RETRIEVE_PROMPT_TEMPLATE = (
    "Ты - ассистент для поиска учебных материалов. Проанализируй запрос пользователя и извлеки параметры.\n\n"
    
    "ПРАВИЛА ИЗВЛЕЧЕНИЯ:\n"
    "1. **subject**: Должен строго соответствовать одному из: \n"
    "   - 'Численные методы'\n"
    "   - 'Компьютерные сети' \n"
    "   - 'Программирование на Python'\n"
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
    "   - 'программирование python за последний месяц' → subject: 'Программирование на Python', соответствующие даты\n\n"
    
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
    elif any(kw in user_input.lower() for kw in ["материал", "ссылк", "покажи", "дай", "по предмету", "за", "все"]):
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
        prompt_text = classify_prompt.format(content=content)
        response = llm.invoke([HumanMessage(content=prompt_text)])
        try:
            text = response.content.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(text[start:end])
                subject = data.get("subject", "Не относится ни к одному из курсов")
            else:
                subject = "Не относится ни к одному из курсов"
        except Exception:
            subject = "Не относится ни к одному из курсов"

        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),  # ← дата добавления, не из LLM!
            "subject": subject,
            "original_link": url
        }

    write_to_json_file(result)
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
            raise ValueError("No JSON")
    except Exception:
        subject, start_date, end_date = "все", "2000-01-01", today

    all_data = load_saved_data()
    filtered = []
    for item in all_data:
        item_date = item.get("date", "1970-01-01")
        item_subject = item.get("subject", "")
        if subject != "все" and item_subject != subject:
            continue
        if start_date <= item_date <= end_date:
            # Добавляем subject явно в каждую запись
            filtered.append({
                "date": item["date"],
                "subject": item["subject"],
                "original_link": item["original_link"]
            })
    
    grouped = {}
    for item in filtered:
         s = item["subject"]
         if s not in grouped:
             grouped[s] = []
         grouped[s].append(item)  # item уже содержит subject
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
# Запуск
# ======================

def main():
    print("Агент запущен. Введите URL или запрос (например: 'материалы по Физике за октябрь').")
    while True:
        try:
            user_input = input("> ").strip()
            if not user_input:
                break
            result = app.invoke({
                "user_input": user_input,
                "intent": "",
                "url": None,
                "subject_filter": None,
                "start_date": None,
                "end_date": None,
                "result": {}
            })
            print(json.dumps(result["result"], ensure_ascii=False, indent=2))
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[Ошибка] {e}")

if __name__ == "__main__":
    main()