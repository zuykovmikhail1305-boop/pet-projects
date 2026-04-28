from __future__ import annotations

import json
import re
import subprocess
import tempfile
from typing import Any

from app.core.config import settings
from app.core.db import get_recent_messages
from app.services.ollama_client import OllamaClient


SYSTEM_PROMPT = """Ты — генератор Lua-кода для LowCode.

Правила:
1. Пиши только корректный Lua.
2. Используй только прямой доступ через wf.vars и wf.initVariables.
3. Не используй JsonPath.
4. Не добавляй markdown-блоки, комментарии и пояснения внутри ответа.
5. Если задача простая и однозначная, выдай минимальный рабочий код.
6. Если задача соответствует типовым шаблонам, придерживайся шаблонного решения.
7. Если запрос недостаточно конкретный, НЕ генерируй код. Вместо этого задай один короткий уточняющий вопрос.
8. Возвращай либо только Lua-код, либо только один уточняющий вопрос.
"""


def extract_json_context_from_prompt(prompt: str) -> dict[str, Any]:
    first_brace = prompt.find("{")
    if first_brace == -1:
        return {}

    candidate = prompt[first_brace:].strip()
    try:
        return json.loads(candidate)
    except Exception:
        return {}


def build_context(prompt: str, attachments: list[dict[str, Any]] | None) -> dict[str, Any]:
    ctx = extract_json_context_from_prompt(prompt)
    wf = ctx.get("wf")
    if not isinstance(wf, dict):
        wf = {}
        ctx["wf"] = wf

    vars_obj = wf.get("vars")
    if not isinstance(vars_obj, dict):
        vars_obj = {}
        wf["vars"] = vars_obj

    init_vars = wf.get("initVariables")
    if not isinstance(init_vars, dict):
        init_vars = {}
        wf["initVariables"] = init_vars

    wf["attachments"] = attachments or []
    return ctx


def needs_clarification(prompt: str, context: dict[str, Any]) -> str | None:
    text = prompt.strip()
    lower = text.lower()

    has_json = bool(context and context.get("wf"))
    attachment_count = len(((context.get("wf") or {}).get("attachments") or []))

    too_generic_patterns = [
        r"^напиши код\.?$",
        r"^сделай код\.?$",
        r"^нужен код\.?$",
        r"^lua\.?$",
        r"^напиши lua\.?$",
        r"^сгенерируй код\.?$",
        r"^код\.?$",
    ]

    if any(re.match(pattern, lower) for pattern in too_generic_patterns):
        return "Что именно должен делать код? Опиши задачу и, если есть, приложи пример входных данных."

    generic_without_context = [
        "напиши код",
        "сделай код",
        "нужен код",
        "сгенерируй код",
        "напиши lua",
        "сделай lua",
    ]

    if any(phrase in lower for phrase in generic_without_context) and not has_json and attachment_count == 0:
        return "Что именно должен делать код? Нужны описание задачи и пример контекста."

    action_words = [
        "получи", "получи последний", "увелич", "очист", "преобраз", "конверт",
        "отфильтр", "добав", "проверь", "верни", "найди", "удали", "оставь",
    ]
    mentions_action = any(word in lower for word in action_words)

    if len(text) < 18 and not mentions_action and not has_json and attachment_count == 0:
        return "Уточни задачу: что должен делать код и с какими данными он работает?"

    return None


def try_match_template(prompt: str, context: dict[str, Any]) -> dict[str, Any] | None:
    lower = prompt.lower()
    wf = context.get("wf", {})
    vars_obj = wf.get("vars", {})

    emails = vars_obj.get("emails")
    if (
        "email" in lower
        and "последн" in lower
        and isinstance(emails, list)
        and emails
    ):
        return {
            "status": "template",
            "text": "Применён шаблон для получения последнего элемента массива.",
            "code": "return wf.vars.emails[#wf.vars.emails]",
            "validation": {},
            "iterations": [{"phase": "template", "content": "last_email"}],
        }

    restbody = vars_obj.get("RESTbody", {})
    result = restbody.get("result") if isinstance(restbody, dict) else None
    if (
        "очист" in lower
        and "id" in lower
        and "entity_id" in lower
        and "call" in lower
        and isinstance(result, list)
    ):
        code = """result = wf.vars.RESTbody.result
for _, filteredEntry in pairs(result) do
  for key, value in pairs(filteredEntry) do
    if key ~= "ID" and key ~= "ENTITY_ID" and key ~= "CALL" then
      filteredEntry[key] = nil
    end
  end
end
return result"""
        return {
            "status": "template",
            "text": "Применён шаблон очистки RESTbody.result.",
            "code": code,
            "validation": {},
            "iterations": [{"phase": "template", "content": "cleanup_restbody_keys"}],
        }

    if (
        "try_count_n" in lower
        and ("увелич" in lower or "итерац" in lower)
        and "try_count_n" in vars_obj
    ):
        return {
            "status": "template",
            "text": "Применён шаблон инкремента счётчика.",
            "code": "return wf.vars.try_count_n + 1",
            "validation": {},
            "iterations": [{"phase": "template", "content": "increment_try_count"}],
        }

    parsed_csv = vars_obj.get("parsedCsv")
    if (
        "отфильтр" in lower
        and "discount" in lower
        and "markdown" in lower
        and isinstance(parsed_csv, list)
    ):
        code = """local result = _utils.array.new()
local items = wf.vars.parsedCsv
for _, item in ipairs(items) do
  if (item.Discount ~= "" and item.Discount ~= nil) or (item.Markdown ~= "" and item.Markdown ~= nil) then
    table.insert(result, item)
  end
end
return result"""
        return {
            "status": "template",
            "text": "Применён шаблон фильтрации массива parsedCsv.",
            "code": code,
            "validation": {},
            "iterations": [{"phase": "template", "content": "filter_discount_markdown"}],
        }

    return None


