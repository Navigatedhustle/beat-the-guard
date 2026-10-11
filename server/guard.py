"""
ResearchGuard (Sentinel V6) client.

Renders the exact V6 prompt with the checkpoint's chat template and streams
from vLLM /v1/completions. Emits the verdict as soon as the "decision" field
appears, then the parsed JSON when generation completes.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import jinja2

from .sentinel_prompt import LABELS, build_messages

ROOT = Path(__file__).resolve().parents[1]
VLLM_URL = os.environ.get("BTG_VLLM_URL", "http://127.0.0.1:8001")
MODEL = "sentinel-v6"
MAX_TOKENS = 300
TIMEOUT_S = float(os.environ.get("BTG_GUARD_TIMEOUT", "20"))

EXPECTED_KEYS = {"decision", "citations", "conditions", "rationale"}
DECISION_RE = re.compile(
    r'"decision"\s*:\s*"(YES|NO|CONDITIONAL|INSUFFICIENT)"', re.I)

_env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)


def _raise(msg):
    raise jinja2.TemplateError(msg)


_env.globals["raise_exception"] = _raise
_TEMPLATE = _env.from_string(
    (ROOT / "models/sentinel-v6-ckpt512/chat_template.jinja").read_text())


class GuardError(Exception):
    pass


def render(messages):
    return _TEMPLATE.render(messages=messages, bos_token="<|begin_of_text|>",
                            add_generation_prompt=True)


def strict_parse(text):
    """Same contract as the V6 evaluator's strict_parse."""
    try:
        obj = json.loads(text.strip())
    except Exception:
        return None
    if not isinstance(obj, dict) or set(obj) != EXPECTED_KEYS:
        return None
    if obj.get("decision") not in LABELS:
        return None
    if not isinstance(obj.get("citations"), list) or not all(
            isinstance(i, str) for i in obj["citations"]):
        return None
    if not isinstance(obj.get("conditions"), list) or not all(
            isinstance(i, str) for i in obj["conditions"]):
        return None
    if not isinstance(obj.get("rationale"), str):
        return None
    return obj


def stream(question, evidence_records):
    """
    Yields ("verdict", decision, t_decision_ms) once, then
    ("final", decision, parsed_or_None, raw_text, t_total_ms).
    Raises GuardError if the model server is down, hangs, or returns nothing
    usable.
    """
    prompt = render(build_messages(question, evidence_records))
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "max_tokens": MAX_TOKENS,
        "temperature": 0, "stream": True, "add_special_tokens": False,
    }).encode()
    req = urllib.request.Request(VLLM_URL + "/v1/completions", body,
                                 {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    text = ""
    decision = None
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            for line in r:
                line = line.decode().strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                text += json.loads(line[6:])["choices"][0]["text"]
                if decision is None:
                    m = DECISION_RE.search(text)
                    if m:
                        decision = m.group(1).upper()
                        yield ("verdict", decision,
                               round((time.perf_counter() - t0) * 1000))
                if time.perf_counter() - t0 > TIMEOUT_S:
                    raise GuardError("generation exceeded timeout")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise GuardError(str(e)) from e

    parsed = strict_parse(text)
    if decision is None:
        if parsed is None:
            raise GuardError("no decision in model output")
        decision = parsed["decision"]
        yield ("verdict", decision, round((time.perf_counter() - t0) * 1000))
    yield ("final", decision, parsed, text,
           round((time.perf_counter() - t0) * 1000))


def health():
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(VLLM_URL + "/v1/models", timeout=3) as r:
            ids = [m["id"] for m in json.load(r)["data"]]
        return {"ok": MODEL in ids, "models": ids,
                "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
