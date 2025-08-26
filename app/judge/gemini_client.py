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
            "You are a succinct debate moderator (judge).\n"
            "Summarize the last turns in 3 short bullet points, then add 1 suggestion for the next turns.\n"
            "Be neutral, mention strongest points and missing counter-arguments.\n\n"
            "Context:\n" + "\n---\n".join(texts[-12:])
        )
        config = genai.types.GenerationConfig(max_output_tokens=max_tokens, temperature=0.4)
        resp = model.generate_content(prompt, generation_config=config)
        return getattr(resp, "text", "(no content)")

    async def summarize(self, texts: List[str], max_tokens: int = 120) -> str:
        return await asyncio.to_thread(self._summarize_sync, texts, max_tokens)
