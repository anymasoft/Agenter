#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
prd-create.py — генератор PRD-документа из JSON-описания.

Sprint 3 S3.3: формирует структурированный markdown-PRD для больших L4-задач
(taskmaster-style). Цель — зафиксировать ТЗ до начала кодирования, дать агенту
и человеку общую точку ссылки на «что нужно сделать».

Скилл намеренно простой: без анализа объектов, без auto-обогащения. Берёт
структурированный JSON и форматирует в каноничный PRD-документ.

Вызов через skill_run в Agenter:
    skill_run("prd-create", {"json_path": "tmp/req.json", "output_path": "docs/specs/prds/x.md"})

Или напрямую из CLI:
    python prd-create.py -JsonPath req.json -OutputPath out.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    """argparse с PowerShell-style именами (skill_run конвертирует snake_case
    в PascalCase, то есть Agenter передаёт -JsonPath / -OutputPath)."""
    # Кастомный парсер чтобы поддержать -JsonPath / -OutputPath (PS-стиль)
    args = sys.argv[1:]
    out: dict[str, str] = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-") and i + 1 < len(args):
            key = a.lstrip("-").lower()
            out[key] = args[i + 1]
            i += 2
        else:
            i += 1
    if "jsonpath" not in out or "outputpath" not in out:
        print("ERROR: ожидаются параметры -JsonPath <file> -OutputPath <file>",
              file=sys.stderr)
        sys.exit(2)
    return argparse.Namespace(
        json_path=Path(out["jsonpath"]),
        output_path=Path(out["outputpath"]),
    )


def _section(title: str, items: list[str] | None) -> str:
    """Возвращает markdown-секцию. Пустой список → секция пропускается."""
    if not items:
        return ""
    lines = [f"## {title}", ""]
    for it in items:
        s = str(it).strip()
        if s:
            lines.append(f"- {s}")
    lines.append("")
    return "\n".join(lines)


def _build_prd(data: dict) -> str:
    title = (data.get("title") or "Без названия").strip()
    context = (data.get("context") or "").strip()
    now = datetime.utcnow().strftime("%Y-%m-%d")

    scope = data.get("scope") or {}
    objects = data.get("objects") or {}

    parts: list[str] = []
    parts.append(f"# PRD: {title}")
    parts.append("")
    parts.append(f"_Сгенерировано: {now}_")
    parts.append("")

    if context:
        parts.append("## Контекст")
        parts.append("")
        parts.append(context)
        parts.append("")

    # Scope
    if isinstance(scope, dict) and (scope.get("in") or scope.get("out")):
        parts.append("## Scope")
        parts.append("")
        if scope.get("in"):
            parts.append("**Входит:**")
            parts.append("")
            for s in scope["in"]:
                parts.append(f"- {s}")
            parts.append("")
        if scope.get("out"):
            parts.append("**Не входит:**")
            parts.append("")
            for s in scope["out"]:
                parts.append(f"- {s}")
            parts.append("")

    # Objects
    if isinstance(objects, dict) and (
        objects.get("new") or objects.get("modified") or objects.get("removed")
    ):
        parts.append("## Объекты конфигурации")
        parts.append("")
        if objects.get("new"):
            parts.append("### ADDED — новые объекты")
            parts.append("")
            for s in objects["new"]:
                parts.append(f"- {s}")
            parts.append("")
        if objects.get("modified"):
            parts.append("### MODIFIED — изменения существующих")
            parts.append("")
            for s in objects["modified"]:
                parts.append(f"- {s}")
            parts.append("")
        if objects.get("removed"):
            parts.append("### REMOVED — удаления")
            parts.append("")
            for s in objects["removed"]:
                parts.append(f"- {s}")
            parts.append("")

    # Requirements (FR-XXX)
    reqs = data.get("requirements") or []
    if reqs:
        parts.append("## Функциональные требования")
        parts.append("")
        for r in reqs:
            parts.append(f"- {r}")
        parts.append("")

    # Phases
    phases = data.get("phases") or []
    if phases:
        parts.append("## Фазы реализации")
        parts.append("")
        parts.append("Топологический порядок: каждая фаза завершается `cfe_validate → db_load`.")
        parts.append("")
        for p in phases:
            parts.append(f"{p}" if str(p).strip().startswith(tuple("0123456789")) else f"- {p}")
        parts.append("")

    # Acceptance
    acceptance = data.get("acceptance") or []
    if acceptance:
        parts.append("## Acceptance criteria")
        parts.append("")
        for a in acceptance:
            parts.append(f"- {a}")
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    args = _parse_args()
    if not args.json_path.exists():
        print(f"ERROR: JsonPath не существует: {args.json_path}", file=sys.stderr)
        return 1
    try:
        data = json.loads(args.json_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"ERROR: не парсится JSON: {e}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print(f"ERROR: ожидается JSON-объект на верхнем уровне, получен {type(data).__name__}",
              file=sys.stderr)
        return 1

    md = _build_prd(data)
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(md, encoding="utf-8")
    print(f"PRD создан: {args.output_path}")
    print(f"Размер: {len(md)} символов, {md.count(chr(10)) + 1} строк")
    return 0


if __name__ == "__main__":
    sys.exit(main())