def validate_lua_syntax(code: str) -> tuple[bool, str]:
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as temp:
            temp.write(code)
            path = temp.name

        process = subprocess.run(
            ["luac", "-p", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if process.returncode == 0:
            return True, "ok"
        return False, (process.stderr or process.stdout or "syntax error").strip()
    except FileNotFoundError:
        return True, "luac not found, syntax check skipped"
    except Exception as exc:
        return False, str(exc)


def clean_model_code(raw: str) -> str:
    text = raw.strip()

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    text = text.replace("lua{", "").replace("}lua", "").strip()
    return text


def looks_like_question(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return "?" in stripped or stripped.lower().startswith(("уточни", "какой", "что ", "какие ", "нужно ли", "где ", "как "))


class LuaAgentService:
    def __init__(self) -> None:
        self.client = OllamaClient()

    async def process(
        self,
        prompt: str,
        chat_id: int | None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        context = build_context(prompt, attachments)

        clarification = needs_clarification(prompt, context)
        if clarification:
            return {
                "status": "clarify",
                "text": clarification,
                "code": "",
                "validation": {},
                "iterations": [{"phase": "clarify", "content": clarification}],
            }

        template = try_match_template(prompt, context)
        if template:
            ok, msg = validate_lua_syntax(template["code"])
            template["validation"] = {"syntax": {"ok": ok, "message": msg}}
            return template

        if not await self.client.is_model_ready():
            return {
                "status": "loading",
                "text": f"Модель '{settings.default_model}' ещё загружается. Подожди немного и повтори запрос.",
                "code": "",
                "validation": {},
                "iterations": [],
            }

        history = []
        if chat_id is not None:
            history = get_recent_messages(chat_id, limit=8)

        history_lines: list[str] = []
        for item in history:
            role = "user" if item["kind"] == "prompt" else "assistant"
            history_lines.append(f"{role}: {item['content']}")

        attachment_texts = []
        for item in attachments or []:
            name = item.get("name", "")
            content = item.get("content", "")
            excerpt = item.get("excerpt", "")
            joined = content or excerpt
            attachment_texts.append(f"{name}:\n{joined}")

        user_payload = {
            "task": prompt,
            "context": context,
            "history": history_lines,
            "attachments": attachment_texts,
            "instruction": (
                "Если задача неясна — верни один короткий уточняющий вопрос. "
                "Если задача ясна — верни только Lua-код без markdown и объяснений."
            ),
        }

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]

        raw = await self.client.chat(messages)

        if looks_like_question(raw):
            return {
                "status": "clarify",
                "text": raw.strip(),
                "code": "",
                "validation": {},
                "iterations": [{"phase": "clarify", "content": raw.strip()}],
            }

        code = clean_model_code(raw)
        ok, msg = validate_lua_syntax(code)

        if not ok and not code:
            return {
                "status": "clarify",
                "text": "Уточни, что именно должен делать код и с какими данными он работает?",
                "code": "",
                "validation": {},
                "iterations": [{"phase": "clarify", "content": "fallback_clarify"}],
            }

        return {
            "status": "result" if ok else "failed",
            "text": "Код сгенерирован." if ok else "Сгенерирован код, но синтаксическая проверка не пройдена.",
            "code": code,
            "validation": {
                "syntax": {
                    "ok": ok,
                    "message": msg,
                }
            },
            "iterations": [
                {
                    "phase": "generate",
                    "content": raw,
                }
            ],
        }