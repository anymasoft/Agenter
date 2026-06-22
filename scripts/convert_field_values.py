"""
Конвертер field-values.ts → field_values.json.

Парсит исходный TypeScript-файл от MetadataViewer1C и сохраняет содержимое
трёх объектов (FIELD_VALUES, FIELD_LABELS, ENUM_VALUE_LABELS,
INFORMATION_REGISTER_PERIODICITY_LABELS) в один JSON.

Запускать вручную при обновлении исходника MetadataViewer1C.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Пути по умолчанию
SOURCE_TS = Path(r"D:\CURSORIC\agenter\_vendor\MetadataViewer1C\src\Metadata\field-values.ts")
TARGET_JSON = Path(r"D:\CURSORIC\agenter\app\data\field_values.json")


# Регекс заголовков объявления объектов
_HEADER_PATTERNS = {
    "FIELD_VALUES": re.compile(
        r"export\s+const\s+FIELD_VALUES\s*:\s*[^=]+=\s*\{", re.DOTALL
    ),
    "FIELD_LABELS": re.compile(
        r"export\s+const\s+FIELD_LABELS\s*:\s*[^=]+=\s*\{", re.DOTALL
    ),
    "ENUM_VALUE_LABELS": re.compile(
        r"export\s+const\s+ENUM_VALUE_LABELS\s*:\s*[^=]+=\s*\{", re.DOTALL
    ),
    "INFORMATION_REGISTER_PERIODICITY_LABELS": re.compile(
        r"const\s+INFORMATION_REGISTER_PERIODICITY_LABELS\s*:\s*[^=]+=\s*\{",
        re.DOTALL,
    ),
}


def _find_matching_brace(text: str, start: int) -> int:
    """Возвращает индекс закрывающей фигурной скобки `{...}`.

    start должен указывать на саму `{`.
    Учитывает вложенные скобки и кавычки.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            quote = c
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    break
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            # line comment
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            # block comment
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"Unmatched brace starting at {start}")


def _extract_object(ts_source: str, name: str) -> str:
    """Извлекает текст между {} объекта по имени."""
    pat = _HEADER_PATTERNS[name]
    match = pat.search(ts_source)
    if not match:
        raise ValueError(f"Object {name} not found")
    open_brace = match.end() - 1  # позиция `{`
    close_brace = _find_matching_brace(ts_source, open_brace)
    return ts_source[open_brace : close_brace + 1]


def _ts_object_to_json(obj_text: str) -> dict:
    """Преобразует TS-литерал объекта в Python dict.

    Использует трансформации:
        - убирает // комментарии и /* */ комментарии
        - заменяет одинарные кавычки на двойные (только вне строк)
        - убирает trailing commas
    """
    # 1. Убрать комментарии
    text = _strip_comments(obj_text)

    # 2. Заменить одинарные кавычки на двойные (учитывая экранирование)
    text = _normalize_quotes(text)

    # 3. Обернуть unquoted-ключи в двойные кавычки
    #    Пример: `Nonperiodical: "..."` → `"Nonperiodical": "..."`
    text = re.sub(
        r"(?<=[{,\s])([A-Za-z_][A-Za-z0-9_]*)(\s*:)",
        r'"\1"\2',
        text,
    )

    # 4. Убрать trailing commas
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 4. Распарсить как JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Дебаг — покажем что не так
        line_no = e.lineno
        lines = text.split("\n")
        context = "\n".join(
            f"{i+1:4d}: {l}" for i, l in enumerate(lines[max(0, line_no - 3) : line_no + 3])
        )
        raise ValueError(f"JSON parse error at line {line_no}: {e.msg}\n{context}") from e


def _strip_comments(text: str) -> str:
    """Удаляет TS/JS комментарии // и /* */."""
    # Сначала /* ... */
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Затем // до конца строки
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _normalize_quotes(text: str) -> str:
    """Меняет одиночные кавычки на двойные, оставляя содержимое неизменным.

    Простой подход: проходим посимвольно. Если внутри строки — оставляем,
    иначе одинарную → двойная.
    """
    result = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            # Двойная строка — копируем как есть
            result.append(c)
            i += 1
            while i < n:
                result.append(text[i])
                if text[i] == "\\":
                    i += 1
                    if i < n:
                        result.append(text[i])
                        i += 1
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
        elif c == "'":
            # Одинарная строка → меняем на двойные с escape `"`
            result.append('"')
            i += 1
            while i < n:
                if text[i] == "\\":
                    result.append(text[i])
                    i += 1
                    if i < n:
                        result.append(text[i])
                        i += 1
                    continue
                if text[i] == "'":
                    result.append('"')
                    i += 1
                    break
                if text[i] == '"':
                    result.append('\\"')
                    i += 1
                    continue
                result.append(text[i])
                i += 1
        else:
            result.append(c)
            i += 1
    return "".join(result)


def main() -> int:
    if not SOURCE_TS.exists():
        print(f"ERROR: source not found: {SOURCE_TS}", file=sys.stderr)
        return 1

    ts_source = SOURCE_TS.read_text(encoding="utf-8")

    output: dict = {}
    for name in _HEADER_PATTERNS:
        try:
            obj_text = _extract_object(ts_source, name)
            data = _ts_object_to_json(obj_text)
            output[name] = data
            print(f"  OK {name}: {len(data)} keys")
        except Exception as e:
            print(f"  FAIL {name}: {e}", file=sys.stderr)
            return 2

    TARGET_JSON.parent.mkdir(parents=True, exist_ok=True)
    TARGET_JSON.write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {TARGET_JSON} ({TARGET_JSON.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
