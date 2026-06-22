"""Smoke-тест role_parser и subsystem_membership на SCHEME."""
from __future__ import annotations

import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from metadata_utils.role_parser import (  # noqa: E402
    has_right,
    list_objects_with_full_access,
    list_rls_objects,
    parse_role_rights_xml,
)
from metadata_utils.subsystem_membership import (  # noqa: E402
    enumerate_subsystem_xml_files,
    extract_content_md_refs,
    find_subsystems_for_object,
    list_subsystem_content,
    load_subsystem_membership,
)


def main() -> int:
    scheme = Path(r"D:\CURSORIC\agenter\SCHEME")
    if not scheme.exists():
        print("[smoke] SCHEME not found - skipping")
        return 0

    # 1. Role parser
    print("[roles] looking for Rights.xml...")
    role_files = list(scheme.glob("Roles/*/Ext/Rights.xml"))[:5]
    print(f"[roles] found {len(role_files)} candidates")
    for role_xml in role_files[:2]:
        t0 = time.time()
        try:
            parsed = parse_role_rights_xml(role_xml)
            elapsed = (time.time() - t0) * 1000
            full_access = list_objects_with_full_access(parsed)
            rls = list_rls_objects(parsed)
            print(f"  {role_xml.parent.parent.name} ({elapsed:.0f}ms): "
                  f"{len(parsed.objects)} objects, "
                  f"{len(full_access)} full-access, "
                  f"{len(rls)} RLS, "
                  f"{len(parsed.restriction_templates)} templates")
            if parsed.objects:
                first = parsed.objects[0]
                print(f"    sample: {first.name} ({len(first.rights)} rights, "
                      f"e.g. Read={has_right(parsed, first.name, 'Read')})")
        except Exception as e:
            print(f"  FAIL {role_xml}: {e}")

    # 2. Subsystem files enumeration
    print("\n[subsystems] enumerating Subsystems/")
    t0 = time.time()
    sub_files = enumerate_subsystem_xml_files(scheme)
    print(f"[subsystems] {len(sub_files)} files in {(time.time()-t0)*1000:.0f}ms")
    for f in sub_files[:3]:
        try:
            rel = f.relative_to(scheme).as_posix()
        except ValueError:
            rel = f.name
        print(f"  {rel}")

    # 3. Найдём какой-нибудь объект для теста
    catalog_dirs = list((scheme / "Catalogs").iterdir())[:3]
    if catalog_dirs:
        sample = catalog_dirs[0]
        md_ref = f"Catalog.{sample.name}"
        print(f"\n[subsystems] looking for object: {md_ref}")
        t1 = time.time()
        rows = find_subsystems_for_object(scheme, md_ref)
        print(f"[subsystems] {md_ref} входит в {len(rows)} подсистем "
              f"за {(time.time()-t1)*1000:.0f}ms")
        for r in rows[:5]:
            print(f"  - {r.label} ({r.rel_path})")

    # 4. Content одной подсистемы
    if sub_files:
        first_sub = sub_files[0].relative_to(scheme).as_posix()
        content = list_subsystem_content(scheme, first_sub)
        print(f"\n[subsystems] {first_sub}: {len(content)} объектов в Content")
        for ref in content[:5]:
            print(f"  - {ref}")

    print("\n[OK] smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
