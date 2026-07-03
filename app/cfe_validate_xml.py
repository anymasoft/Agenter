"""
agenter/app/cfe_validate_xml.py — дополнительные XML-проверки расширения.

Подключается в _cfe_validate (desktop/main.py) ПОСЛЕ основного PowerShell-
скилла cfe-validate.ps1. PowerShell-скилл валидирует структуру CFE-расширения
(ObjectBelonging, ExtendedConfigurationObject, ChildObjects, и т.п.), а этот
модуль — проверки, которые чаще всего ловят ошибки db_load по опыту реальных
разработчиков 1С:

  R14. Help.xml ↔ Ext/Help/ru.html     — отсутствие файла справки валит загрузку
  R15. СКД: 2 файла шаблона            — Templates/X.xml + Templates/X/Ext/Template.xml
  R16. СКД: запрет <role> в <dataSet>  — XDTO-ошибка чтения схемы
  R17. Запрет неподдерживаемых свойств — <Leading> у Dimension, <Recorder> у AccumulationRegister
  R18. Запрет '--' в XML-комментариях  — стандарт XML запрещает двойной дефис внутри <!-- ... -->
  R19. Subsystems Content              — у внутренних подсистем расширения проверить,
                                          что все ссылки разрешимы

Источник правил — публичный курс "1С + Cursor" (Низамутдинов И.) + опыт
работы с реальными расширениями. Каждое правило соответствует ошибке загрузки,
которую сложно отладить пост-фактум.

Возврат:
    {
        "errors":   int,
        "warnings": int,
        "checks":   int,
        "text":     str   # форматированный вывод для добавления к cfe-validate.ps1
    }
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

# ── Namespaces 1C ────────────────────────────────────────────────────────────
_MD_NS  = "http://v8.1c.ru/8.3/MDClasses"
_XR_NS  = "http://v8.1c.ru/8.3/xcf/readable"
_NS     = {"md": _MD_NS, "xr": _XR_NS}

# Категории объектов, в которых может встретиться Help.xml
_HELP_BEARERS = {
    "Catalogs", "Documents", "InformationRegisters", "AccumulationRegisters",
    "AccountingRegisters", "CalculationRegisters",
    "ChartsOfAccounts", "ChartsOfCharacteristicTypes", "ChartsOfCalculationTypes",
    "Reports", "DataProcessors", "Enums", "CommonModules",
    "ExchangePlans", "BusinessProcesses", "Tasks",
}

# Не-поддерживаемые свойства подэлементов (известные грабли XML-выгрузки).
# Карта: тип объекта (в имени папки/файла) → имя свойства, которое НЕ должно встречаться.
_FORBIDDEN_PROPS = [
    # (Откуда взято правило, путь к файлу/маске, имя свойства, объяснение)
    ("AccumulationRegisters", "Recorder",
     "Свойство <Recorder> не входит в состав объекта метаданных AccumulationRegister. "
     "Привязка к регистратору задаётся в Documents/<Документ>.xml → <RegisterRecords>."),
    # <Leading> у Dimension встречается у InformationRegister, но НЕ у Accumulation/Calculation.
    # Здесь упрощённо запрещаем во всех файлах кроме InformationRegister.
]


# ── Утилиты вывода ───────────────────────────────────────────────────────────

class _Report:
    """Накопитель строк отчёта с подсчётом errors/warnings/ok."""
    __slots__ = ("lines", "errors", "warnings", "checks", "max_errors", "stopped")

    def __init__(self, max_errors: int = 30) -> None:
        self.lines: list[str] = []
        self.errors = 0
        self.warnings = 0
        self.checks = 0
        self.max_errors = max_errors
        self.stopped = False

    def error(self, msg: str) -> None:
        self.errors += 1
        self.lines.append(f"[ERROR] {msg}")
        if self.errors >= self.max_errors:
            self.stopped = True

    def warn(self, msg: str) -> None:
        self.warnings += 1
        self.lines.append(f"[WARN]  {msg}")

    def ok(self, msg: str) -> None:
        self.checks += 1
        # OK-строки в общий вывод не пишем, чтобы не зашумлять — итог покажет общее число.

    def render(self) -> str:
        out = []
        out.append("=== XML extras: Help · СКД · forbidden props · comments · subsystems · XDTO ===")
        if self.lines:
            out.extend(self.lines)
        out.append("")
        out.append(
            f"=== Extras result: {self.errors} errors, {self.warnings} warnings "
            f"({self.checks} ok checks) ==="
        )
        return "\n".join(out)


# ── Универсальные хелперы ────────────────────────────────────────────────────

def _iter_object_dirs(ext_src: Path) -> list[tuple[str, Path]]:
    """Возвращает [(категория, путь к папке объекта), ...] для всех stand-alone
    объектов расширения (Catalogs/X, Documents/X, ...).
    """
    result: list[tuple[str, Path]] = []
    for category in _HELP_BEARERS:
        cat_dir = ext_src / category
        if not cat_dir.is_dir():
            continue
        for obj_dir in cat_dir.iterdir():
            if obj_dir.is_dir():
                result.append((category, obj_dir))
    return result


def _read_text(path: Path) -> str | None:
    """Читает текст с автоопределением utf-8/utf-8-sig. None если файла нет."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="cp1251")
        except Exception:
            return None


