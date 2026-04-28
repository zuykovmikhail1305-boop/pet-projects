from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.default_model
        self.options: dict[str, Any] = {
            "temperature": 0.1,
            "top_p": 0.9,
            "repeat_penalty": 1.05,
            "num_ctx": 1024,
            "num_predict": 160,
        }

    async def tags(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return response.json()

    async def is_model_ready(self) -> bool:
        try:
            data = await self.tags()
            models = data.get("models", [])
            return any(model.get("name") == self.model for model in models)
        except Exception:
            return False

    async def chat(self, messages: list[dict[str, str]], *, model: str | None = None) -> str:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "options": self.options,
        }

        async with httpx.AsyncClient(timeout=600) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)

        if response.status_code == 404:
            raise RuntimeError(
                f"Модель '{self.model}' ещё не загружена или Ollama ещё не готова."
            )

        response.raise_for_status()
        data = response.json()
        message = data.get("message") or {}
        return str(message.get("content") or "").strip()