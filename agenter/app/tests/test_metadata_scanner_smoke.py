"""Smoke-тест metadata_scanner на реальной SCHEME."""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

# Чтобы запускать как python app/tests/test_metadata_scanner_smoke.py
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from metadata_utils import decode_1c_unicode_escapes, scan_metadata_root  # noqa: E402


def main() -> int:
    sample = "#U041F#U0440#U0438#U043C#U0435#U0440"
    decoded = decode_1c_unicode_escapes(sample)
    print(f"[unicode] {sample!r} -> {decoded!r}")
    assert decoded == "Пример", f"expected 'Пример', got {decoded!r}"

    scheme_root = Path(r"D:\CURSORIC\agenter\SCHEME")
    if not scheme_root.exists():
        print(f"[scanner] SCHEME not found at {scheme_root} — skipping")
        return 0

    t0 = time.time()
    result = scan_metadata_root(scheme_root)
    elapsed = time.time() - t0

    by_type: Counter[str] = Counter(r.object_type_dir for r in result.objects)
    total = len(result.objects)
    print(f"[scanner] elapsed={elapsed:.2f}s, total={total}, errors={len(result.errors)}")
    print("[scanner] top types:")
    for type_name, n in by_type.most_common(20):
        print(f"    {type_name:30s} {n:>6d}")

    with_predef = sum(1 for r in result.objects if r.predefined_xml_path)
    with_ext = sum(1 for r in result.objects if r.ext_xml_paths)
    print(f"[scanner] objects with Predefined.xml: {with_predef}")
    print(f"[scanner] objects with Ext XMLs: {with_ext}")

    # Покажем первые 3 предопределённых
    samples_with_pre = [r for r in result.objects if r.predefined_xml_path][:3]
    for s in samples_with_pre:
        print(f"    [predef] {s.object_type_dir}/{s.display_name}  -> {s.predefined_xml_path}")

    if result.errors:
        print("[scanner] first 5 errors:")
        for e in result.errors[:5]:
            print(f"    {e}")

    # Порог не привязан к размеру конкретной конфигурации: любая реальная
    # SCHEME даёт десятки+ объектов без ошибок сканирования.
    assert total > 50, f"expected >50 objects from a real SCHEME, got {total}"
    assert not result.errors, f"scanner reported {len(result.errors)} errors"
    print("[OK] smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
