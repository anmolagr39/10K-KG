"""One small LLM client (OpenAI-compatible chat API) with an on-disk response cache.

Default provider is the Groq free tier. Any OpenAI-compatible endpoint works via env vars:
  LLM_BASE_URL  default https://api.groq.com/openai/v1
  LLM_API_KEY   default $GROQ_API_KEY
  Gemini: LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai  LLM_API_KEY=<key>
  Ollama: LLM_BASE_URL=http://localhost:11434/v1  LLM_API_KEY=ollama

Every response is cached in data/cache/llm/<sha256(request)>.json. The cache is committed,
so the benchmark can be re-run with no API key (set LLM_OFFLINE=1 to forbid network calls).
Where the LLM is used at all: (1) mapping unusual row labels to ontology metric ids,
(2) extracting prose-only relations with a verbatim quote (checked in code),
(3) planning a query as a JSON program. It never reads or writes a number that ends up in an answer.
"""
import hashlib
import json
import os
import re
import time

import requests

from kg.config import CACHE_DIR

LLM_CACHE = CACHE_DIR / "llm"
PLANNER_MODEL = os.environ.get("LLM_PLANNER_MODEL", "openai/gpt-oss-120b")
EXTRACT_MODEL = os.environ.get("LLM_EXTRACT_MODEL", "qwen/qwen3.8-27b")
FALLBACKS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]

_exhausted: set[str] = set()   # models whose daily quota ran out in this process


class LLMError(Exception):
    pass


def _cache_key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _wait_seconds(resp: requests.Response) -> float:
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            return float(ra) + 0.5
        except ValueError:
            pass
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", resp.text)
    if m:
        return int(m.group(1) or 0) * 60 + float(m.group(2)) + 0.5
    return 10.0


def chat_json(messages: list[dict], model: str | None = None, max_tokens: int = 2000,
              temperature: float = 0.0, tag: str = "", reasoning_effort: str | None = "low",
              allow_fallback: bool = True) -> dict:
    """Return the model's JSON reply (dict). Cached; falls back to other models on daily-quota errors
    unless allow_fallback=False (used where results must come from one fixed model)."""
    model = model or PLANNER_MODEL
    order = [model] + ([m for m in FALLBACKS if m != model] if allow_fallback else [])
    last_err = None
    for m in order:
        payload = {"model": m, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
        if reasoning_effort and "gpt-oss" in m:
            payload["reasoning_effort"] = reasoning_effort
        path = LLM_CACHE / f"{_cache_key(payload)}.json"
        if path.exists():  # an earlier run may have answered with a fallback model
            return json.loads(path.read_text(encoding="utf-8"))["parsed"]
    # no cache hit for any model: call the API
    if os.environ.get("LLM_OFFLINE"):
        raise LLMError("cache miss with LLM_OFFLINE=1")
    base = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    key = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMError("no LLM_API_KEY / GROQ_API_KEY set")
    for m in order:
        if m in _exhausted:
            continue
        payload = {"model": m, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
        if reasoning_effort and "gpt-oss" in m:
            payload["reasoning_effort"] = reasoning_effort
        path = LLM_CACHE / f"{_cache_key(payload)}.json"
        for attempt in range(8):
            try:
                r = requests.post(f"{base}/chat/completions", json=payload, timeout=180,
                                  headers={"Authorization": f"Bearer {key}"})
            except requests.RequestException as e:
                last_err = e
                time.sleep(5)
                continue
            if r.status_code == 429:
                if "per day" in r.text or "(TPD)" in r.text or "(RPD)" in r.text:
                    _exhausted.add(m)
                    last_err = LLMError(f"daily quota exhausted for {m}")
                    break
                time.sleep(min(_wait_seconds(r), 90))
                continue
            if r.status_code == 413 or (r.status_code == 400 and "json_validate_failed" not in r.text):
                raise LLMError(f"{m}: HTTP {r.status_code}: {r.text[:300]}")
            if r.status_code != 200:
                last_err = LLMError(f"{m}: HTTP {r.status_code}: {r.text[:300]}")
                time.sleep(3)
                continue
            body = r.json()
            content = body["choices"][0]["message"].get("content") or ""
            try:
                parsed = _parse_json(content)
            except Exception as e:  # malformed JSON: retry once more, then give up on this model
                last_err = LLMError(f"{m}: bad JSON: {e}: {content[:200]}")
                continue
            LLM_CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"tag": tag, "request": payload, "response": content,
                                        "parsed": parsed, "usage": body.get("usage")},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
            return parsed
    raise LLMError(f"all models failed: {last_err}")
