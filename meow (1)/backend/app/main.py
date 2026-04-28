from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from pypdf import PdfReader

from app.core.config import settings
from app.core.db import (
    add_message,
    create_chat,
    get_chat,
    init_db,
    list_chats,
    update_chat_title,
)
from app.services.agent import LuaAgentService
from app.services.ollama_client import OllamaClient


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title=settings.app_title)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)


class GenerateRequest(BaseModel):
    prompt: str
    chat_id: int | None = None
    attachments: list[dict[str, Any]] = []


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    os.makedirs(settings.uploads_dir, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    template = templates_env.get_template("index.html")
    html = template.render(
        request=request,
        app_title=settings.app_title,
        default_model=settings.default_model,
    )
    return HTMLResponse(content=html)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    client = OllamaClient()
    ready = await client.is_model_ready()
    return {
        "ok": True,
        "model_ready": ready,
        "model": settings.default_model,
    }


@app.get("/api/chats")
async def chats_list() -> list[dict[str, Any]]:
    return list_chats()


@app.post("/api/chats")
async def create_chat_endpoint() -> dict[str, Any]:
    chat = create_chat("New chat")
    return {"chat_id": chat["id"], "title": chat["title"]}


@app.get("/api/chats/{chat_id}")
async def chat_detail(chat_id: int) -> dict[str, Any]:
    chat = get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.post("/api/generate")
async def generate(payload: GenerateRequest) -> dict[str, Any]:
    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is empty")

    chat_id = payload.chat_id
    if chat_id is None:
        title = prompt[:48].strip() or "New chat"
        chat = create_chat(title)
        chat_id = chat["id"]
    else:
        chat = get_chat(chat_id)
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")

    add_message(chat_id, "prompt", prompt, meta={})

    for item in payload.attachments:
      add_message(
          chat_id,
          "file",
          item.get("content") or item.get("excerpt") or item.get("name", ""),
          meta={"name": item.get("name", "")},
      )

    agent_response = await LuaAgentService().process(
        prompt=prompt,
        chat_id=chat_id,
        attachments=payload.attachments,
    )

    result_status = agent_response.get("status", "result")
    result_text = agent_response.get("text", "")

    result_kind = "clarify" if result_status == "clarify" else "result"

    add_message(
        chat_id,
        result_kind,
        result_text,
        meta={
            "status": result_status,
            "validation": agent_response.get("validation", {}),
            "iterations": agent_response.get("iterations", []),
        },
    )

    code = agent_response.get("code", "").strip()
    if code and result_status != "clarify":
        add_message(chat_id, "code", code, meta={})

    current_chat = get_chat(chat_id)
    if current_chat and current_chat.get("title") == "New chat":
        update_chat_title(chat_id, prompt[:48].strip() or "New chat")

    final_chat = get_chat(chat_id)
    if not final_chat:
        raise HTTPException(status_code=500, detail="Failed to load chat after generation")

    return {
        "chat_id": chat_id,
        "chat": final_chat,
    }


@app.post("/api/files/upload")
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    saved_name = f"{uuid.uuid4().hex}_{file.filename}"
    saved_path = os.path.join(settings.uploads_dir, saved_name)

    with open(saved_path, "wb") as fh:
        fh.write(content)

    text_content = extract_file_text(saved_path, file.content_type or "", file.filename or "")
    excerpt = text_content[:4000]

    return {
        "id": uuid.uuid4().hex,
        "name": file.filename or saved_name,
        "content_type": file.content_type or "application/octet-stream",
        "excerpt": excerpt,
        "content": text_content,
    }


def extract_file_text(path: str, content_type: str, filename: str) -> str:
    lower_name = filename.lower()

    if lower_name.endswith(".pdf") or content_type == "application/pdf":
        return extract_pdf_text(path)

    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="cp1251") as fh:
                return fh.read()
        except Exception:
            return ""
    except Exception:
        return ""


def extract_pdf_text(path: str) -> str:
    try:
        reader = PdfReader(path)
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n\n".join(parts).strip()
    except Exception:
        return ""