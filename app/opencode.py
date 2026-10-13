"""OpenCode Go backend, OpenAI-compatible chat completions.

Selected with LC_PROVIDER=opencode. Same seam as gemini.py: contents arrive
in the app's Gemini wire format (text/functionCall/functionResponse parts)
and the reply leaves in it too, so coach.py and the stored rows stay
provider-agnostic. inlineData (audio) is dropped: DeepSeek is text-only.
"""
import hashlib
import json
import os
import time

import httpx

from . import settings

BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
API_KEY = os.environ.get("OPENCODE_API_KEY", "")
# Families served on the chat/completions route; Grok/GPT live on /responses
# and MiniMax/Qwen on /messages, so they're filtered out of the picker.
CHAT_PREFIXES = ("deepseek", "glm", "kimi", "longcat", "mimo")


def has_token() -> bool:
    return bool(API_KEY)


def models() -> list[str]:
    """Live catalog of the Go subscription. On error, the configured id."""
    try:
        res = httpx.get(f"{BASE_URL}/models",
                        headers={"Authorization": f"Bearer {API_KEY}"}, timeout=5)
        ids = sorted(m["id"] for m in res.json().get("data", [])
                     if m.get("id", "").startswith(CHAT_PREFIXES))
        return ids or [settings.current_model("opencode")]
    except (httpx.HTTPError, ValueError, KeyError):
        return [settings.current_model("opencode")]


def _schema(node):
    """JSON Schema minus the Gemini-only `nullable` keyword."""
    if isinstance(node, dict):
        return {k: _schema(v) for k, v in node.items() if k != "nullable"}
    if isinstance(node, list):
        return [_schema(v) for v in node]
    return node


def _messages(contents: list[dict], system: str | None) -> list[dict]:
    """Wire contents -> OpenAI messages. Tool calls get deterministic ids
    matched to functionResponse parts in order of appearance."""
    msgs = [{"role": "system", "content": system}] if system else []
    pending: dict[str, list[str]] = {}
    seq = 0
    for turn in contents:
        role = "assistant" if turn["role"] == "model" else "user"
        text, calls = [], []
        for part in turn.get("parts", []):
            if "functionResponse" in part:
                fr = part["functionResponse"]
                ids = pending.get(fr.get("name", ""), [])
                msgs.append({"role": "tool",
                             "tool_call_id": ids.pop(0) if ids else f"orphan_{len(msgs)}",
                             "content": json.dumps(fr.get("response") or {}, ensure_ascii=False)})
            elif "functionCall" in part:
                calls.append(part["functionCall"])
            elif "inlineData" in part:
                text.append("[audio joint, non audible par ce modèle]")
            elif part.get("text") and not part.get("thought"):
                text.append(part["text"])
        if not text and not calls:
            continue
        msg = {"role": role, "content": "\n".join(text) or None}
        if calls:
            msg["tool_calls"] = []
            for call in calls:
                seq += 1
                cid = f"call_{seq}"
                pending.setdefault(call.get("name", ""), []).append(cid)
                msg["tool_calls"].append({
                    "id": cid, "type": "function",
                    "function": {"name": call.get("name", ""),
                                 "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False)}})
        msgs.append(msg)
    return msgs


def _stream(body: dict, session: str):
    with httpx.stream(
        "POST",
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}",
                 # Go asks for an own UA plus a per-conversation session id
                 # (routing and prompt caching); see opencode.ai/docs/go.
                 "User-Agent": "language-coach/1.0",
                 "x-opencode-session": session},
        json=body,
        timeout=httpx.Timeout(None, connect=10),
    ) as res:
        if res.status_code != 200:
            raise RuntimeError(f"chat/completions {res.status_code}: {res.read().decode()}", res)
        for line in res.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            yield json.loads(data)


def generate_turn(contents: list[dict], system: str | None = None,
                  tools: list[dict] | None = None, on_text=None) -> list[dict]:
    """Same contract as gemini.generate_turn: on_text gets each streamed text
    delta, and the return value is Gemini-format parts for storage/replay."""
    body = {"model": settings.current_model("opencode"),
            "messages": _messages(contents, system), "stream": True}
    if tools:
        body["tools"] = [{"type": "function", "function": _schema(t)} for t in tools]
    # The first wire row never changes within a thread, so its hash is a
    # stable conversation id without threading a new argument through coach.
    session = hashlib.sha256(
        json.dumps(contents[:1], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    text, calls = "", {}
    for _attempt in range(3):
        try:
            for chunk in _stream(body, session):
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta", {})
                    if delta.get("content"):
                        text += delta["content"]
                        if on_text:
                            on_text(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", 0), {"name": "", "arguments": ""})
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["arguments"] += fn.get("arguments") or ""
            break
        except RuntimeError as e:
            res = e.args[1] if len(e.args) > 1 else None
            if res is not None and res.status_code == 429 and not text and not calls:
                time.sleep(1)
                continue
            raise
    parts = [{"text": text}] if text else []
    parts += [{"functionCall": {"name": c["name"], "args": json.loads(c["arguments"] or "{}")}}
              for _, c in sorted(calls.items())]
    return parts
