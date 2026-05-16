"""
Финальный smoke-тест всего pipeline:
    1. metadata_utils пакет: scanner + parser + types
    2. xml_validator: 27 XDTO-схем
    3. cfe_validate_xml: R20 интегрирован
    4. ops_runner: validate_xdto
    5. main.py: /metadata/* эндпоинты + регистрация validate-xdto
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))


def main() -> int:
    failed = 0

    # 1. metadata_utils пакет
    print("=== 1. metadata_utils package ===")
    try:
        from metadata_utils import (  # noqa: F401
            MetadataFileRef,
            ScanResult,
            decode_1c_unicode_escapes,
            scan_metadata_root,
        )
        from metadata_utils.metadata_parser import parse_metadata_object  # noqa: F401
        from metadata_utils.metadata_repository import MetadataRepository, MetadataTreeNode  # noqa: F401
        from metadata_utils.metadata_types import (  # noqa: F401
            METADATA_TYPES,
            all_bsl_mappings,
            get_bsl_ref_type,
        )
        from metadata_utils.predefined_parser import parse_predefined_xml  # noqa: F401
        from metadata_utils.role_parser import parse_role_rights_xml  # noqa: F401
        from metadata_utils.subsystem_membership import (  # noqa: F401
            find_subsystems_for_object,
            load_subsystem_membership,
        )

        print(f"  [OK] all imports work")
        print(f"  [OK] METADATA_TYPES: {len(METADATA_TYPES)} types")
        print(f"  [OK] BSL mappings: {len(all_bsl_mappings())} entries")
        print(f"  [OK] CatalogRef -> {get_bsl_ref_type('CatalogRef')}")
        assert get_bsl_ref_type("CatalogRef") == "СправочникСсылка"
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # 2. XDTO-схемы
    print("\n=== 2. XDTO schemas ===")
    try:
        from xml_validator import list_available_schemas

        schemas = list_available_schemas()
        print(f"  [OK] {len(schemas)} schemas: {schemas}")
        assert "metadata" in schemas
        assert "form" in schemas
        assert "dcs" in schemas
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # 3. field_values.json
    print("\n=== 3. field_values.json ===")
    try:
        import json

        fv_path = APP_DIR / "data" / "field_values.json"
        assert fv_path.exists(), f"not found: {fv_path}"
        data = json.loads(fv_path.read_text(encoding="utf-8"))
        for key in ("FIELD_VALUES", "FIELD_LABELS", "ENUM_VALUE_LABELS"):
            assert key in data, f"missing {key}"
            print(f"  [OK] {key}: {len(data[key])} entries")
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # 4. cfe_validate_xml с R20
    print("\n=== 4. cfe_validate_xml (R20 integrated) ===")
    try:
        from cfe_validate_xml import _check_xdto_structure, validate_extension_xml

        # Smoke-вызов на ext_src
        ext_src = Path(r"C:\BUFFER\ERP\ext_src")
        if ext_src.exists():
            res = validate_extension_xml(str(ext_src))
            print(f"  [OK] validate_extension_xml: errors={res['errors']}, warnings={res['warnings']}, checks={res['checks']}")
            assert "XDTO" in res["text"], "R20 not in output"
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # 5. ops_runner.validate_xdto
    print("\n=== 5. ops_runner.validate_xdto ===")
    try:
        from ops_runner import validate_xdto

        print(f"  [OK] validate_xdto registered: {validate_xdto}")
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # 6. main.py роуты + validate-xdto в SUPPORTED_OPS
    print("\n=== 6. main.py routes ===")
    try:
        import main as agenter_main

        paths = sorted(
            r.path for r in agenter_main.app.routes
            if hasattr(r, "path") and (r.path.startswith("/metadata") or "/ops/" in r.path)
        )
        for p in paths:
            print(f"  {p}")

        assert "/metadata/tree" in paths
        assert "/metadata/tree/stream" in paths
        assert "/metadata/object" in paths
        assert "/metadata/invalidate" in paths
        assert "validate-xdto" in agenter_main.SUPPORTED_OPS
        print(f"  [OK] validate-xdto in SUPPORTED_OPS: {agenter_main.SUPPORTED_OPS}")
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    # 7. Frontend файлы
    print("\n=== 7. Frontend files ===")
    try:
        frontend_dir = APP_DIR.parent / "frontend"
        for f in ["metadata-tree.jsx", "api.js", "chat-screen.jsx", "app.html"]:
            full = frontend_dir / f
            assert full.exists(), f"missing: {full}"
            print(f"  [OK] {f} ({full.stat().st_size // 1024} KB)")

        # Иконки
        icons_dark = frontend_dir / "assets" / "icons" / "dark"
        icons_light = frontend_dir / "assets" / "icons" / "light"
        assert icons_dark.exists(), "icons/dark missing"
        assert icons_light.exists(), "icons/light missing"
        n_dark = len(list(icons_dark.glob("*.svg")))
        n_light = len(list(icons_light.glob("*.svg")))
        print(f"  [OK] dark icons: {n_dark}")
        print(f"  [OK] light icons: {n_light}")
        assert n_dark > 40 and n_light > 40

        # XSLT
        xslt_dir = frontend_dir / "assets" / "xslt"
        n_xsl = len(list(xslt_dir.rglob("*.xsl")))
        print(f"  [OK] xslt templates: {n_xsl}")

        # Проверяем что metadata-tree.jsx подключён в app.html
        html = (frontend_dir / "app.html").read_text(encoding="utf-8")
        assert "metadata-tree.jsx" in html, "metadata-tree.jsx not registered in app.html"
        print(f"  [OK] metadata-tree.jsx registered in app.html")

        # Проверяем что AgenterAPI имеет новые методы
        api_js = (frontend_dir / "api.js").read_text(encoding="utf-8")
        for method in ("getMetadataTree", "getMetadataObject", "invalidateMetadata", "streamMetadataTree"):
            assert method in api_js, f"missing method: {method}"
        print(f"  [OK] AgenterAPI methods: getMetadataTree, streamMetadataTree, ...")
    except Exception as e:
        print(f"  [FAIL] {e}")
        failed += 1

    print(f"\n=== Result: {'OK' if failed == 0 else f'{failed} test(s) FAILED'} ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
