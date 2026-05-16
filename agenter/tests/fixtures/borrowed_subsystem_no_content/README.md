# Fixture: `borrowed_subsystem_no_content`

Captures the exact `ext_src/` state that triggered the production
failure on 2026-05-16.

## Origin

User ran two tasks in Agenter:

1. **"Создай справочник Посуда"** — succeeded. Created `Catalog.Расш1_Посуда`
   in the extension `МоеРасширение`.
2. **"Помести этот справочник в подсистему Финансы"** — failed.
   The agent correctly identified that `Финансы` lives in the main
   configuration, re-planned to borrow it first via `cfe_borrow`,
   succeeded with the borrow, then tried `subsystem-edit add-content`
   and crashed:

   ```
   Do-AddContent : No <Content> element found
   at scripts\subsystem-edit.ps1:498 char:22
   ```

## What the fixture contains

`Subsystems/Финансы.xml` — the borrowed subsystem after `cfe_borrow`.
Note: `<Properties>` is present but contains no `<Content>` child.
This is the natural shape of a freshly borrowed empty subsystem.

## What a working `subsystem-edit add-content` should do

Detect that `<Content>` is missing, create it inside `<Properties>`
(after the existing children, with correct whitespace), then insert
the `<xr:Item xsi:type="xr:MDObjectRef">Catalog.Расш1_Посуда</xr:Item>`.

The test in `tests/skills/test_subsystem_edit.py` enforces this.
