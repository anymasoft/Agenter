"""Smoke-тест metadata_parser на 10 случайных объектах SCHEME."""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from metadata_utils import scan_metadata_root  # noqa: E402
from metadata_utils.metadata_parser import parse_metadata_object  # noqa: E402
from metadata_utils.metadata_types import (  # noqa: E402
    get_bsl_ref_type,
    get_display_name_by_dir,
)
from metadata_utils.predefined_parser import parse_predefined_xml  # noqa: E402


def main() -> int:
    scheme_root = Path(r"D:\CURSORIC\agenter\SCHEME")
    if not scheme_root.exists():
        print("[parser] SCHEME not found — skipping")
        return 0

    print("[scan] starting...")
    t0 = time.time()
    scan = scan_metadata_root(scheme_root)
    print(f"[scan] {len(scan.objects)} objects in {time.time()-t0:.2f}s")

    # Берём по 2 объекта из основных типов
    interesting = {"Catalogs", "Documents", "AccumulationRegisters", "InformationRegisters", "Enums"}
    by_type: dict[str, list] = {}
    for ref in scan.objects:
        if ref.object_type_dir in interesting:
            by_type.setdefault(ref.object_type_dir, []).append(ref)

    samples = []
    for type_dir, refs in by_type.items():
        random.seed(42)
        chosen = random.sample(refs, min(2, len(refs)))
        samples.extend(chosen)

    print(f"\n[parser] parsing {len(samples)} samples...")
    total_members = 0
    total_attrs = 0
    total_tabular = 0
    t1 = time.time()

    for ref in samples:
        try:
            obj = parse_metadata_object(ref)
            n_attrs = len(obj.attributes)
            n_tab = len(obj.tabular_sections)
            n_forms = len(obj.forms)
            n_cmd = len(obj.commands)
            n_predef = 0
            if ref.predefined_xml_path:
                predef = parse_predefined_xml(ref.predefined_xml_path)
                obj.predefined = predef
                n_predef = len(predef)

            total_members += len(obj.members)
            total_attrs += n_attrs
            total_tabular += n_tab

            print(
                f"  [{obj.object_type:25s}] {obj.display_name[:40]:40s} "
                f"attrs={n_attrs:>3d} tabs={n_tab:>2d} forms={n_forms:>2d} "
                f"cmd={n_cmd:>2d} predef={n_predef:>2d}"
            )
        except Exception as e:
            print(f"  FAIL {ref.main_xml_path}: {e}")
            return 1

    elapsed = time.time() - t1
    print(
        f"\n[parser] OK {len(samples)} objects in {elapsed:.2f}s "
        f"({len(samples)/elapsed:.0f} obj/s)"
    )
    print(
        f"        total_members={total_members}, attrs={total_attrs}, "
        f"tabular_sections={total_tabular}"
    )

    # Проверка metadata_types
    print("\n[types] sanity check:")
    samples = ["CatalogRef", "DocumentRef", "AccumulationRegisterRef", "EnumRef"]
    for s in samples:
        print(f"  {s} -> {get_bsl_ref_type(s)}")
    print(f"  display 'Catalogs' -> {get_display_name_by_dir('Catalogs')!r}")
    print(f"  display 'Documents' -> {get_display_name_by_dir('Documents')!r}")

    print("\n[OK] all smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
