"""
Словарь типов метаданных 1С + маппинг английских названий в BSL (русские).

Порт из MetadataViewer1C/src/Metadata/metadata-types.ts.

Используется для:
    - отображения русских названий типов в UI
    - построения BSL-типов ссылок (CatalogRef → СправочникСсылка)
    - LLM-промптов («все типы объектов 1С»)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MetadataTypeMapping:
    """Соответствие английского и русского названий типа метаданных."""

    type: str
    """Catalog, Document, Enum, ..."""

    display_name: str
    """Русское название: Справочник, Документ, ..."""

    ref_type: str
    """Английский тип ссылки: CatalogRef, DocumentRef, ..."""

    ref_display_name: str
    """Русское название типа ссылки."""

    object_type: Optional[str] = None
    """CatalogObject, DocumentObject, ..."""

    object_display_name: Optional[str] = None
    """СправочникОбъект, ДокументОбъект, ..."""

    manager_type: Optional[str] = None
    """CatalogManager, DocumentManager, ..."""

    manager_display_name: Optional[str] = None
    """СправочникМенеджер, ДокументМенеджер, ..."""

    @property
    def type_dir(self) -> str:
        """Имя папки в выгрузке: Catalogs, Documents, ..."""
        # Большинство — добавление 's' к type
        special = {
            "ChartOfCharacteristicTypes":  "ChartsOfCharacteristicTypes",
            "ChartOfAccounts":             "ChartsOfAccounts",
            "ChartOfCalculationTypes":     "ChartsOfCalculationTypes",
            "BusinessProcess":             "BusinessProcesses",
            "FilterCriterion":             "FilterCriteria",
            # Languages — папка названа также, как тип во множественном числе
        }
        return special.get(self.type, f"{self.type}s")


# Полный словарь типов
METADATA_TYPES: list[MetadataTypeMapping] = [
    MetadataTypeMapping("Catalog", "Справочник", "CatalogRef", "Справочник",
                        "CatalogObject", "СправочникОбъект", "CatalogManager", "СправочникМенеджер"),
    MetadataTypeMapping("Document", "Документ", "DocumentRef", "Документ",
                        "DocumentObject", "ДокументОбъект", "DocumentManager", "ДокументМенеджер"),
    MetadataTypeMapping("Enum", "Перечисление", "EnumRef", "Перечисление"),
    MetadataTypeMapping("Report", "Отчёт", "ReportRef", "Отчёт"),
    MetadataTypeMapping("DataProcessor", "Обработка", "DataProcessorRef", "Обработка"),
    MetadataTypeMapping("ChartOfCharacteristicTypes", "План видов характеристик",
                        "ChartOfCharacteristicTypesRef", "План видов характеристик"),
    MetadataTypeMapping("ChartOfAccounts", "План счетов",
                        "ChartOfAccountsRef", "План счетов"),
    MetadataTypeMapping("ChartOfCalculationTypes", "План видов расчёта",
                        "ChartOfCalculationTypesRef", "План видов расчёта"),
    MetadataTypeMapping("InformationRegister", "Регистр сведений",
                        "InformationRegisterRef", "Регистр сведений"),
    MetadataTypeMapping("AccumulationRegister", "Регистр накопления",
                        "AccumulationRegisterRef", "Регистр накопления"),
    MetadataTypeMapping("AccountingRegister", "Регистр бухгалтерии",
                        "AccountingRegisterRef", "Регистр бухгалтерии"),
    MetadataTypeMapping("CalculationRegister", "Регистр расчёта",
                        "CalculationRegisterRef", "Регистр расчёта"),
    MetadataTypeMapping("BusinessProcess", "Бизнес-процесс",
                        "BusinessProcessRef", "Бизнес-процесс"),
    MetadataTypeMapping("Task", "Задача", "TaskRef", "Задача"),
    MetadataTypeMapping("Constant", "Константа", "ConstantRef", "Константа"),
    MetadataTypeMapping("CommonModule", "Общий модуль", "CommonModuleRef", "Общий модуль"),
    MetadataTypeMapping("CommonForm", "Общая форма", "CommonFormRef", "Общая форма"),
    MetadataTypeMapping("ExternalDataSource", "Внешний источник данных",
                        "ExternalDataSourceRef", "Внешний источник данных"),
    MetadataTypeMapping("DefinedType", "Определяемый тип",
                        "DefinedTypeRef", "Определяемый тип"),
    MetadataTypeMapping("ExchangePlan", "План обмена", "ExchangePlanRef", "План обмена"),
    MetadataTypeMapping("DocumentJournal", "Журнал документов",
                        "DocumentJournalRef", "Журнал документов"),
    MetadataTypeMapping("Sequence", "Последовательность",
                        "SequenceRef", "Последовательность"),
    MetadataTypeMapping("DocumentNumerator", "Нумератор документов",
                        "DocumentNumeratorRef", "Нумератор документов"),
    MetadataTypeMapping("WebService", "Веб-сервис", "WebServiceRef", "Веб-сервис"),
    MetadataTypeMapping("HTTPService", "HTTP-сервис", "HTTPServiceRef", "HTTP-сервис"),
    MetadataTypeMapping("Subsystem", "Подсистема", "SubsystemRef", "Подсистема"),
    MetadataTypeMapping("Role", "Роль", "RoleRef", "Роль"),
    MetadataTypeMapping("SessionParameter", "Параметр сеанса",
                        "SessionParameterRef", "Параметр сеанса"),
    MetadataTypeMapping("CommonAttribute", "Общий реквизит",
                        "CommonAttributeRef", "Общий реквизит"),
    MetadataTypeMapping("EventSubscription", "Подписка на событие",
                        "EventSubscriptionRef", "Подписка на событие"),
    MetadataTypeMapping("ScheduledJob", "Регламентное задание",
                        "ScheduledJobRef", "Регламентное задание"),
    MetadataTypeMapping("CommonCommand", "Общая команда",
                        "CommonCommandRef", "Общая команда"),
    MetadataTypeMapping("CommandGroup", "Группа команд",
                        "CommandGroupRef", "Группа команд"),
    MetadataTypeMapping("CommonTemplate", "Общий макет",
                        "CommonTemplateRef", "Общий макет"),
    MetadataTypeMapping("CommonPicture", "Общая картинка",
                        "CommonPictureRef", "Общая картинка"),
    MetadataTypeMapping("WSReference", "WS-ссылка", "WSReferenceRef", "WS-ссылка"),
    MetadataTypeMapping("Style", "Стиль", "StyleRef", "Стиль"),
    MetadataTypeMapping("StyleItem", "Элемент стиля", "StyleItemRef", "Элемент стиля"),
    MetadataTypeMapping("FilterCriterion", "Критерий отбора",
                        "FilterCriterionRef", "Критерий отбора"),
    MetadataTypeMapping("FunctionalOption", "Функциональная опция",
                        "FunctionalOptionRef", "Функциональная опция"),
    MetadataTypeMapping("FunctionalOptionsParameter", "Параметр функциональных опций",
                        "FunctionalOptionsParameterRef", "Параметр функциональных опций"),
    MetadataTypeMapping("SettingsStorage", "Хранилище настроек",
                        "SettingsStorageRef", "Хранилище настроек"),
    MetadataTypeMapping("XDTOPackage", "XDTO-пакет", "XDTOPackageRef", "XDTO-пакет"),
    MetadataTypeMapping("Language", "Язык", "LanguageRef", "Язык"),
]


# Быстрые индексы по type / type_dir / ref_type
_BY_TYPE: dict[str, MetadataTypeMapping] = {m.type: m for m in METADATA_TYPES}
_BY_TYPE_DIR: dict[str, MetadataTypeMapping] = {m.type_dir: m for m in METADATA_TYPES}
_BY_REF_TYPE: dict[str, MetadataTypeMapping] = {m.ref_type: m for m in METADATA_TYPES}


def get_type(type_name: str) -> Optional[MetadataTypeMapping]:
    """Возвращает MetadataTypeMapping по type (Catalog, Document, ...)."""
    return _BY_TYPE.get(type_name)


def get_type_by_dir(type_dir: str) -> Optional[MetadataTypeMapping]:
    """Возвращает MetadataTypeMapping по type_dir (Catalogs, Documents, ...)."""
    return _BY_TYPE_DIR.get(type_dir)


def get_display_name(type_name: str) -> str:
    """Русское имя типа или сам type_name, если не найдено."""
    m = _BY_TYPE.get(type_name)
    return m.display_name if m else type_name


# Множественные формы названий типов — как в конфигураторе 1С.
# Алгоритмическая плюрализация для русского не работает корректно
# (Подсистема→Подсистемы, но Регистр сведений→Регистры сведений, и т.п.),
# поэтому фиксируем все формы вручную по типу метаданных.
_DISPLAY_NAME_PLURAL: dict[str, str] = {
    "Catalog":                      "Справочники",
    "Document":                     "Документы",
    "Enum":                         "Перечисления",
    "Report":                       "Отчёты",
    "DataProcessor":                "Обработки",
    "ChartOfCharacteristicTypes":   "Планы видов характеристик",
    "ChartOfAccounts":              "Планы счетов",
    "ChartOfCalculationTypes":      "Планы видов расчёта",
    "InformationRegister":          "Регистры сведений",
    "AccumulationRegister":         "Регистры накопления",
    "AccountingRegister":           "Регистры бухгалтерии",
    "CalculationRegister":          "Регистры расчёта",
    "BusinessProcess":              "Бизнес-процессы",
    "Task":                         "Задачи",
    "Constant":                     "Константы",
    "CommonModule":                 "Общие модули",
    "CommonForm":                   "Общие формы",
    "ExternalDataSource":           "Внешние источники данных",
    "DefinedType":                  "Определяемые типы",
    "ExchangePlan":                 "Планы обмена",
    "DocumentJournal":              "Журналы документов",
    "Sequence":                     "Последовательности",
    "DocumentNumerator":            "Нумераторы документов",
    "WebService":                   "Веб-сервисы",
    "HTTPService":                  "HTTP-сервисы",
    "Subsystem":                    "Подсистемы",
    "Role":                         "Роли",
    "SessionParameter":             "Параметры сеанса",
    "CommonAttribute":              "Общие реквизиты",
    "EventSubscription":            "Подписки на событие",
    "ScheduledJob":                 "Регламентные задания",
    "CommonCommand":                "Общие команды",
    "CommandGroup":                 "Группы команд",
    "CommonTemplate":               "Общие макеты",
    "CommonPicture":                "Общие картинки",
    "WSReference":                  "WS-ссылки",
    "Style":                        "Стили",
    "StyleItem":                    "Элементы стиля",
    "FilterCriterion":              "Критерии отбора",
    "FunctionalOption":             "Функциональные опции",
    "FunctionalOptionsParameter":   "Параметры функциональных опций",
    "SettingsStorage":              "Хранилища настроек",
    "XDTOPackage":                  "XDTO-пакеты",
    "Language":                     "Языки",
}


def get_display_name_by_dir(type_dir: str) -> str:
    """Русское имя типа в множественной форме по dir-имени.

    Catalogs → Справочники, AccumulationRegisters → Регистры накопления,
    SessionParameters → Параметры сеанса, и т.п.
    """
    m = _BY_TYPE_DIR.get(type_dir)
    if m:
        # Явная plural-форма (если не нашли — fallback на алгоритмический)
        return _DISPLAY_NAME_PLURAL.get(m.type) or _pluralize_ru(m.display_name)
    return type_dir


def _pluralize_ru(s: str) -> str:
    """Fallback-плюрализация для типов, отсутствующих в _DISPLAY_NAME_PLURAL.

    Достаточно грубая, на случай если в выгрузке встретится новый тип
    объектов 1С, который мы ещё не добавили в словарь явных форм.
    """
    if s.endswith("к"):
        return s[:-1] + "ки"
    if s.endswith("т"):
        return s + "ы"  # Документ → Документы, Отчёт → Отчёты
    if s.endswith("е"):
        return s[:-1] + "я"  # Перечисление → Перечисления
    if s.endswith("а"):
        return s[:-1] + "ы"  # Обработка → Обработки, Подсистема → Подсистемы
    if s.endswith("я"):
        return s[:-1] + "и"  # Задача? Опция?
    if s.endswith("ь"):
        return s[:-1] + "и"  # Роль → Роли, Стиль → Стили
    return s + "ы"


# ---- BSL Mapping -------------------------------------------------------------

# Точные соответствия из существующего кода
_EXPLICIT_BSL_MAP: dict[str, str] = {
    "CatalogRef": "СправочникСсылка",
    "DocumentRef": "ДокументСсылка",
    "EnumRef": "ПеречислениеСсылка",
    "ChartOfAccountsRef": "ПланСчетовСсылка",
    "ChartOfCalculationTypesRef": "ПланВидовРасчетаСсылка",
    "ChartOfCharacteristicTypesRef": "ПланВидовХарактеристикСсылка",
    "InformationRegisterRef": "РегистрСведенийСсылка",
    "AccumulationRegisterRef": "РегистрНакопленияСсылка",
    "AccountingRegisterRef": "РегистрБухгалтерииСсылка",
    "CalculationRegisterRef": "РегистрРасчетаСсылка",
    "BusinessProcessRef": "БизнесПроцессСсылка",
    "TaskRef": "ЗадачаСсылка",
    "ExchangePlanRef": "ПланОбменаСсылка",
    "DocumentObject": "ДокументОбъект",
    "CatalogObject": "СправочникОбъект",
    "CatalogManager": "СправочникМенеджер",
    "DocumentManager": "ДокументМенеджер",
}


def _to_bsl_name(display_name: str) -> str:
    """Преобразует 'Общий модуль' → 'ОбщийМодуль' (для BSL-имени типа)."""
    parts = display_name.replace("ё", "е").replace("Ё", "Е").split()
    result = ""
    for p in parts:
        # Может быть составное через дефис (Бизнес-процесс)
        for sub in p.split("-"):
            if sub:
                result += sub[0].upper() + sub[1:].lower()
    return result


_BSL_REF_MAP: dict[str, str] = dict(_EXPLICIT_BSL_MAP)

# Достраиваем остальные через display_name
for _m in METADATA_TYPES:
    if _m.ref_type not in _BSL_REF_MAP:
        _BSL_REF_MAP[_m.ref_type] = _to_bsl_name(_m.display_name) + "Ссылка"
    if _m.object_type and _m.object_type not in _BSL_REF_MAP:
        _BSL_REF_MAP[_m.object_type] = _to_bsl_name(_m.display_name) + "Объект"
    if _m.manager_type and _m.manager_type not in _BSL_REF_MAP:
        _BSL_REF_MAP[_m.manager_type] = _to_bsl_name(_m.display_name) + "Менеджер"


def get_bsl_ref_type(en_ref_type: str) -> str:
    """CatalogRef → СправочникСсылка."""
    return _BSL_REF_MAP.get(en_ref_type, en_ref_type)


def all_bsl_mappings() -> dict[str, str]:
    """Полная таблица соответствий — для LLM-промптов и валидации."""
    return dict(_BSL_REF_MAP)