# ── R14. Help.xml ↔ Ext/Help/ru.html ────────────────────────────────────────

def _check_help_files(ext_src: Path, rep: _Report) -> None:
    """Если у объекта есть Ext/Help.xml и в нём <Page>ru</Page>,
    то Ext/Help/ru.html обязателен. Иначе db_load упадёт с
    «Каталог не обнаружен \\Ext\\Help\\ru.html»."""
    checked = 0
    for category, obj_dir in _iter_object_dirs(ext_src):
        help_xml = obj_dir / "Ext" / "Help.xml"
        if not help_xml.exists():
            continue
        checked += 1
        text = _read_text(help_xml) or ""
        # Извлекаем все <Page>...</Page>
        pages = re.findall(r"<Page>([^<]+)</Page>", text)
        if not pages:
            # Help.xml без <Page> — допускаем, но предупредим
            rep.warn(f"14. {category}/{obj_dir.name}: Help.xml не содержит <Page>")
            continue
        for page in pages:
            page = page.strip()
            html_file = obj_dir / "Ext" / "Help" / f"{page}.html"
            if not html_file.exists():
                rep.error(
                    f"14. {category}/{obj_dir.name}: Help.xml ссылается на <Page>{page}</Page>, "
                    f"но Ext/Help/{page}.html отсутствует — загрузка в БД упадёт"
                )
                if rep.stopped:
                    return
    if checked > 0 and not rep.stopped:
        rep.ok(f"14. Help-файлы проверены: {checked} объектов")


# ── R15 / R16. СКД-шаблоны отчётов ──────────────────────────────────────────

def _check_dcs_templates(ext_src: Path, rep: _Report) -> None:
    """Для каждого отчёта в Reports/X/Templates/<TplName> должны быть два файла:
        - Templates/<TplName>.xml          (метаданные шаблона)
        - Templates/<TplName>/Ext/Template.xml (содержимое СКД)

    Дополнительно: внутри <dataSet><field>...</field> не должно быть <role>
    (XDTO-ошибка чтения схемы при загрузке).
    """
    reports_dir = ext_src / "Reports"
    if not reports_dir.is_dir():
        return

    checked_tpl = 0
    for report_dir in reports_dir.iterdir():
        if not report_dir.is_dir():
            continue
        templates_dir = report_dir / "Templates"
        if not templates_dir.is_dir():
            continue

        # Собираем имена шаблонов: либо файл X.xml в Templates/, либо подпапка X/
        tpl_files = {p.stem for p in templates_dir.glob("*.xml")}
        tpl_dirs  = {p.name for p in templates_dir.iterdir() if p.is_dir()}
        all_names = tpl_files | tpl_dirs

        for tpl_name in sorted(all_names):
            checked_tpl += 1
            meta_file    = templates_dir / f"{tpl_name}.xml"
            content_file = templates_dir / tpl_name / "Ext" / "Template.xml"

            # R15: оба файла обязательны
            if not meta_file.exists():
                rep.error(
                    f"15. Reports/{report_dir.name}/Templates: метаданные шаблона "
                    f"«{tpl_name}.xml» отсутствуют (есть только папка)"
                )
                continue
            if not content_file.exists():
                rep.error(
                    f"15. Reports/{report_dir.name}/Templates/{tpl_name}: содержимое "
                    f"Ext/Template.xml отсутствует — для СКД-шаблона требуются ОБА файла"
                )
                continue

            # R16: в содержимом не должно быть <role> внутри <dataSet>
            content_text = _read_text(content_file) or ""
            # Грубая, но надёжная проверка: ищем dataSet и любую <role> внутри его блока.
            # Полный XML-парсинг тут избыточен, потому что нас интересует только наличие тега.
            if "<dataSet" in content_text:
                # Вырезаем все блоки <dataSet>...</dataSet>; в каждом ищем <role>
                # либо dcscom:resource / dcscom:dimension в любом виде.
                for m in re.finditer(r"<dataSet[\s\S]*?</dataSet>", content_text):
                    block = m.group(0)
                    if re.search(r"<\s*(\w+:)?role\b", block):
                        rep.error(
                            f"16. Reports/{report_dir.name}/Templates/{tpl_name}/Ext/Template.xml: "
                            f"внутри <dataSet> присутствует <role> — это вызывает XDTO-ошибку "
                            f"чтения схемы (роли задаются на уровне настроек СКД, не в полях)"
                        )
                        break
                    if re.search(r"<\s*dcscom:(resource|dimension)\b", block):
                        rep.error(
                            f"16. Reports/{report_dir.name}/Templates/{tpl_name}/Ext/Template.xml: "
                            f"внутри <dataSet> присутствует dcscom:resource/dcscom:dimension "
                            f"— это вызывает XDTO-ошибку (используй стандартные поля без ролей)"
                        )
                        break

            if rep.stopped:
                return

    if checked_tpl > 0 and not rep.stopped:
        rep.ok(f"15-16. СКД-шаблоны проверены: {checked_tpl}")


