"""
Фаза 1 / Шаг 1.4 — детектор изменений базы через ConfigDumpInfo.xml (net-new).

1С хранит per-object штамп версии в `ConfigDumpInfo.xml`
(`<Metadata name="…" configVersion="…">`) — это её родной механизм для
инкрементальной выгрузки. Сравнив сохранённый снимок штампа с текущим, получаем
ДЁШЕВО (без полной выгрузки): менялась ли база и ЧТО именно изменилось.

В Фазе 1 — ТОЛЬКО детектор (сигнал «менялось/нет» + список объектов).
Авто-реакцию (переиндексация Level-2) и кнопку «Синхронизировать» — в Фазу 2.

Дешёвое обновление самого штампа делает `db-dump-xml.ps1 -Mode UpdateInfo`
(уже используется в `ops_runner.test_1c_auth`) — он переписывает только
ConfigDumpInfo.xml. Здесь — парсинг и diff; запуск UpdateInfo против реальной
базы оставлен интеграции (Фаза 2), т.к. требует живой 1С.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

CONFIG_DUMP_INFO_NAME = "ConfigDumpInfo.xml"


def parse_config_dump_info(path: str | Path) -> dict[str, str]:
    """Возвращает плоскую карту {имя_объекта: configVersion} для всех Metadata
    (на любой глубине вложенности), у которых есть configVersion.

    Узлы без configVersion (Dimension/Resource внутри объекта) пропускаются —
    у них штамп наследуется от родителя и в diff не нужен."""
    p = Path(path)
    result: dict[str, str] = {}
    if not p.is_file():
        return result
    tree = ET.parse(str(p))
    for el in tree.getroot().iter():
        tag = el.tag.split("}")[-1]  # отбрасываем namespace
        if tag == "Metadata":
            name = el.get("name")
            cv = el.get("configVersion")
            if name and cv:
                result[name] = cv
    return result


def _top_object(name: str) -> str:
    """Сводит подробное имя к объекту 1С: первые два сегмента
    'AccumulationRegister.Взаиморасчеты.Form.X' → 'AccumulationRegister.Взаиморасчеты'."""
    parts = name.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else name


def diff_versions(old: dict[str, str], new: dict[str, str]) -> dict:
    """Diff двух карт штампов. Возвращает changed/added/removed + агрегат по
    объектам + флаг any."""
    old_keys, new_keys = set(old), set(new)
    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    changed = sorted(k for k in (old_keys & new_keys) if old[k] != new[k])
    objects = sorted({_top_object(n) for n in (changed + added + removed)})
    return {
        "any": bool(added or removed or changed),
        "changed": changed,
        "added": added,
        "removed": removed,
        "changed_objects": objects,
        "counts": {"changed": len(changed), "added": len(added),
                   "removed": len(removed), "objects": len(objects)},
    }


def detect_changes(baseline_path: str | Path, current_path: str | Path) -> dict:
    """Сравнивает сохранённый снимок ConfigDumpInfo.xml с текущим.
    baseline отсутствует → всё в current трактуется как 'added' (первый запуск)."""
    old = parse_config_dump_info(baseline_path)
    new = parse_config_dump_info(current_path)
    res = diff_versions(old, new)
    res["baseline_objects"] = len(old)
    res["current_objects"] = len(new)
    return res


def config_dump_info_path(ext_src_path: str | Path) -> Path:
    """ConfigDumpInfo.xml лежит в каталоге выгрузки (ConfigDir = ext_src)."""
    return Path(ext_src_path) / CONFIG_DUMP_INFO_NAME
