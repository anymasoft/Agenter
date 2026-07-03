"""
Фаза 2 / Шаг 2.2 — Уровень 2 синхронизации: авто-сверка перед задачей (net-new).

Заменяет снятый в Шаге 2.1 инвариант «ВСЕГДА синхронизируй» на «синхронизируй,
КОГДА реально изменилось». Перед задачей дёшево сверяем текущий
ConfigDumpInfo.xml базы (в `scheme_path`) с сохранённым baseline-снимком прошлой
синхронизации (через `base_change_detector`, Фаза 1):

  • не менялось  → выгрузка/переиндексация не нужны, задача стартует мгновенно;
  • менялось     → возвращаем список изменившихся объектов для инкрементальной
                   переиндексации (reindex force=False) — полная выгрузка не нужна;
  • нет baseline → первый запуск, рекомендуем полную выгрузку (нечего сравнивать).

Принцип Р4: истина на чтение = реальная база (её per-object configVersion-штампы
в ConfigDumpInfo.xml), а НЕ записанная память. Baseline-снимок обновляется
`update_baseline()` после успешной синхронизации.

Граница интеграции (живая 1С): сам запуск `-Mode UpdateInfo` (обновить штамп) и
`reindex` (применить) делает `ops_runner` против настоящей базы. Здесь — чистая
решающая логика + хранение baseline. Это позволяет проверить РЕШЕНИЕ
детерминированно (без 1С), а запуск против живой базы — это уже интеграция.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import base_change_detector as _bcd

CONFIG_DUMP_INFO_NAME = _bcd.CONFIG_DUMP_INFO_NAME  # "ConfigDumpInfo.xml"

# Действия, которые может вернуть решающая логика.
ACTION_SKIP = "skip"        # база не менялась — ничего не делаем
ACTION_REINDEX = "reindex"  # база менялась — инкрементальная переиндексация
ACTION_FULL = "full"        # нет baseline (первый запуск) — полная выгрузка


def baseline_path(app_dir: str | Path, project_id: str) -> Path:
    """Куда кладём baseline-снимок ConfigDumpInfo базы для проекта.

    Хранится отдельно от scheme_path (тот перезаписывается выгрузкой), чтобы
    пережить db_dump и служить «последним известным синхронизированным
    состоянием»."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(project_id))
    return Path(app_dir) / "base_sync" / f"{safe}_ConfigDumpInfo.xml"


def current_config_dump_info(scheme_path: str | Path) -> Path:
    """ConfigDumpInfo.xml основной конфигурации лежит в каталоге выгрузки SCHEME."""
    return Path(scheme_path) / CONFIG_DUMP_INFO_NAME


def decide_pre_task_sync(
    baseline: str | Path,
    current: str | Path,
) -> dict:
    """Решает, что делать перед задачей, сравнив baseline-снимок с текущим
    ConfigDumpInfo базы. Чистая логика — без запуска 1С.

    Возвращает:
      {
        "action": "skip" | "reindex" | "full",
        "reason": <человекочитаемо>,
        "changed_objects": [...],   # только для reindex
        "counts": {...},            # агрегаты diff (для reindex/full)
      }
    """
    baseline_p = Path(baseline)
    current_p = Path(current)

    # Нет текущего штампа — сверять не с чем. Не форсим выгрузку: пусть работает
    # с тем, что есть (агент/кнопка «Синхронизировать» доступны вручную).
    if not current_p.is_file():
        return {
            "action": ACTION_SKIP,
            "reason": "ConfigDumpInfo базы отсутствует — нечего сверять, "
                      "старт без выгрузки (синхронизировать можно вручную кнопкой)",
            "changed_objects": [],
            "counts": {},
        }

    # Нет baseline — первый запуск для проекта. Сравнивать не с чем →
    # рекомендуем полную выгрузку, чтобы появилась точка отсчёта.
    if not baseline_p.is_file():
        cur = _bcd.parse_config_dump_info(current_p)
        return {
            "action": ACTION_FULL,
            "reason": f"baseline-снимок отсутствует (первая синхронизация проекта): "
                      f"рекомендуется полная выгрузка, текущая база — {len(cur)} объектов",
            "changed_objects": [],
            "counts": {"current_objects": len(cur)},
        }

    diff = _bcd.detect_changes(baseline_p, current_p)
    if not diff["any"]:
        return {
            "action": ACTION_SKIP,
            "reason": "база не менялась с прошлой синхронизации — выгрузка не нужна, "
                      "старт мгновенный",
            "changed_objects": [],
            "counts": diff["counts"],
        }

    return {
        "action": ACTION_REINDEX,
        "reason": (
            "база менялась: "
            f"изменено {diff['counts']['changed']}, "
            f"добавлено {diff['counts']['added']}, "
            f"удалено {diff['counts']['removed']} "
            f"(объектов затронуто: {diff['counts']['objects']}) — "
            "нужна инкрементальная переиндексация"
        ),
        "changed_objects": diff["changed_objects"],
        "counts": diff["counts"],
    }


def update_baseline(current: str | Path, app_dir: str | Path, project_id: str) -> Path | None:
    """Сохраняет текущий ConfigDumpInfo базы как новый baseline-снимок проекта.
    Вызывается ПОСЛЕ успешной синхронизации (db_dump/reindex). Возвращает путь
    сохранённого снимка либо None, если текущего файла нет."""
    current_p = Path(current)
    if not current_p.is_file():
        return None
    dest = baseline_path(app_dir, project_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current_p, dest)
    return dest