# ── R17. Запрещённые свойства в XML ─────────────────────────────────────────

def _check_forbidden_props(ext_src: Path, rep: _Report) -> None:
    """Ищет запрещённые свойства в XML-файлах объектов. Известные грабли:

    - <Recorder> у AccumulationRegister.xml
    - <Leading> у Dimension в AccumulationRegister/CalculationRegister
      (у InformationRegister допустимо — пропускаем)
    """
    checked_files = 0

    # AccumulationRegister/<Name>.xml — не должно быть <Recorder>
    ar_dir = ext_src / "AccumulationRegisters"
    if ar_dir.is_dir():
        for obj_dir in ar_dir.iterdir():
            if not obj_dir.is_dir():
                continue
            xml_file = obj_dir / f"{obj_dir.name}.xml"
            if not xml_file.exists():
                continue
            checked_files += 1
            text = _read_text(xml_file) or ""
            if re.search(r"<\s*Recorder\b", text):
                rep.error(
                    f"17. AccumulationRegisters/{obj_dir.name}/{obj_dir.name}.xml: содержит "
                    f"<Recorder> — это свойство НЕ входит в состав AccumulationRegister. "
                    f"Регистратор задаётся в Documents/<Документ>.xml → <RegisterRecords>"
                )
                if rep.stopped:
                    return

    # AccumulationRegister / CalculationRegister — Dimension не должен иметь <Leading>
    for cat in ("AccumulationRegisters", "CalculationRegisters"):
        cat_dir = ext_src / cat
        if not cat_dir.is_dir():
            continue
        for obj_dir in cat_dir.iterdir():
            if not obj_dir.is_dir():
                continue
            xml_file = obj_dir / f"{obj_dir.name}.xml"
            if not xml_file.exists():
                continue
            checked_files += 1
            text = _read_text(xml_file) or ""
            # Ищем Dimension блоки и в каждом — Leading
            for m in re.finditer(r"<Dimension[\s\S]*?</Dimension>", text):
                if re.search(r"<\s*Leading\b", m.group(0)):
                    # Достаём имя измерения для понятного сообщения
                    name_match = re.search(r"<Name>([^<]+)</Name>", m.group(0))
                    dim_name = name_match.group(1) if name_match else "<unnamed>"
                    rep.error(
                        f"17. {cat}/{obj_dir.name}/{obj_dir.name}.xml: Dimension «{dim_name}» "
                        f"содержит <Leading> — это свойство поддерживается только у "
                        f"InformationRegister.Dimension, в {cat[:-1]} вызывает ошибку загрузки"
                    )
                    if rep.stopped:
                        return

    if checked_files > 0 and not rep.stopped:
        rep.ok(f"17. Запрещённые свойства проверены: {checked_files} XML-файлов регистров")


# ── R18. '--' в XML-комментариях ────────────────────────────────────────────

