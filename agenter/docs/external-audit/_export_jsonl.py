"""Export a Claude Code session JSONL into a readable markdown transcript.

The JSONL file (~167 MB raw for our Agenter session) contains a stream
of events: user messages, assistant messages, tool calls, tool results,
plus internal queue/control events. This script keeps the conversation
and tool activity while aggressively truncating tool outputs so the
result fits comfortably in another LLM's context window for review.

Truncation rules applied:
    - tool_use input  : first 600 chars
    - tool_use result : first 700 chars (1500 for error results)
    - thinking blocks : dropped (internal reasoning, very long, low signal)
    - queue/system events : dropped
    - Read/Glob/Grep results on huge files : just first 400 chars

Usage:
    python _export_jsonl.py <input.jsonl> <output.md>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TRUNC_INPUT = 600
TRUNC_RESULT = 700
TRUNC_RESULT_ERROR = 1500
TRUNC_TEXT = 8000  # cap any single text block at 8KB

# Tools whose results tend to be huge and not very informative in transcript
NOISY_TOOL_RESULTS = {"Read", "Glob", "Grep", "Bash", "PowerShell"}


def _truncate(s: str, limit: int) -> str:
    if not isinstance(s, str):
        s = str(s)
    if len(s) > limit:
        return s[:limit] + f"\n...[truncated, {len(s) - limit} more chars]"
    return s


def _render_tool_input(name: str, input_data) -> str:
    try:
        s = json.dumps(input_data, ensure_ascii=False, indent=None)
    except Exception:
        s = repr(input_data)
    return _truncate(s, TRUNC_INPUT)


def _render_tool_result(item: dict, tool_name_hint: str = "") -> str:
    content = item.get("content", "")
    is_error = bool(item.get("is_error", False))
    # content may be string or list of text-parts
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                parts.append(c.get("text") or c.get("content") or str(c))
            else:
                parts.append(str(c))
        content = "\n".join(parts)
    if not isinstance(content, str):
        content = str(content)

    limit = TRUNC_RESULT_ERROR if is_error else TRUNC_RESULT
    if tool_name_hint in NOISY_TOOL_RESULTS and not is_error:
        limit = min(limit, 400)
    return _truncate(content, limit), is_error


def _render_content_items(items, last_tool_use_name: dict):
    """Render a list of content items (mix of text, tool_use, tool_result, thinking).

    `last_tool_use_name` is a mutable dict {tool_use_id -> name} used to
    annotate tool_results with the originating tool name.
    """
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        t = item.get("type", "")
        if t == "text":
            text = item.get("text", "").strip()
            if text:
                out.append(_truncate(text, TRUNC_TEXT))
        elif t == "thinking":
            # drop — too long, internal
            continue
        elif t == "tool_use":
            name = item.get("name", "?")
            tid = item.get("id", "")
            if tid:
                last_tool_use_name[tid] = name
            inp = _render_tool_input(name, item.get("input", {}))
            out.append(f"**→ tool_use: `{name}`**\n```json\n{inp}\n```")
        elif t == "tool_result":
            tid = item.get("tool_use_id", "")
            name_hint = last_tool_use_name.get(tid, "")
            body, is_err = _render_tool_result(item, name_hint)
            tag = "tool_result (ERROR)" if is_err else "tool_result"
            name_part = f" of `{name_hint}`" if name_hint else ""
            out.append(f"**← {tag}{name_part}**\n```\n{body}\n```")
        else:
            # unknown content type — note briefly
            out.append(f"_[unhandled item type: {t}]_")
    return "\n\n".join(p for p in out if p)


def main(in_path: str, out_path: str) -> int:
    in_p = Path(in_path)
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    counters = {"user_msg": 0, "assistant_msg": 0, "queue": 0, "other": 0}
    last_tool_use_name: dict[str, str] = {}

    with in_p.open("r", encoding="utf-8") as fin, out_p.open("w", encoding="utf-8") as fout:
        fout.write("# Agenter — полный транскрипт разработки\n\n")
        fout.write(f"Источник: `{in_p}`\n")
        fout.write(f"Размер исходного JSONL: {in_p.stat().st_size:,} байт\n\n")
        fout.write(
            "Этот документ — реконструкция Claude Code-сессии по разработке Agenter "
            "(локальный AI-агент для 1С на базе Claude Agent SDK). Содержит сообщения "
            "пользователя и ассистента, вызовы tool'ов и их результаты. Длинные tool-"
            "outputs труничены до читаемого размера; внутренние блоки thinking "
            "(reasoning) опущены.\n\n"
        )
        fout.write("---\n\n")

        for line in fin:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            ev_type = ev.get("type")
            if ev_type == "queue-operation":
                counters["queue"] += 1
                continue
            if ev_type not in ("user", "assistant"):
                counters["other"] += 1
                continue

            msg = ev.get("message")
            if not isinstance(msg, dict):
                continue

            role = msg.get("role", ev_type)
            content = msg.get("content")
            timestamp = ev.get("timestamp", "")[:19]

            if isinstance(content, str):
                rendered = _truncate(content.strip(), TRUNC_TEXT)
            elif isinstance(content, list):
                rendered = _render_content_items(content, last_tool_use_name)
            else:
                rendered = ""

            if not rendered.strip():
                continue

            counters[f"{role}_msg"] = counters.get(f"{role}_msg", 0) + 1

            # System reminders inside text body: keep for honesty
            if role == "user":
                label = f"## USER · {timestamp}"
            else:
                label = f"## ASSISTANT · {timestamp}"
            fout.write(f"{label}\n\n{rendered}\n\n---\n\n")

        fout.write(f"\n_End of transcript._\n\n")
        fout.write(f"Counts: {counters}\n")

    print(f"Wrote {out_p} ({out_p.stat().st_size:,} bytes)")
    print(f"Counts: {counters}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
