import requests
from bs4 import BeautifulSoup
from langchain_gigachat import GigaChat
from langchain_core.messages import HumanMessage
from langchain.prompts import PromptTemplate

API_KEY = "MDE5OWRlNGQtODZmMy03NTBiLWFhMGMtOTg4OTZkMWVhZjRjOjgwYjM4OTc3LWYxMTktNDM2YS05NDU1LTU0YTM2ZmE0YmExZg=="

llm = GigaChat(
    credentials=API_KEY,
    scope="GIGACHAT_API_PERS",
    auth_url="https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
    verify_ssl_certs=False
)


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
    "Ответь ТОЛЬКО одним из этих вариантов: "
    "«Численные методы», «Компьютерные сети», «Программирование на python», «Физика», "
    "или «Не относится ни к одному из курсов», если релевантность отсутствует. "
    "Не добавляй никаких других слов, пояснений или знаков препинания вне кавычек.\n\n"
    "Текст: {content}"
)

prompt = PromptTemplate(template=PROMPT_TEMPLATE, input_variables=["content"])


def main():
    url = input().strip()
    if not url:
        return

    page_text = get_text_from_url(url)

    if page_text.startswith("[Ошибка"):
        print(page_text)
        return

    formatted_prompt = prompt.format(content=page_text)
    messages = [HumanMessage(content=formatted_prompt)]
    response = llm.invoke(messages)

    print(response.content.strip())


if __name__ == "__main__":
    main()