"""Проверка плюрализации русских названий типов 1С."""
from __future__ import annotations

import sys
from pathlib import Path

# Выводим в UTF-8, чтобы русский корректно отображался в PowerShell
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from metadata_utils.metadata_types import METADATA_TYPES, get_display_name_by_dir


def main() -> int:
    type_dirs = [
        "Catalogs", "Documents", "Enums", "Reports", "DataProcessors",
        "ChartsOfCharacteristicTypes", "ChartsOfAccounts", "ChartsOfCalculationTypes",
        "InformationRegisters", "AccumulationRegisters", "AccountingRegisters",
        "CalculationRegisters", "BusinessProcesses", "Tasks", "Constants",
        "CommonModules", "CommonForms", "ExternalDataSources", "DefinedTypes",
        "ExchangePlans", "DocumentJournals", "Sequences", "DocumentNumerators",
        "WebServices", "HTTPServices", "Subsystems", "Roles", "SessionParameters",
        "CommonAttributes", "EventSubscriptions", "ScheduledJobs", "CommonCommands",
        "CommandGroups", "CommonTemplates", "CommonPictures", "WSReferences",
        "Styles", "StyleItems", "FilterCriteria", "FunctionalOptions",
        "FunctionalOptionsParameters", "SettingsStorages", "XDTOPackages",
        "Languages",
    ]
    bad: list[str] = []
    for td in type_dirs:
        result = get_display_name_by_dir(td)
        # Маркер плохого окончания: "ы" после согласной/мягкого знака — обычно ошибка
        # на словах, оканчивающихся на 'ка/ге/ия' и т.п.
        red_flags = ["ьы", "ия+ы", "ийы", "льы", "тьы", "цы", "цыы", "коы", "ныы", "сяы", "еы"]
        marker = ""
        for rf in red_flags:
            if rf in result:
                marker = f"  ← BAD ({rf!r})"
                bad.append(td)
                break
        print(f"  {td:30s} -> {result}{marker}")

    print(f"\n  Total types: {len(type_dirs)}")
    print(f"  Suspicious endings: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
