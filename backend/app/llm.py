
"""Model providers behind one small interface. All calls are made here, on the server.

Neutral message format:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [...]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
"""

import base64
import json
import logging
from dataclasses import dataclass, field

import requests

from .config import settings

log = logging.getLogger("llm")


class LLMError(Exception):
    """kind: not_configured | auth | rate_limit | bad_request | server | timeout | network | bad_response"""

    def __init__(
        self,
        kind: str,
        message: str,
        status: int | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status


USER_MESSAGES = {
    "not_configured": "The AI assistant is not set up yet. Add an API key in the backend settings.",
    "auth": "The AI service rejected the API key. Check the key and model name in the backend settings.",
    "rate_limit": "The AI service is busy or the usage limit was reached. Please try again in a minute.",
    "bad_request": "The AI service could not accept this request. Check the model name in the backend settings.",
    "server": "The AI service had a problem. Please try again in a moment.",
    "timeout": "The AI service took too long to answer. Please try again.",
    "network": "Could not reach the AI service. Check the internet connection of the server.",
    "bad_response": "The AI service sent an answer the app could not read. Please try again.",
}


def user_message(err: LLMError) -> str:
    return USER_MESSAGES.get(err.kind, USER_MESSAGES["server"])


def classify_status(status: int | None, text: str = "") -> str:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    if status in (400, 404, 413, 422):
        return "bad_request"
    if status and status >= 500:
        return "server"
    return "server"


@dataclass
class LLMResult:
    text: str = ""
    tool_calls: list = field(default_factory=list)
    stop_reason: str = ""


# ------------------------------------------------------------------
# Anthropic provider
# ------------------------------------------------------------------

def map_anthropic_error(exc: Exception) -> LLMError:
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()

    if "timeout" in name:
        return LLMError("timeout", str(exc)[:160])
    if "connection" in name:
        return LLMError("network", str(exc)[:160])

    return LLMError(classify_status(status), str(exc)[:160], status)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float):
        import anthropic

        self.client = anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=1,
        )
        self.model = model

    @staticmethod
    def convert(messages):
        out = []
        pending = None

        for m in messages:
            if m["role"] == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"],
                }

                if pending is None:
                    pending = {"role": "user", "content": []}
                    out.append(pending)

                pending["content"].append(block)
                continue

            pending = None

            if m["role"] == "assistant":
                blocks = []

                if m.get("content"):
                    blocks.append({
                        "type": "text",
                        "text": m["content"],
                    })

                for tc in m.get("tool_calls") or []:
                    blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["args"] or {},
                    })

                out.append({
                    "role": "assistant",
                    "content": blocks or [{
                        "type": "text",
                        "text": "...",
                    }],
                })
            else:
                out.append({
                    "role": "user",
                    "content": m["content"],
                })

        return out

    def complete(self, system, messages, tools, max_tokens):
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": self.convert(messages),
        }

        if tools:
            kwargs["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["input_schema"],
                }
                for t in tools
            ]

        try:
            resp = self.client.messages.create(**kwargs)
        except Exception as exc:
            raise map_anthropic_error(exc) from exc

        text = "".join(
            getattr(b, "text", "")
            for b in resp.content
            if getattr(b, "type", "") == "text"
        )

        calls = [
            {
                "id": b.id,
                "name": b.name,
                "args": dict(b.input or {}),
            }
            for b in resp.content
            if getattr(b, "type", "") == "tool_use"
        ]

        return LLMResult(
            text=text.strip(),
            tool_calls=calls,
            stop_reason=getattr(resp, "stop_reason", "") or "",
        )

    def complete_vision(
        self, system, text, jpeg: bytes, max_tokens, model=None
    ):
        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(jpeg).decode(),
            },
        }

        try:
            resp = self.client.messages.create(
                model=model or self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{
                    "role": "user",
                    "content": [
                        block,
                        {"type": "text", "text": text},
                    ],
                }],
            )
        except Exception as exc:
            raise map_anthropic_error(exc) from exc

        out = "".join(
            getattr(b, "text", "")
            for b in resp.content
            if getattr(b, "type", "") == "text"
        ).strip()

        if not out:
            raise LLMError(
                "bad_response",
                "The model returned no text",
            )

        return out


# ------------------------------------------------------------------
# OpenAI-compatible provider, including Gemini
# ------------------------------------------------------------------

