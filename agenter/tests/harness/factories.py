"""Programmatic factories for ext_src/ state used in tests.

Industrial pattern: instead of dozens of copy-pasted XML fixtures
on disk, generate them from a small Python API. Keeps fixture-drift
to a minimum and makes parameterized tests trivial.

These are NOT meant to be byte-identical to what 1C generates —
they're shaped enough for the skills to operate on, with the same
namespace declarations and element structure that we observed in
real `cfe_borrow` and `meta_compile` output.

When a test needs a state that's hard to construct (e.g. a complex
multi-object configuration), prefer a snapshot fixture under
`tests/fixtures/<name>/` instead.
"""
from __future__ import annotations

import uuid
from pathlib import Path

# Standard MDClasses namespace declarations used in every 1C XML root.
_MD_NS_ATTRS = (
    'xmlns="http://v8.1c.ru/8.3/MDClasses" '
    'xmlns:app="http://v8.1c.ru/8.2/managed-application/core" '
    'xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" '
    'xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" '
    'xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" '
    'xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" '
    'xmlns:style="http://v8.1c.ru/8.1/data/ui/style" '
    'xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" '
    'xmlns:v8="http://v8.1c.ru/8.1/data/core" '
    'xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" '
    'xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" '
    'xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" '
    'xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" '
    'xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" '
    'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
    'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'version="2.20"'
)


def make_ext_src_root(base: Path) -> Path:
    """Create an empty extension layout under `base`.

    Returns the ext_src root containing Configuration.xml.
    """
    base.mkdir(parents=True, exist_ok=True)
    config_xml = base / "Configuration.xml"
    if not config_xml.exists():
        config_xml.write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<MetaDataObject {_MD_NS_ATTRS}>\n"
            f'\t<Configuration uuid="{uuid.uuid4()}">\n'
            f"\t\t<Properties>\n"
            f"\t\t\t<Name>TestExtension</Name>\n"
            f"\t\t\t<Synonym/>\n"
            f"\t\t\t<NamePrefix>Тест_</NamePrefix>\n"
            f"\t\t</Properties>\n"
            f"\t\t<ChildObjects/>\n"
            f"\t</Configuration>\n"
            f"</MetaDataObject>\n",
            encoding="utf-8",
        )
    return base


def make_borrowed_subsystem(
    ext_src_root: Path,
    name: str,
    *,
    with_content: bool = False,
    content_items: list[str] | None = None,
) -> Path:
    """Create a Subsystems/<name>.xml mimicking cfe_borrow output.

    Args:
        ext_src_root: Path to ext_src root (use make_ext_src_root).
        name: Subsystem name (e.g. "Финансы").
        with_content: If True, emit a <Content> element with items.
                      If False, emit a Properties block WITHOUT <Content>
                      — this is the shape that triggered the prod bug.
        content_items: If provided and with_content=True, populate
                       <Content> with these <xr:Item> entries.

    Returns the path to the created file.
    """
    subsystems = ext_src_root / "Subsystems"
    subsystems.mkdir(parents=True, exist_ok=True)
    xml_path = subsystems / f"{name}.xml"

    sub_uuid = uuid.uuid4()
    ext_uuid = uuid.uuid4()

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(f"<MetaDataObject {_MD_NS_ATTRS}>")
    lines.append(f'\t<Subsystem uuid="{sub_uuid}">')
    lines.append("\t\t<InternalInfo/>")
    lines.append("\t\t<Properties>")
    lines.append("\t\t\t<ObjectBelonging>Adopted</ObjectBelonging>")
    lines.append(f"\t\t\t<Name>{name}</Name>")
    lines.append("\t\t\t<Comment/>")
    lines.append(f"\t\t\t<ExtendedConfigurationObject>{ext_uuid}</ExtendedConfigurationObject>")
    if with_content:
        items = content_items or []
        if items:
            lines.append("\t\t\t<Content>")
            for item in items:
                lines.append(f'\t\t\t\t<xr:Item xsi:type="xr:MDObjectRef">{item}</xr:Item>')
            lines.append("\t\t\t</Content>")
        else:
            lines.append("\t\t\t<Content/>")
    lines.append("\t\t</Properties>")
    lines.append("\t</Subsystem>")
    lines.append("</MetaDataObject>")

    xml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return xml_path