def _check_xml_comments(ext_src: Path, rep: _Report) -> None:
    """В XML-комментариях (<!-- ... -->) запрещено двойное «--» —
    стандарт XML не позволяет. Это «грабля» автоматической вставки маркеров
    вида <!--cursor---> и т.п.
    """
    checked = 0
    bad: list[Path] = []
    for xml_file in ext_src.rglob("*.xml"):
        checked += 1
        text = _read_text(xml_file)
        if not text:
            continue
        # Ищем все XML-комментарии и проверяем, нет ли внутри них '--'
        # (кроме закрывающего '-->'). Используем нежадный поиск.
        for m in re.finditer(r"<!--(.*?)-->", text, re.DOTALL):
            inner = m.group(1)
            if "--" in inner:
                bad.append(xml_file)
                # Достаточно одного попадания на файл, чтобы не зашумлять
                break
        if rep.stopped:
            break

    for xml_file in bad:
        rep.error(
            f"18. {xml_file.relative_to(ext_src).as_posix()}: XML-комментарий содержит "
            f"двойной дефис «--» внутри (например, <!--cursor--->). Это нарушение XML "
            f"стандарта — конфигуратор выдаст «Double hyphen within comment». "
            f"Используй <!--cursor_end--> или удали маркер."
        )
        if rep.stopped:
            break

    if checked > 0 and not bad and not rep.stopped:
        rep.ok(f"18. XML-комментарии проверены: {checked} файлов")


# ── R19. Subsystems Content ─────────────────────────────────────────────────

def _check_subsystems(ext_src: Path, rep: _Report) -> None:
    """Если в расширении есть свои подсистемы (Subsystems/<Имя>.xml),
    то все ссылки в <Content><xr:Item xsi:type="xr:MDObjectRef">Type.Name</xr:Item>
    должны указывать на объекты, реально существующие в расширении или
    помеченные как заимствованные (Adopted).

    Проверка мягкая (WARN), потому что в Content могут быть ссылки и на
    объекты основной конфигурации — не имея SCHEME, точно сказать нельзя.
    """
    subs_dir = ext_src / "Subsystems"
    if not subs_dir.is_dir():
        return

    # Список объектов, реально существующих в расширении
    ext_objects: set[str] = set()
    for category, obj_dir in _iter_object_dirs(ext_src):
        # Из имени категории получаем тип в нотации Configuration.xml
        type_map = {
            "Catalogs": "Catalog", "Documents": "Document",
            "InformationRegisters": "InformationRegister",
            "AccumulationRegisters": "AccumulationRegister",
            "AccountingRegisters": "AccountingRegister",
            "CalculationRegisters": "CalculationRegister",
            "ChartsOfAccounts": "ChartOfAccounts",
            "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
            "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
            "Reports": "Report", "DataProcessors": "DataProcessor",
            "Enums": "Enum", "CommonModules": "CommonModule",
            "ExchangePlans": "ExchangePlan",
            "BusinessProcesses": "BusinessProcess", "Tasks": "Task",
        }
        type_name = type_map.get(category)
        if type_name:
            ext_objects.add(f"{type_name}.{obj_dir.name}")

    checked_subs = 0
    dangling: list[tuple[str, str]] = []  # (subsystem name, missing ref)

    for sub_xml in subs_dir.rglob("*.xml"):
        # Файл должен быть прямо в Subsystems/<Name>.xml (без подпапки Forms/Templates)
        if sub_xml.parent != subs_dir:
            continue
        text = _read_text(sub_xml)
        if not text or "<Content" not in text:
            continue
        checked_subs += 1
        # Ищем все ссылки внутри Content
        for m in re.finditer(
            r'<xr:Item[^>]*xsi:type="xr:MDObjectRef"[^>]*>([^<]+)</xr:Item>', text
        ):
            ref = m.group(1).strip()
            if not ref:
                continue
            # Если ссылка — на объект расширения, его должно быть в ext_objects.
            # Объекты основной конфигурации мы не валидируем (нет SCHEME под рукой).
            # Эвристика: если name начинается с того же префикса, что и расширение,
            # то это «наш» объект. Но определить префикс без явных данных трудно —
            # поэтому проверяем мягко: если refs нет в ext_objects, но он содержит
            # подстроку, похожую на префикс с подчёркиванием — это вероятно наш.
            if ref in ext_objects:
                continue
            # Heuristic: проверяем суффикс после точки на наличие префикса вида "пгт_"/"АП_"
            after_dot = ref.split(".", 1)[1] if "." in ref else ref
            if "_" in after_dot[:8]:
                # Похоже на наш объект, но его нет в расширении
                dangling.append((sub_xml.stem, ref))

    for sub_name, ref in dangling:
        rep.warn(
            f"19. Subsystems/{sub_name}.xml: Content содержит ссылку «{ref}», которой "
            f"нет в этом расширении. Если это ссылка на объект основной конфигурации — "
            f"игнорируй. Если предполагался свой объект — добавь его в ext_src."
        )

    if checked_subs > 0:
        rep.ok(f"19. Подсистемы проверены: {checked_subs}")