class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @staticmethod
    def convert(system, messages):
        out = [{"role": "system", "content": system}]

        for m in messages:
            if m["role"] == "tool":
                out.append({
                    "role": "tool",
                    "tool_call_id": m["tool_call_id"],
                    "content": m["content"],
                })

            elif m["role"] == "assistant":
                msg = {
                    "role": "assistant",
                    "content": m.get("content") or None,
                }

                if m.get("tool_calls"):
                    converted_calls = []

                    for tc in m["tool_calls"]:
                        item = {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(
                                    tc["args"] or {}
                                ),
                            },
                        }

                        # Preserve provider-specific metadata, including
                        # Gemini thought signatures, on subsequent turns.
                        if tc.get("extra_content") is not None:
                            item["extra_content"] = tc["extra_content"]

                        converted_calls.append(item)

                    msg["tool_calls"] = converted_calls

                out.append(msg)

            else:
                out.append({
                    "role": "user",
                    "content": m["content"],
                })

        return out

    def _post(self, body):
        headers = {"Content-Type": "application/json"}

        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key

        try:
            r = requests.post(
                self.base_url + "/chat/completions",
                headers=headers,
                json=body,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise LLMError("timeout", str(exc)[:160]) from exc
        except requests.RequestException as exc:
            raise LLMError("network", str(exc)[:160]) from exc

        if r.status_code >= 400:
            raise LLMError(
                classify_status(r.status_code),
                r.text[:200],
                r.status_code,
            )

        try:
            return r.json()
        except ValueError as exc:
            raise LLMError(
                "bad_response",
                "The service did not return JSON",
            ) from exc

    def complete(self, system, messages, tools, max_tokens):
        body = {
            "model": self.model,
            "messages": self.convert(system, messages),
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }

        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]

        data = self._post(body)

        try:
            choice = data["choices"][0]
            msg = choice["message"]
            calls = []

            for tc in msg.get("tool_calls") or []:
                raw = tc["function"].get("arguments") or "{}"

                try:
                    args = (
                        json.loads(raw)
                        if isinstance(raw, str)
                        else dict(raw)
                    )
                except (ValueError, TypeError):
                    args = {}

                call = {
                    "id": tc.get("id") or f"call_{len(calls)}",
                    "name": tc["function"]["name"],
                    "args": args,
                }

                # Keep Gemini's provider-specific tool-call metadata.
                if tc.get("extra_content") is not None:
                    call["extra_content"] = tc["extra_content"]

                calls.append(call)

            return LLMResult(
                text=(msg.get("content") or "").strip(),
                tool_calls=calls,
                stop_reason=choice.get("finish_reason") or "",
            )

        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(
                "bad_response",
                f"Unexpected response shape: {exc}",
            ) from exc

    def complete_vision(
        self, system, text, jpeg: bytes, max_tokens, model=None
    ):
        url = (
            "data:image/jpeg;base64,"
            + base64.b64encode(jpeg).decode()
        )

        body = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text},
                        {
                            "type": "image_url",
                            "image_url": {"url": url},
                        },
                    ],
                },
            ],
        }

        data = self._post(body)

        try:
            out = (
                data["choices"][0]["message"].get("content") or ""
            ).strip()
        except (
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
        ) as exc:
            raise LLMError(
                "bad_response",
                f"Unexpected response shape: {exc}",
            ) from exc

        if not out:
            raise LLMError(
                "bad_response",
                "The model returned no text "
                "(the token limit may be too small for a reasoning model)",
            )

        return out


# ------------------------------------------------------------------
# Provider factory
# ------------------------------------------------------------------

_cache = {}


def get_provider():
    if not settings.assistant_enabled:
        raise LLMError(
            "not_configured",
            "No LLM provider configured",
        )

    key = (
        settings.llm_provider,
        settings.llm_model,
        settings.llm_base_url,
        bool(settings.llm_api_key or settings.anthropic_api_key),
        settings.llm_timeout,
    )

    if key not in _cache:
        if settings.llm_provider == "anthropic":
            _cache[key] = AnthropicProvider(
                settings.anthropic_api_key,
                settings.llm_model,
                settings.llm_timeout,
            )
        else:
            _cache[key] = OpenAICompatProvider(
                settings.llm_base_url,
                settings.llm_api_key,
                settings.llm_model,
                settings.llm_timeout,
            )

    return _cache[key]
