"""
agenter/app/bsl_ls.py — нативная интеграция BSL Language Server (без Docker).

Sprint 2 S2.1 архитектуры из audit-2026-05-15.md. Заменяет проприетарный
Docker-контейнер `comol/1c_syntaxcheck_mcp` на upstream-инструмент:
github.com/1c-syntax/bsl-language-server (open-source, MIT).

Стратегия выбора исполняемого файла (по приоритету):

  1. Native GraalVM-binary: ``mcp-servers/bsl-ls/bsl-language-server.exe``
     — не требует Java на машине, работает «из коробки».
  2. Jar: ``mcp-servers/bsl-ls/bsl-language-server.jar`` + ``java`` в PATH.
  3. Lightweight fallback: чистый Python проверяет грубые BSL-ошибки
     (балансировка `Процедура...КонецПроцедуры`, `Если...КонецЕсли` и т.п.).
     Лучше чем ничего, хуже чем настоящий LS.

Для каждой проверки запускает BSL LS в режиме CLI analyze:

    bsl-language-server.exe analyze --srcDir <dir> --reporter json --silent

Парсит JSON-отчёт и возвращает список диагностик. UI/agent видит компактный
сводный текст: «5 errors, 12 warnings: ...».
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)


# Где Agenter ищет BSL LS executable. mcp-servers/ — папка, куда положены
# инструкции по установке (см. docs/SETUP-BSL-LS.md).
_DEFAULT_BSL_LS_DIR = Path(r"D:\CURSORIC\agenter\mcp-servers\bsl-ls")


@dataclass(slots=True)
class Diagnostic:
    """Одна диагностика от BSL LS (или fallback'а)."""
    severity: str          # error | warning | info | hint
    line: int              # 1-based
    column: int            # 1-based
    message: str
    code: str = ""         # код правила, например "FunctionShouldHaveDescription"
    source: str = "BSL LS" # источник: «BSL LS» / «fallback»


# ── Поиск исполняемого файла ────────────────────────────────────────────────


def _find_executable(custom_dir: Path | None = None) -> tuple[str, str] | tuple[None, None]:
    """Возвращает (path, kind) где kind ∈ {'exe', 'jar'} или (None, None).

    Ищет в нескольких типичных локациях:
      1. <dir>/bsl-language-server.exe — .exe положили рядом (наш ожидаемый layout)
      2. <dir>/bsl-language-server/bsl-language-server.exe — родной zip-layout от
         upstream: внутри подпапки лежит .exe + bundled JRE (runtime/) + jars (app/).
         Переносить .exe отдельно нельзя, он не запустится без runtime/.
      3. Аналогично для .jar (вариант B из README — для тех, у кого Java уже стоит).

    Сначала проверяем custom_dir (если передан), затем дефолтный.
    """
    candidates_dirs = []
    if custom_dir:
        candidates_dirs.append(Path(custom_dir))
    candidates_dirs.append(_DEFAULT_BSL_LS_DIR)

    # На каждом candidate проверяем два под-layout'а (плоский + zip-подпапка)
    for base in candidates_dirs:
        if not base or not base.exists():
            continue
        for sub in (base, base / "bsl-language-server"):
            if not sub.exists():
                continue
            exe = sub / "bsl-language-server.exe"
            if exe.exists():
                return (str(exe), "exe")
        for sub in (base, base / "bsl-language-server"):
            if not sub.exists():
                continue
            jar = sub / "bsl-language-server.jar"
            if jar.exists():
                return (str(jar), "jar")
            # У upstream .jar часто называется bsl-language-server-X.Y.Z-exec.jar
            # внутри подпапки app/. Подхватываем эту локацию.
            app_dir = sub / "app"
            if app_dir.exists():
                for cand in sorted(app_dir.glob("bsl-language-server-*-exec.jar")):
                    return (str(cand), "jar")
    return (None, None)


def _has_java() -> bool:
    """Проверка наличия java в PATH (для jar-варианта)."""
    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


# ── Запуск настоящего BSL LS ────────────────────────────────────────────────


def _run_bsl_ls(
    exe_path: str,
    exe_kind: str,
    src_dir: Path,
    timeout: int = 120,
) -> tuple[list[Diagnostic], str]:
    """Запускает BSL LS analyze на каталоге, возвращает (diagnostics, raw_out).

    BSL LS пишет JSON в `bsl-json.json` в рабочей папке. После прогона читаем.
    """
    if exe_kind == "exe":
        cmd = [exe_path]
    else:
        cmd = ["java", "-jar", exe_path]
    cmd += [
        "analyze",
        "--srcDir", str(src_dir),
        "--reporter", "json",
        "--silent",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(src_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return ([], f"BSL LS превысил таймаут {timeout}s — слишком большой scope?")
    except FileNotFoundError as e:
        return ([], f"BSL LS не запустился: {e}")

    # Файл отчёта обычно `bsl-json.json` в src_dir или cwd
    report_paths = [
        src_dir / "bsl-json.json",
        Path("bsl-json.json"),
    ]
    report_text: str | None = None
    for rp in report_paths:
        if rp.exists():
            try:
                report_text = rp.read_text(encoding="utf-8")
                break
            except Exception:
                pass

    raw_out = (proc.stdout or "") + (proc.stderr or "")
    if not report_text:
        return ([], raw_out)

    try:
        data = json.loads(report_text)
    except json.JSONDecodeError:
        return ([], raw_out + "\n(JSON отчёт повреждён)")

    # Реальный формат BSL LS 0.29.0 (lowercase ключи):
    #   {"date": "...", "fileinfos": [
    #     {"path": "file:///.../test.bsl", "diagnostics": [
    #       {"code": "...", "severity": "Error|Warning|Info|Hint",
    #        "message": "...",
    #        "range": {"start": {"line": N, "character": C}, "end": {...}}
    #       }
    #     ]}
    #   ]}
    diagnostics: list[Diagnostic] = []
    fileinfos = data.get("fileinfos") or data.get("FileInfos") or []
    for fi in fileinfos:
        path_in_report = fi.get("path") or fi.get("Path") or ""
        # Извлекаем имя файла из URI для удобной фильтрации
        short_name = path_in_report
        if "/" in short_name:
            short_name = short_name.rsplit("/", 1)[-1]
        diags_in_file = fi.get("diagnostics") or fi.get("Diagnostics") or []
        for d in diags_in_file:
            sev_raw = (d.get("severity") or d.get("Severity") or "Warning").lower()
            # BSL LS severity (LSP-style): Error / Warning / Information / Hint.
            # Также возможны legacy-варианты Blocker/Critical/Major/Minor.
            sev = (
                "error"   if sev_raw in ("error", "blocker", "critical") else
                "warning" if sev_raw in ("warning", "major", "minor") else
                "info"
            )
            rng   = d.get("range") or d.get("Range") or {}
            start = rng.get("start") or rng.get("Start") or {}
            line  = int(start.get("line", 0) or 0)
            col   = int(start.get("character", 0) or 0)
            diagnostics.append(Diagnostic(
                severity=sev,
                # LSP — 0-based, у нас в UI принято 1-based для отображения
                line=line + 1,
                column=col + 1,
                message=str(d.get("message") or d.get("Message") or "").strip(),
                code=str(d.get("code") or d.get("Code") or ""),
                source=f"BSL LS [{short_name}]",
            ))
    return diagnostics, raw_out


# ── Lightweight fallback (Python regex-checks) ─────────────────────────────


_KEYWORD_PAIRS = [
    # Открывающий → закрывающий
    (r"\bПроцедура\b",   r"\bКонецПроцедуры\b"),
    (r"\bФункция\b",     r"\bКонецФункции\b"),
    (r"\bЕсли\b.*\bТогда\b", r"\bКонецЕсли\b"),
    (r"\bПока\b.*\bЦикл\b",  r"\bКонецЦикла\b"),
    (r"\bДля\b.*\bЦикл\b",   r"\bКонецЦикла\b"),
    (r"\bПопытка\b",     r"\bКонецПопытки\b"),
]


def _basic_python_check(file_path: Path) -> list[Diagnostic]:
    """Грубая проверка BSL без LS — только баланс блочных ключевых слов.

    Игнорируется в строковых литералах и комментариях (наивно — по //).
    """
    diagnostics: list[Diagnostic] = []
    try:
        text = file_path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as e:
        return [Diagnostic("error", 0, 0, f"Не удалось прочитать файл: {e}", source="fallback")]

    # Убираем комментарии и строковые литералы для подсчёта.
    # 1) Сначала строковые литералы (могут содержать // — не комментарий!)
    #    Простая модель: между неэкранированными кавычками. 1С использует
    #    двойные кавычки для строк; «"" внутри строки» — это экранирование.
    cleaned = re.sub(r'"(?:[^"]|"")*"', '""', text, flags=re.DOTALL)
    # 2) Затем построчные комментарии (// до конца строки)
    cleaned_lines = []
    for line in cleaned.splitlines():
        if "//" in line:
            line = line.split("//", 1)[0]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    # Считаем баланс блочных ключевых слов
    for open_re, close_re in [
        (r"\bПроцедура\b",       r"\bКонецПроцедуры\b"),
        (r"\bФункция\b",         r"\bКонецФункции\b"),
        (r"\bПопытка\b",         r"\bКонецПопытки\b"),
    ]:
        opens = len(re.findall(open_re, cleaned, re.IGNORECASE))
        closes = len(re.findall(close_re, cleaned, re.IGNORECASE))
        if opens != closes:
            diagnostics.append(Diagnostic(
                severity="error",
                line=0, column=0,
                message=(
                    f"Несбалансированы блоки {open_re.strip(r'\b')} / "
                    f"{close_re.strip(r'\b')}: {opens} открывающих, {closes} закрывающих"
                ),
                source="fallback",
            ))

    # КонецЕсли vs Если...Тогда (с учётом ИначеЕсли)
    if_opens = len(re.findall(r"\bЕсли\b.*?\bТогда\b", cleaned, re.IGNORECASE | re.DOTALL))
    if_closes = len(re.findall(r"\bКонецЕсли\b", cleaned, re.IGNORECASE))
    if if_opens != if_closes:
        diagnostics.append(Diagnostic(
            severity="error",
            line=0, column=0,
            message=f"Несбалансированы Если/КонецЕсли: {if_opens} / {if_closes}",
            source="fallback",
        ))

    # Циклы
    loop_opens = len(re.findall(r"\b(?:Пока|Для)\b.*?\bЦикл\b", cleaned, re.IGNORECASE | re.DOTALL))
    loop_closes = len(re.findall(r"\bКонецЦикла\b", cleaned, re.IGNORECASE))
    if loop_opens != loop_closes:
        diagnostics.append(Diagnostic(
            severity="error",
            line=0, column=0,
            message=f"Несбалансированы Пока|Для...Цикл/КонецЦикла: {loop_opens} / {loop_closes}",
            source="fallback",
        ))

    return diagnostics


# ── Публичный API ──────────────────────────────────────────────────────────


def check_bsl_path(
    target: str | Path,
    *,
    bsl_ls_dir: str | Path | None = None,
    timeout: int = 120,
) -> tuple[list[Diagnostic], str]:
    """Проверяет один BSL-файл или каталог через BSL LS (или fallback).

    Возвращает (diagnostics, mode) где mode ∈ {'bsl-ls-exe', 'bsl-ls-jar',
    'fallback', 'unavailable'}.

    Если target — файл, для BSL LS используется родительский каталог как
    --srcDir (LS работает на уровне директории). Для fallback'а проверяется
    непосредственно файл.
    """
    p = Path(target)
    if not p.exists():
        return [Diagnostic("error", 0, 0, f"Путь не существует: {p}", source="meta")], "unavailable"

    custom_dir = Path(bsl_ls_dir) if bsl_ls_dir else None
    exe_path, exe_kind = _find_executable(custom_dir)

    # Проверка Java для jar-варианта
    if exe_kind == "jar" and not _has_java():
        log.warning("BSL LS .jar найден, но Java отсутствует → fallback")
        exe_path, exe_kind = None, None

    if exe_path and exe_kind:
        src_dir = p if p.is_dir() else p.parent
        diags, _ = _run_bsl_ls(exe_path, exe_kind, src_dir, timeout=timeout)
        # Если target — конкретный файл, фильтруем диагностики только по нему
        if p.is_file():
            fname = p.name.lower()
            diags = [
                d for d in diags
                if not d.source.startswith("BSL LS [") or fname in d.source.lower()
            ]
        return diags, f"bsl-ls-{exe_kind}"

    # Fallback: только если target — файл (директорию не сканируем)
    if p.is_file():
        return _basic_python_check(p), "fallback"

    # Папка без BSL LS — нечего проверять
    return [
        Diagnostic(
            severity="info",
            line=0, column=0,
            message=(
                "BSL Language Server не найден; для полной проверки скачайте "
                "bsl-language-server.exe (GraalVM-native, не требует Java) с "
                "github.com/1c-syntax/bsl-language-server/releases и положите в "
                "mcp-servers/bsl-ls/. Без него работает только базовая Python-проверка "
                "одного файла."
            ),
            source="meta",
        ),
    ], "unavailable"


def format_diagnostics_summary(
    diagnostics: Iterable[Diagnostic],
    *,
    max_rows: int = 40,
) -> str:
    """Компактный человекочитаемый отчёт. Группировка по severity."""
    diags = list(diagnostics)
    if not diags:
        return "✓ Замечаний нет (0 errors, 0 warnings)."

    errs = [d for d in diags if d.severity == "error"]
    wrns = [d for d in diags if d.severity == "warning"]
    others = [d for d in diags if d.severity not in ("error", "warning")]

    head = f"{len(errs)} errors, {len(wrns)} warnings"
    if others:
        head += f", {len(others)} info"
    lines = [head, ""]
    shown = 0
    # Сначала errors, потом warnings, потом info
    for group, label in ((errs, "ERROR"), (wrns, "WARN"), (others, "INFO")):
        for d in group:
            if shown >= max_rows:
                lines.append(f"... и ещё {len(diags) - shown} (вывод обрезан)")
                return "\n".join(lines)
            loc = f"{d.line}:{d.column}" if d.line else "?"
            code = f" [{d.code}]" if d.code else ""
            lines.append(f"  {label:5s} {loc:>8s}  {d.message}{code}")
            shown += 1
    return "\n".join(lines)
