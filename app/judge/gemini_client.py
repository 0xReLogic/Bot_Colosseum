from __future__ import annotations

import asyncio
import os
from typing import List, Tuple, Dict, Any

import google.generativeai as genai


class GeminiJudge:
    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        genai.configure(api_key=self.api_key)
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    def _summarize_sync(self, texts: List[str], max_tokens: int, return_usage: bool = False):
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
        usage_obj = getattr(resp, "usage_metadata", None) or getattr(resp, "usageMetadata", None)
        usage_dict: Dict[str, Any] | None = None
        if os.getenv("LOG_TOKEN_USAGE"):
            try:
                print(
                    f"[gemini_usage] model={self.model_name} usage="
                    f"{getattr(usage_obj, 'to_dict', lambda: usage_obj)() if usage_obj else None}"
                )
            except Exception:
                pass
        if return_usage:
            try:
                usage_dict = {
                    "input_tokens": getattr(usage_obj, "input_token_count", None),
                    "output_tokens": getattr(usage_obj, "output_token_count", None),
                    "total_token_count": getattr(usage_obj, "total_token_count", None),
                }
            except Exception:
                usage_dict = None
            return text, usage_dict
        return text

    async def summarize(self, texts: List[str], max_tokens: int = 120, return_usage: bool = False):
        return await asyncio.to_thread(self._summarize_sync, texts, max_tokens, return_usage)

    def _generate_topics_sync(self, keyword: str | None, count: int) -> List[str]:
        model = genai.GenerativeModel(self.model_name)
        kw = keyword.strip() if keyword else ""
        instr = (
            "Buat daftar topik debat Indonesia yang ringkas dan menarik. "
            f"Jumlah: {count}. "
            "Format: satu baris per topik tanpa nomor/heading. "
        )
        if kw:
            instr += f"Fokus pada tema: {kw}. "
        prompt = instr + "Jawab hanya daftar topik."
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", "")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        cleaned: List[str] = []
        for l in lines:
            l = l.lstrip("-• ")
            # remove leading numbering like 1. or 1)
            if ". " in l[:4]:
                try:
                    int(l.split(".", 1)[0])
                    l = l.split(".", 1)[1].strip()
                except Exception:
                    pass
            if ") " in l[:4]:
                try:
                    int(l.split(")", 1)[0])
                    l = l.split(")", 1)[1].strip()
                except Exception:
                    pass
            cleaned.append(l)
        # ensure unique & limit
        out: List[str] = []
        for t in cleaned:
            if t and t not in out:
                out.append(t)
            if len(out) >= count:
                break
        return out

    async def generate_topics(self, keyword: str | None = None, count: int = 10) -> List[str]:
        return await asyncio.to_thread(self._generate_topics_sync, keyword, count)
