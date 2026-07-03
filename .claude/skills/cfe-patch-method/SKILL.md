---
name: cfe-patch-method
description: Генерация перехватчика метода в расширении 1С (CFE). Используй когда нужно перехватить метод заимствованного объекта — вставить код до, после или вместо оригинального
argument-hint: -ExtensionPath <path> -ModulePath "Catalog.X.ObjectModule" -MethodName "ПриЗаписи" -InterceptorType Before
allowed-tools:
  - Bash
  - Read
  - Glob
---

# /cfe-patch-method — Генерация перехватчика метода

Генерирует `.bsl` файл с декоратором перехвата для заимствованного объекта расширения. Создаёт файл или дописывает в существующий.

## Предусловие

Объект должен быть заимствован в расширение (`/cfe-borrow`). Скрипт читает `NamePrefix` из `Configuration.xml` расширения для формирования имени процедуры.

## Параметры

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `ExtensionPath` | Путь к расширению (обязат.) | — |
| `ModulePath` | Путь к модулю (обязат.) | — |
| `MethodName` | Имя перехватываемого метода (обязат.) | — |
| `InterceptorType` | `Before` / `After` / `Instead` / `ModificationAndControl` (обязат.) | — |
| `Context` | Директива контекста | `НаСервере` |
| `IsFunction` | Метод — функция (добавит `Возврат`) | false |

## Формат ModulePath

| ModulePath | Файл |
|------------|------|
| `Catalog.X.ObjectModule` | `Catalogs/X/Ext/ObjectModule.bsl` |
| `Catalog.X.ManagerModule` | `Catalogs/X/Ext/ManagerModule.bsl` |
| `Catalog.X.Form.Y` | `Catalogs/X/Forms/Y/Ext/Form/Module.bsl` |
| `CommonModule.X` | `CommonModules/X/Ext/Module.bsl` |
| `Document.X.ObjectModule` | `Documents/X/Ext/ObjectModule.bsl` |
| `Document.X.Form.Y` | `Documents/X/Forms/Y/Ext/Form/Module.bsl` |

Аналогично для Report, DataProcessor, InformationRegister и других типов.

## Типы перехвата

| InterceptorType | Декоратор | Назначение |
|-----------------|-----------|------------|
| `Instead` | `&Вместо` | **Канонический выбор.** Код до `ПродолжитьВызов` = «перед», после = «после», без вызова = полная замена. Копия оригинала НЕ нужна |
| `Before` | `&Перед` | Код до вызова оригинального метода |
| `After` | `&После` | Код после вызова оригинального метода |
| `ModificationAndControl` | `&ИзменениеИКонтроль` | Копия тела метода с маркерами `#Вставка`/`#Удаление` |

> **ПРАВИЛО ВЫБОРА.** По умолчанию — `Instead` (`&Вместо`) + `ПродолжитьВызов`: один синтаксис на все случаи, копия оригинала не требуется → ошибка платформы «Текст модуля для метода … изменился» невозможна в принципе.
> `ModificationAndControl` ВРУЧНУЮ НЕ ИСПОЛЬЗОВАТЬ: он требует байт-точной копии тела оригинала, которую правкой не воспроизвести; платформа отвергнет применение модуля (`db_load` это НЕ ловит — ловит apply-проверка `/CheckCanApplyConfigurationExtensions`). Допустим только через генератор размеченной копии из точного оригинала.
> Для `Instead`/`Before`/`After` сигнатура процедуры повторяет параметры оригинала; для `Instead` они передаются в `ПродолжитьВызов`.

## Команда

```powershell
powershell.exe -NoProfile -File "${CLAUDE_SKILL_DIR}/scripts/cfe-patch-method.ps1" -ExtensionPath src -ModulePath "Catalog.Контрагенты.ObjectModule" -MethodName "ПриЗаписи" -InterceptorType Before
```

## Примеры

```powershell
# Перехват &Перед на сервере
... -ExtensionPath src -ModulePath "Catalog.Контрагенты.ObjectModule" -MethodName "ПриЗаписи" -InterceptorType Before

# Перехват &После на клиенте
... -ExtensionPath src -ModulePath "Document.Заказ.Form.ФормаДокумента" -MethodName "ПослеЗаписиНаСервере" -InterceptorType After -Context "НаКлиенте"

# ИзменениеИКонтроль для функции
... -ExtensionPath src -ModulePath "CommonModule.ОбщийМодуль" -MethodName "ПолучитьДанные" -InterceptorType ModificationAndControl -IsFunction
```

## Генерируемый код (Before)

```bsl
&НаСервере
&Перед("ПриЗаписи")
Процедура Расш1_ПриЗаписи()
	// TODO: код перед вызовом оригинального метода
КонецПроцедуры
```
