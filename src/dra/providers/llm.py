"""LLM 接入层：DeepSeek（OpenAI 兼容），支持 JSON 模式与 thinking 开关。"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..trace import Tracer

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    reasoning: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_cny: float
    latency_ms: int


class LLMClient:
    def __init__(self, settings: Settings, tracer: Tracer, on_usage=None) -> None:
        self.s = settings
        self.tracer = tracer
        self.on_usage = on_usage
        self._http = httpx.Client(timeout=settings.llm_timeout)

    def close(self) -> None:
        self._http.close()

    # ---------- 基础调用 ----------
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        json_mode: bool = False,
        thinking: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        span_name: str = "llm",
    ) -> LLMResult:
        model = model or self.s.llm_model
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens or self.s.llm_max_tokens,
            "stream": False,
        }
        if thinking:
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = "high"
        else:
            body["thinking"] = {"type": "disabled"}
            body["temperature"] = temperature if temperature is not None else self.s.llm_temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        with self.tracer.span(span_name, kind="llm", model=model, json_mode=json_mode, thinking=thinking) as span:
            t0 = time.perf_counter()
            data = self._post_with_retry(body)
            latency_ms = int((time.perf_counter() - t0) * 1000)

            usage = data.get("usage") or {}
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
            cost = self.s.cost_cny(model, tokens_in, tokens_out)

            message = (data.get("choices") or [{}])[0].get("message") or {}
            text = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""

            span.usage(tokens_in, tokens_out, cost)
            span.set(latency_ms=latency_ms, chars_out=len(text))
            if self.on_usage is not None:
                self.on_usage(tokens_in, tokens_out, cost)
            return LLMResult(text, reasoning, model, tokens_in, tokens_out, cost, latency_ms)

    def _post_with_retry(self, body: dict[str, Any], attempts: int = 2) -> dict[str, Any]:
        url = f"{self.s.llm_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self.s.llm_api_key}", "Content-Type": "application/json"}
        last: Exception | None = None
        for i in range(attempts):
            try:
                resp = self._http.post(url, json=body, headers=headers)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (429, 500, 502, 503, 504) and i + 1 < attempts:
                    time.sleep(2 * (i + 1))
                    last = LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    continue
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if i + 1 < attempts:
                    time.sleep(2 * (i + 1))
                    continue
                raise LLMError(f"网络错误: {exc}") from exc
        raise LLMError(str(last))

    # ---------- 结构化输出 ----------
    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        *,
        model: str | None = None,
        span_name: str = "llm_json",
        repair_attempts: int = 1,
        temperature: float | None = None,
    ) -> tuple[T, LLMResult]:
        result = self.complete(messages, model=model, json_mode=True, span_name=span_name, temperature=temperature)
        parsed, err = _parse_model(result.text, schema)
        if parsed is not None:
            return parsed, result

        for _ in range(repair_attempts):
            repair = messages + [
                {"role": "assistant", "content": result.text},
                {
                    "role": "user",
                    "content": f"上面的输出不符合 JSON 要求（{err}）。请只输出合法 JSON，不要解释、不要代码块。",
                },
            ]
            result = self.complete(
                repair, model=model, json_mode=True, span_name=f"{span_name}_repair", temperature=temperature
            )
            parsed, err = _parse_model(result.text, schema)
            if parsed is not None:
                return parsed, result
        raise LLMError(f"结构化输出解析失败: {err}")


def _parse_model(text: str, schema: type[T]) -> tuple[T | None, str]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"JSON 语法错误: {exc}"
    try:
        return schema.model_validate(data), ""
    except ValidationError as exc:
        return None, f"字段校验失败: {exc.errors()[:2]}"
