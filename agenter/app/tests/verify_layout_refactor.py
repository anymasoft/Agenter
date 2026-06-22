"""Проверка корректности рефакторинга UI: метаданные в левую, без quick commands."""
from pathlib import Path


def main() -> int:
    f = Path(r"D:\CURSORIC\agenter\agenter\frontend\chat-screen.jsx").read_text(encoding="utf-8")

    checks = [
        ("Sidebar has Metadata section", "Метаданные конфигурации" in f and "side-section" in f),
        ("MetadataTree in Sidebar", "<MetadataTree config={config}" in f),
        ("Quick Commands removed", "Быстрые команды" not in f),
        ("Metadata mentioned exactly once", f.count("Метаданные конфигурации") == 1),
        ("History capped to maxHeight 200", "maxHeight: 200" in f),
        ("No leftover Quick references", "quick-grid" not in f and "quick-row" not in f),
    ]
    failed = 0
    for name, ok in checks:
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {name}")
        if not ok:
            failed += 1

    rb_sections = f.count('className="rb-section"')
    side_sections = f.count('className="side-section"')
    print(f"\n  RightPanel sections: {rb_sections} (was 5, target 3)")
    print(f"  Sidebar sections:    {side_sections} (was 2, target 3)")
    print(f"  File size:           {len(f) // 1024} KB")

    return failed


if __name__ == "__main__":
    import sys
    sys.exit(main())
