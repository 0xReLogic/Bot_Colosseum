from __future__ import annotations

import asyncio
import os
from typing import List

import google.generativeai as genai


class GeminiJudge:
    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        genai.configure(api_key=self.api_key)
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    def _summarize_sync(self, texts: List[str], max_tokens: int) -> str:
        model = genai.GenerativeModel(self.model_name)
        prompt = (
            "Anda adalah moderator debat yang ringkas (juri). Bahasa: Indonesia.\n"
            "Ringkaslah giliran terakhir dalam 3 bullet poin pendek, lalu beri 1 saran untuk giliran berikutnya.\n"
            "Bersikap netral, sebutkan poin terkuat dan kontra-argumen yang belum dijawab.\n"
            "Jangan menulis heading seperti 'Ringkasan Juri'. Jawab hanya berupa bullet.\n\n"
            "Konteks:\n" + "\n---\n".join(texts[-12:])
        )
        config = genai.types.GenerationConfig(max_output_tokens=max_tokens, temperature=0.4)
        resp = model.generate_content(prompt, generation_config=config)
        text = getattr(resp, "text", "(no content)")
        # Optional usage logging
        if os.getenv("LOG_TOKEN_USAGE"):
            try:
                usage = getattr(resp, "usage_metadata", None) or getattr(resp, "usageMetadata", None)
                print(f"[gemini_usage] model={self.model_name} usage={getattr(usage, 'to_dict', lambda: usage)() if usage else None}")
            except Exception:
                pass
        return text

    async def summarize(self, texts: List[str], max_tokens: int = 120) -> str:
        return await asyncio.to_thread(self._summarize_sync, texts, max_tokens)
