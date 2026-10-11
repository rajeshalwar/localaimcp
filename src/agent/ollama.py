"""Minimal Ollama chat client -- just the tool-calling loop's half of it."""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.environ.get("MODEL_NAME", "qwen2.5:7b-instruct")
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "350"))
# Tool-selection turns need room for a tool call plus brief reasoning, but MUST
# be bounded: an uncapped tool turn let the model ramble for twenty minutes at
# CPU speed during testing. Generous, but finite.
TOOL_NUM_PREDICT = int(os.environ.get("OLLAMA_TOOL_NUM_PREDICT", "700"))
REQUEST_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "240"))
def _keep_alive(raw: str):
    """Ollama's keep_alive field wants a JSON number (seconds) or a duration
    string WITH a unit ("30m"). The string "-1" is rejected outright with
    `time: missing unit in duration "-1"` -- so coerce bare numbers to numbers.
    -1 means "keep the model resident forever", which is what stops the demo
    paying a ~6s cold load on every turn.
    """
    raw = (raw or "").strip()
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw or -1


KEEP_ALIVE = _keep_alive(os.environ.get("OLLAMA_KEEP_ALIVE", "-1"))


def _options(num_predict: int | None) -> dict:
    opts: dict[str, Any] = {"num_ctx": NUM_CTX, "temperature": 0.1}
    if num_predict is not None:
        opts["num_predict"] = num_predict
    return opts


async def chat(
    client: httpx.AsyncClient, messages: list[dict], tools: list[dict] | None = None
) -> dict:
    """One non-streaming turn. Non-streaming while resolving tool calls keeps
    the loop simple and avoids parsing partial tool-call JSON."""
    resp = await client.post(
        f"{HOST}/api/chat",
        json={"model": MODEL, "messages": messages, "tools": tools or [],
              "stream": False, "keep_alive": KEEP_ALIVE,
              "options": _options(TOOL_NUM_PREDICT)},
        timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0),
    )
    if resp.status_code >= 400:
        # A bare "400 Bad Request" tells you nothing. Ollama puts the actual
        # complaint (usually a tool schema it dislikes) in the body.
        raise RuntimeError(f"Ollama {resp.status_code} on /api/chat: {resp.text[:600]}")
    return resp.json()


async def stream_final(
    client: httpx.AsyncClient, messages: list[dict]
) -> AsyncIterator[str]:
    """Stream only the closing narration -- the one turn a human is reading."""
    payload = {"model": MODEL, "messages": messages, "stream": True,
               "keep_alive": KEEP_ALIVE, "options": _options(NUM_PREDICT)}
    async with client.stream("POST", f"{HOST}/api/chat", json=payload,
                             timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0)) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            chunk = json.loads(line)
            piece = (chunk.get("message") or {}).get("content") or ""
            if piece:
                yield piece
            if chunk.get("done"):
                return


async def ensure_model(client: httpx.AsyncClient) -> tuple[bool, str]:
    try:
        r = await client.get(f"{HOST}/api/tags", timeout=10)
        r.raise_for_status()
    except Exception as exc:
        return False, f"cannot reach Ollama at {HOST}: {exc}"
    have = {m["name"] for m in r.json().get("models", [])}
    if MODEL in have or f"{MODEL}:latest" in have:
        return True, MODEL
    return False, (f"model {MODEL!r} is not present. Have: {sorted(have) or 'nothing'}. "
                   f"Run `make pull-model`.")


async def warm(client: httpx.AsyncClient) -> None:
    """Force the model resident before the first question, so the demo never
    pays a 6-8s cold load in front of an audience."""
    await client.post(f"{HOST}/api/chat",
                      json={"model": MODEL, "messages": [{"role": "user", "content": "hi"}],
                            "stream": False, "keep_alive": KEEP_ALIVE,
                            "options": {"num_ctx": NUM_CTX, "num_predict": 1}},
                      timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0))
