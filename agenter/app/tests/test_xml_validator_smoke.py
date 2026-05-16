"""Smoke-тест xml_validator на ext_src."""
from __future__ import annotations

import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from xml_validator import (  # noqa: E402
    list_available_schemas,
    validate_directory,
    validate_xml_file,
)


def main() -> int:
    # 1. Какие схемы доступны?
    schemas = list_available_schemas()
    print(f"[schemas] available: {len(schemas)} — {schemas}")
    assert "metadata" in schemas
    assert "form" in schemas
    assert "dcs" in schemas

    # 2. Один объект из ext_src
    ext_root = Path(r"C:\BUFFER\ERP\ext_src")
    if not ext_root.exists():
        print(f"[ext_src] not found at {ext_root}, falling back to SCHEME")
        ext_root = Path(r"C:\BUFFER\ERP\SCHEME")
        if not ext_root.exists():
            return 0

    # Найдём первый Catalog.xml или Document.xml
    candidates = list(ext_root.rglob("*.xml"))
    catalog_xml = next(
        (c for c in candidates if "Catalogs" in c.parts and c.name == c.parent.name + ".xml"),
        None,
    )
    document_xml = next(
        (c for c in candidates if "Documents" in c.parts and c.name == c.parent.name + ".xml"),
        None,
    )

    samples = [c for c in [catalog_xml, document_xml] if c is not None][:3]

    for sample in samples:
        print(f"\n[test] validating {sample.name}")
        res = validate_xml_file(sample)
        print(f"  schema={res.schema_name} valid={res.valid} "
              f"errors={len(res.errors)} warnings={len(res.warnings)}")
        if res.errors:
            for e in res.errors[:3]:
                print(f"    [err] {e}")

    # 3. Bulk-валидация всего ext_src в extension-режиме
    print(f"\n[bulk] validating all XMLs in {ext_root} (extension_mode=True)")
    t0 = time.time()
    bulk = validate_directory(ext_root, max_files=2000, extension_mode=True)
    elapsed = time.time() - t0
    print(
        f"[bulk] checked={bulk.checked_files} ({elapsed:.2f}s), "
        f"with_errors={bulk.files_with_errors}, total_errors={bulk.total_errors}"
    )
    print(f"[bulk] by_schema:")
    for s, n in sorted(bulk.by_schema.items(), key=lambda x: -x[1]):
        print(f"    {s:15s} {n:>4d}")

    # Покажем первые 3 файла с ошибками
    if bulk.errors_by_file:
        print(f"\n[bulk] first 3 files with errors:")
        for file_path, errs in list(bulk.errors_by_file.items())[:3]:
            print(f"  {file_path}")
            for e in errs[:3]:
                print(f"    {e}")

    print("\n[OK] smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
