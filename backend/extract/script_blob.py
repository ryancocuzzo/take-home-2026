import json
import re
from typing import Any


_ASSIGNMENT_PREFIX_RE = re.compile(r"(window|self|globalThis)\.__[A-Za-z0-9_]+\s*=")


def iter_assigned_json_blobs(script_body: str) -> list[Any]:
    """
    Extract JSON blobs from common assignment patterns:
      window.__FOO__ = {...};
      self.__DATA__ = [...];
      globalThis.__STATE__ = {...};
    """
    payloads: list[Any] = []
    idx = 0
    while True:
        match = _ASSIGNMENT_PREFIX_RE.search(script_body, idx)
        if not match:
            break
        json_start = _next_json_start(script_body, match.end())
        if json_start < 0:
            idx = match.end()
            continue

        extracted, end_idx = _extract_balanced_json(script_body, json_start)
        if extracted:
            payload = _safe_json_loads(extracted)
            if payload is not None:
                payloads.append(payload)
        idx = end_idx
    return payloads


def _next_json_start(text: str, start_idx: int) -> int:
    for i in range(start_idx, len(text)):
        if text[i] in "{[":
            return i
        if text[i] == ";":
            return -1
    return -1


def _extract_balanced_json(text: str, start_idx: int) -> tuple[str | None, int]:
    opening = text[start_idx]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for i in range(start_idx, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == opening:
            depth += 1
            continue
        if ch == closing:
            depth -= 1
            if depth == 0:
                return text[start_idx : i + 1], i + 1

    return None, len(text)


def _safe_json_loads(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
