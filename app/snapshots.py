"""
agenter/app/snapshots.py — снапшоты ext_src для отката после неуспешных задач.

При начале новой сессии (первая задача после reset) делаем zip ext_src/ в
agenter/data/<project_id>/snapshots/<task_id>_<ts>.zip. Этот zip живёт всю
сессию и позволяет:

  • Восстановить ext_src/ к состоянию ДО задачи (если что-то пошло не так)
  • Сравнить diff между задачами в одной сессии (для дебага)

Snapshot не включает БД 1С — БД и так нетронута пока агент не вызвал db_load.
Если фазы успешно committed, БД содержит частичный результат, и rollback
ext_src/ из snapshot НЕ откатит БД. Это намеренно: пользователь сам решает,
хочет ли он откатить БД через дополнительный db_load после восстановления.

TTL и лимиты:
  • Не больше MAX_SNAPSHOTS_PER_PROJECT снапшотов на проект (старые удаляются)
  • Старше SNAPSHOT_TTL_DAYS дней — auto-cleanup при создании нового
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# Лимиты — простые константы, при необходимости вынесем в config.json.
MAX_SNAPSHOTS_PER_PROJECT = 5
SNAPSHOT_TTL_DAYS         = 7

# Файлы и папки, которые НЕ нужно класть в snapshot (мусор, бэкапы и .git).
# Регистронезависимое сравнение, паттерн матчится по имени файла/папки.
_EXCLUDE_NAMES = {
    ".git", ".vscode", ".idea",
    "__pycache__", "node_modules",
    "thumbs.db", ".ds_store",
}
_EXCLUDE_SUFFIXES = {".bak", ".tmp", ".swp"}


def _agenter_data_dir(app_dir: Path) -> Path:
    """agenter/data/ — корневая папка для пользовательских данных (memory, snapshots).
    app_dir — папка agenter/app/, она же __file__.parent главного main.py."""
    return app_dir.parent / "data"


def snapshots_dir(app_dir: Path, project_id: str) -> Path:
    """agenter/data/<project_id>/snapshots/ — куда складываем zip."""
    return _agenter_data_dir(app_dir) / project_id / "snapshots"


def _should_skip(path: Path) -> bool:
    name_lc = path.name.lower()
    if name_lc in _EXCLUDE_NAMES:
        return True
    if path.suffix.lower() in _EXCLUDE_SUFFIXES:
        return True
    return False


def create_snapshot(
    ext_src_path: str | Path,
    app_dir: Path,
    project_id: str,
    task_id: str,
) -> Path | None:
    """Создаёт zip ext_src/ → snapshots/<task_id>_<ts>.zip.

    Returns:
        Path к созданному zip, или None если ext_src/ не существует / пуст
        (тогда snapshot не нужен — откатывать нечего).

    Не бросает исключения внутрь caller'а — все ошибки логируются как warning.
    Если snapshot не создался, задача всё равно должна запуститься (без отката).
    """
    src = Path(ext_src_path)
    if not src.is_dir():
        log.info("snapshot: ext_src %s не существует, snapshot не нужен", src)
        return None

    # Папка снапшотов проекта
    snaps_root = snapshots_dir(app_dir, project_id)
    snaps_root.mkdir(parents=True, exist_ok=True)

    # Auto-cleanup перед созданием нового — освобождаем место
    try:
        _cleanup_old_snapshots(snaps_root)
    except Exception as e:
        log.warning("snapshot: cleanup failed (продолжаем): %s", e)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out = snaps_root / f"{task_id}_{ts}.zip"

    files_added = 0
    try:
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in src.rglob("*"):
                if _should_skip(p):
                    continue
                # Пропускаем директории (zip их не нужен, файлы внутри добавятся сами).
                # Пустые директории в zip не сохраняем — при restore'е они и так
                # создадутся через mkdir() при записи первого файла.
                if p.is_dir():
                    continue
                # Проверяем не лежит ли файл в исключённой папке выше по дереву
                if any(part in _EXCLUDE_NAMES for part in p.parts):
                    continue
                try:
                    arcname = p.relative_to(src)
                    zf.write(p, arcname)
                    files_added += 1
                except Exception as e:
                    log.warning("snapshot: пропускаю %s: %s", p, e)
    except Exception as e:
        log.warning("snapshot: ошибка создания %s: %s", out, e)
        # Подчищаем частично созданный zip
        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    if files_added == 0:
        # ext_src/ есть, но пустой — нет смысла хранить пустой zip
        out.unlink(missing_ok=True)
        log.info("snapshot: ext_src пуст, snapshot не создан")
        return None

    size_kb = out.stat().st_size // 1024
    log.info("snapshot: создан %s (%d файлов, %d KB)", out, files_added, size_kb)
    return out


def restore_snapshot(
    snapshot_path: str | Path,
    ext_src_path: str | Path,
) -> dict:
    """Восстанавливает ext_src/ из zip. Текущее содержимое ext_src/ ПОЛНОСТЬЮ
    стирается перед распаковкой — это операция «вернуть к состоянию из zip».

    Returns:
        dict с полями ok, files_restored, error (если ok=False)

    БД 1С не трогается. После restore'а юзер может вручную сделать db_load
    из UI, чтобы откатить и БД до состояния snapshot'а.
    """
    snap = Path(snapshot_path)
    dst  = Path(ext_src_path)
    if not snap.is_file():
        return {"ok": False, "error": f"snapshot не найден: {snap}"}

    # Полная очистка ext_src/ (только то что внутри, саму папку оставляем)
    if dst.exists():
        for item in dst.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                return {"ok": False, "error": f"не удалось очистить {item}: {e}"}
    else:
        dst.mkdir(parents=True, exist_ok=True)

    files_restored = 0
    try:
        with zipfile.ZipFile(snap, "r") as zf:
            zf.extractall(dst)
            files_restored = len(zf.namelist())
    except Exception as e:
        return {"ok": False, "error": f"распаковка упала: {e}"}

    log.info("snapshot: restored %d файлов из %s в %s", files_restored, snap, dst)
    return {"ok": True, "files_restored": files_restored}


def delete_snapshot(snapshot_path: str | Path) -> bool:
    """Тихое удаление файла снапшота. True если удалили, False если нечего удалять."""
    p = Path(snapshot_path) if snapshot_path else None
    if not p or not p.is_file():
        return False
    try:
        p.unlink()
        return True
    except Exception as e:
        log.warning("snapshot: не удалось удалить %s: %s", p, e)
        return False


def _cleanup_old_snapshots(snaps_dir: Path) -> None:
    """Удаляет снапшоты старше TTL и снапшоты сверх лимита.

    Стратегия:
      1. Сначала удаляем по TTL — всё старше SNAPSHOT_TTL_DAYS дней
      2. Если осталось > MAX_SNAPSHOTS_PER_PROJECT — удаляем самые старые
         пока не уложимся в лимит.
    """
    if not snaps_dir.is_dir():
        return
    cutoff = datetime.utcnow() - timedelta(days=SNAPSHOT_TTL_DAYS)
    files = []
    for p in snaps_dir.iterdir():
        if p.is_file() and p.suffix == ".zip":
            mtime = datetime.utcfromtimestamp(p.stat().st_mtime)
            files.append((mtime, p))

    # TTL-удаление
    for mtime, p in files:
        if mtime < cutoff:
            try:
                p.unlink()
                log.info("snapshot: TTL cleanup, удалён %s", p)
            except Exception as e:
                log.warning("snapshot: не удалось удалить %s: %s", p, e)
    # Перечитываем список после TTL
    files = [(datetime.utcfromtimestamp(p.stat().st_mtime), p)
             for p in snaps_dir.iterdir() if p.is_file() and p.suffix == ".zip"]
    files.sort(key=lambda x: x[0])  # старые в начале

    # Лимит-удаление: оставляем последние MAX_SNAPSHOTS_PER_PROJECT
    excess = len(files) - MAX_SNAPSHOTS_PER_PROJECT
    if excess > 0:
        for mtime, p in files[:excess]:
            try:
                p.unlink()
                log.info("snapshot: limit cleanup, удалён %s", p)
            except Exception as e:
                log.warning("snapshot: не удалось удалить %s: %s", p, e)


def memory_md_path(app_dir: Path, project_id: str) -> Path:
    """Путь к MEMORY.md проекта. Файл может не существовать — это нормально,
    создаётся агентом при первой записи через Edit/Write."""
    return _agenter_data_dir(app_dir) / project_id / "MEMORY.md"


def load_memory_md(app_dir: Path, project_id: str, max_chars: int = 50000) -> str:
    """Читает MEMORY.md если он есть. Возвращает '' если файл отсутствует/пуст.

    max_chars — защита от бесконтрольного разрастания: если файл больше,
    обрезаем хвост (новые записи скорее всего в конце, но мы берём ГОЛОВУ —
    там обычно фундаментальные факты проекта). При срабатывании добавляем
    предупреждение в конце для агента.
    """
    p = memory_md_path(app_dir, project_id)
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        log.warning("MEMORY.md read failed: %s", e)
        return ""
    if len(text) > max_chars:
        return (
            text[:max_chars]
            + f"\n\n[...MEMORY.md обрезан: было {len(text)} символов, "
              f"показано {max_chars}. Сделай compact через Edit.]"
        )
    return text


def append_memory_md(
    app_dir: Path,
    project_id: str,
    line: str,
) -> None:
    """Sprint 2 S2.5: добавляет одну строку в MEMORY.md проекта.

    Используется backend'ом для автозаписи факта phase_commit (или другого
    значимого события) — чтобы при resume следующей задачи агент видел в
    своей памяти что было сделано раньше, без необходимости лезть в БД задач.

    Файл создаётся при первой записи. Каждая строка — самостоятельный факт.
    Время в UTC ISO-формате (без секунд, чтобы было компактно).
    """
    if not line or not line.strip():
        return
    try:
        p = memory_md_path(app_dir, project_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        # ISO без миллисекунд: «2026-05-16T17:42»
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M")
        entry = f"- {ts} · {line.strip()}\n"
        # Если файла нет — создаём с маленьким заголовком (помогает агенту понять контекст)
        if not p.exists():
            header = (
                "# MEMORY.md\n"
                "\n"
                "Долговременная память проекта. Каждая строка — факт о том что было сделано.\n"
                "Автозаписи делает Agenter (после каждого успешного db_load). Агент может\n"
                "дополнять файл через Edit, если нужно зафиксировать архитектурное решение.\n"
                "\n"
                "## Хроника\n"
                "\n"
            )
            p.write_text(header + entry, encoding="utf-8")
        else:
            with p.open("a", encoding="utf-8") as f:
                f.write(entry)
    except Exception as e:
        log.warning("append_memory_md failed: %s", e)
