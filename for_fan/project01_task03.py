import requests
from bs4 import BeautifulSoup
from langchain_gigachat import GigaChat
from langchain_core.messages import HumanMessage
from langchain.prompts import PromptTemplate
from pydantic import BaseModel, Field
from datetime import datetime
import json
from typing import Dict, Any

API_KEY = "MDE5OWRlNGQtODZmMy03NTBiLWFhMGMtOTg4OTZkMWVhZjRjOjgwYjM4OTc3LWYxMTktNDM2YS05NDU1LTU0YTM2ZmE0YmExZg=="

llm = GigaChat(
    credentials=API_KEY,
    scope="GIGACHAT_API_PERS",
    auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
    verify_ssl_certs=False
)


class SubjectAnalysis(BaseModel):
    date: str = Field(description="Дата, в которую была получена ссылка")
    subject: str = Field(description="Предмет, для которого она будет полезна")
    original_link: str = Field(description="Оригинальная ссылка")


def write_to_json_file(data: Dict[str, Any]) -> str:
    """Tool для записи JSON в файл requests.json"""
    try:
        filename = "requests.json"
        
        # Читаем существующие данные
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing_data = []
        
        # Добавляем новые данные
        if isinstance(existing_data, list):
            existing_data.append(data)
        else:
            existing_data = [existing_data, data]
        
        # Записываем обратно
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)
        
        return f"Данные успешно записаны в {filename}"
    except Exception as e:
        return f"Ошибка при записи в файл: {e}"


def truncate_by_characters(text: str, max_chars: int = 1000) -> str:
    return text[:max_chars] if len(text) > max_chars else text


def get_text_from_url(url: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = " ".join(text.split())
        return truncate_by_characters(text, 1000)
    except Exception as e:
        return f"[Ошибка загрузки страницы: {e}]"


PROMPT_TEMPLATE = (
    "Ты — интеллектуальный помощник для студента. "
    "Проанализируй следующий текст и определи, к какому из перечисленных учебных курсов он наиболее релевантен: "
    "Численные методы, Компьютерные сети, Программирование на python, Физика. "
    "Верни ответ в формате JSON со следующими полями: "
    "date (сегодняшняя дата в формате ГГГГ-ММ-ДД), "
    "subject (один из вариантов: 'Численные методы', 'Компьютерные сети', 'Программирование на python', 'Физика', 'Не относится ни к одному из курсов'), "
    "original_link (оригинальная ссылка). "
    "Не добавляй никаких других слов или пояснений.\n\n"
    "Текст: {content}\n"
    "Ссылка: {url}"
)

prompt = PromptTemplate(template=PROMPT_TEMPLATE, input_variables=["content", "url"])


def main():
    url = input().strip()
    if not url:
        return

    page_text = get_text_from_url(url)

    if page_text.startswith("[Ошибка"):
        print(page_text)
        return

    formatted_prompt = prompt.format(content=page_text, url=url)
    messages = [HumanMessage(content=formatted_prompt)]
    response = llm.invoke(messages)

    try:
        response_text = response.content.strip()
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        
        if json_start != -1 and json_end != 0:
            json_str = response_text[json_start:json_end]
            data = json.loads(json_str)
            
            result = SubjectAnalysis(
                date=data.get('date', datetime.now().strftime('%Y-%m-%d')),
                subject=data.get('subject', 'Не относится ни к одному из курсов'),
                original_link=data.get('original_link', url)
            )
        else:
            result = SubjectAnalysis(
                date=datetime.now().strftime('%Y-%m-%d'),
                subject='Не относится ни к одному из курсов',
                original_link=url
            )
        
        # Конвертируем в словарь для записи в файл
        result_dict = {
            "date": result.date,
            "subject": result.subject,
            "original_link": result.original_link
        }
        
        # Выводим в консоль
        print(json.dumps(result_dict, ensure_ascii=False, indent=2))
        
        # Записываем в файл
        write_result = write_to_json_file(result_dict)
        print(write_result)
        
    except Exception as e:
        result = SubjectAnalysis(
            date=datetime.now().strftime('%Y-%m-%d'),
            subject='Не относится ни к одному из курсов',
            original_link=url
        )
        
        result_dict = {
            "date": result.date,
            "subject": result.subject,
            "original_link": result.original_link
        }
        
        print(json.dumps(result_dict, ensure_ascii=False, indent=2))
        write_result = write_to_json_file(result_dict)
        print(write_result)


if __name__ == "__main__":
    main()