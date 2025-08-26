from __future__ import annotations

import os
import httpx
from typing import List, Dict, Any


class GroqClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self.base_url = base_url or "https://api.groq.com/openai/v1"
        self._client = httpx.Client(timeout=60.0)

    def chat(self,
             model: str,
             messages: List[Dict[str, Any]],
             temperature: float = 0.7,
             max_tokens: int = 512,
             stop: list[str] | None = None,
             return_usage: bool = False) -> str | tuple[str, Any]:
        """Call Groq chat completions (OpenAI-compatible) and return text content."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stop:
            payload["stop"] = stop
        resp = self._client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage")
        if os.getenv("LOG_TOKEN_USAGE"):
            print(f"[groq_usage] model={model} usage={usage}")
        if return_usage:
            return text, usage
        return text