# ── Главная функция ─────────────────────────────────────────────────────────

def _check_xdto_structure(ext_src: Path, rep: _Report) -> None:
    """R20 — структура XML соответствует XDTO-схеме платформы 1С.

    Использует xml_validator.py с extension_mode=True (extension-specific теги
    и minOccurs переводятся из errors в warnings — расширение правомерно может
    не содержать обязательных детей основной конфигурации).
    """
    try:
        from xml_validator import validate_directory
    except ImportError as e:
        rep.warn(f"R20: xml_validator недоступен ({e})")
        return

    bulk = validate_directory(
        ext_src,
        max_files=None,
        max_errors_per_file=10,
        extension_mode=True,
    )

    rep.ok(
        f"R20 XDTO: проверено {bulk.checked_files} XML "
        f"({', '.join(f'{s}={n}' for s, n in bulk.by_schema.items())})"
    )

    if bulk.total_errors:
        rep.warn(
            f"R20: {bulk.files_with_errors} файлов с ошибками структуры "
            f"({bulk.total_errors} нарушений)"
        )
        # Покажем первые 3 файла с ошибками — детально
        shown = 0
        for file_path, errs in bulk.errors_by_file.items():
            if shown >= 3:
                break
            try:
                rel = Path(file_path).relative_to(ext_src)
            except ValueError:
                rel = Path(file_path).name
            for err in errs[:3]:
                rep.error(f"R20 {rel}: {err}")
            shown += 1

    if bulk.total_warnings:
        rep.warn(
            f"R20: {bulk.files_with_warnings} файлов с предупреждениями "
            f"({bulk.total_warnings} extension-specific нарушений — "
            f"допустимо для расширений)"
        )


def validate_extension_xml(ext_src_path: str, max_errors: int = 30) -> dict:
    """Запускает все дополнительные XML-проверки на папке расширения.

    Возвращает {errors, warnings, checks, text}.
    """
    ext_src = Path(ext_src_path)
    if not ext_src.is_dir():
        return {
            "errors": 1, "warnings": 0, "checks": 0,
            "text": (
                "=== XML extras: cannot run ===\n"
                f"[ERROR] Папка расширения не существует: {ext_src}"
            ),
        }

    rep = _Report(max_errors=max_errors)

    # Порядок: сначала самые частые/критичные, потом мягкие.
    #
    # R20 (_check_xdto_structure) УБРАН из обязательного пути валидации.
    # Причина: самодельная XDTO-валидация по портированным схемам (data/xsd/)
    # беднее платформы и даёт ложные срабатывания на штатных платформенных тегах
    # (доказано: InternalInfo/PropertyState — конфигуратор пишет сам, а схема его
    # не знает; db_load принимает блок без ошибок — airtight c2). Финальный арбитр
    # структуры — db_load самой 1С, не наша схема. Остаются лёгкие эвристики
    # R14–R19 на ИЗВЕСТНЫЕ грабли загрузки. XDTO-проверка доступна отдельным
    # on-demand op (ops_runner.validate_xdto). См. _inventory/validation-provenance-part2.md.
    checks = [
        _check_help_files,
        _check_dcs_templates,
        _check_forbidden_props,
        _check_xml_comments,
        _check_subsystems,
    ]
    for check_fn in checks:
        if rep.stopped:
            break
        try:
            check_fn(ext_src, rep)
        except Exception as e:
            rep.warn(f"Проверка {check_fn.__name__} упала: {e}")

    return {
        "errors":   rep.errors,
        "warnings": rep.warnings,
        "checks":   rep.checks,
        "text":     rep.render(),
    }


# Самостоятельный запуск (для отладки): python cfe_validate_xml.py <ext_src>
if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python cfe_validate_xml.py <ext_src_path>")
        sys.exit(2)
    res = validate_extension_xml(sys.argv[1])
    print(res["text"])
    sys.exit(1 if res["errors"] > 0 else 0)
