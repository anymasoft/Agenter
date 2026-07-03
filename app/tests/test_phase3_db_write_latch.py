"""
Фаза 3 разворота — проверка прогоном.

Две части:
  A) Защёлка записи в БД (Шаг 3.3) — net-new правило периметра, стоит
     САМОСТОЯТЕЛЬНО (не зависит от stage-dispatch). Должна ловить прямую
     загрузку в БД через конфигуратор/предприятие и пропускать чтение/выгрузку.
  B) Срез stage-dispatch (Шаг 3.2) + живость ядра — вызов, который раньше
     блокировался «не та стадия», теперь проходит; §0/R7 по-прежнему держат.

Запуск: python app/tests/test_phase3_db_write_latch.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tool_guards import check_tool_call, _bash_db_write_to_base  # noqa: E402


def _ok(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


# ── Часть A: защёлка записи в БД (детектор семантики) ───────────────────────
print("A. Защёлка записи в БД — детектор _bash_db_write_to_base:")

# Прямой конфигуратор → запись (блок)
_ok(_bash_db_write_to_base(
    '1cv8 DESIGNER /LoadConfigFromFiles "D:/ext_src" -Extension Ext /UpdateDBCfg'
) is not None, "1cv8 DESIGNER /LoadConfigFromFiles+/UpdateDBCfg → запись")
_ok(_bash_db_write_to_base("1cv8.exe DESIGNER /UpdateDBCfg") is not None,
    "1cv8.exe DESIGNER /UpdateDBCfg → запись")
_ok(_bash_db_write_to_base("1cv8 DESIGNER /LoadCfg ext.cfe -Extension E") is not None,
    "1cv8 DESIGNER /LoadCfg .cfe → запись")
# PowerShell-обёртка: бинарник + verb всё равно видны
_ok(_bash_db_write_to_base(
    'powershell -Command "& \'1cv8.exe\' DESIGNER /LoadConfigFromFiles ext_src /UpdateDBCfg"'
) is not None, "powershell-обёртка вокруг 1cv8 DESIGNER → запись")
# Режим предприятия с исполнением кода (db-run)
_ok(_bash_db_write_to_base("1cv8c ENTERPRISE /Execute upd.epf") is not None,
    "1cv8c ENTERPRISE /Execute → запись (db-run)")
_ok(_bash_db_write_to_base('1cv8 ENTERPRISE /C "ВыполнитьОбновление"') is not None,
    "1cv8 ENTERPRISE /C → запись (db-run)")

# Чтение/выгрузка/диагностика → НЕ запись (пропуск)
_ok(_bash_db_write_to_base("1cv8 DESIGNER /DumpConfigToFiles D:/ext_src") is None,
    "1cv8 DESIGNER /DumpConfigToFiles → выгрузка, не блок")
_ok(_bash_db_write_to_base("1cv8 DESIGNER /DumpIB backup.dt") is None,
    "1cv8 DESIGNER /DumpIB → выгрузка, не блок")
_ok(_bash_db_write_to_base("cat ext_src/Configuration.xml") is None,
    "cat .xml → чтение, не блок")
_ok(_bash_db_write_to_base("git status") is None, "git status → не блок")
# Нет бинарника платформы — не наш случай (страховка от ложных срабатываний)
_ok(_bash_db_write_to_base("echo /UpdateDBCfg in docs") is None,
    "текст без бинарника 1cv8 → не блок")

# ── Защёлка в составе check_tool_call (Bash-tool) ───────────────────────────
print("\nA2. Защёлка через check_tool_call(tool='Bash'):")
r = check_tool_call(
    "Bash",
    {"command": "1cv8 DESIGNER /LoadConfigFromFiles ext_src /UpdateDBCfg"},
    [],
)
_ok(r is not None and "запись в БД мимо db_load" in r,
    "прямой 1cv8 LoadConfigFromFiles через Bash → GUARD BLOCKED")
_ok(check_tool_call("Bash", {"command": "cat foo.xml"}, []) is None,
    "cat foo.xml → не блокируется защёлкой БД")

# ── Наш канал db_load НЕ затронут защёлкой (это tool, не Bash) ──────────────
print("\nA3. Канал db_load цел:")
hist_validated = [{"tool": "cfe_validate", "ok": True, "params": {}}]
_ok(check_tool_call("db_load", {}, hist_validated) is None,
    "db_load после успешного cfe_validate → разрешён (наш канал работает)")

# ── Часть B: срез stage-dispatch + живость ядра ─────────────────────────────
# Фаза 4: параметры stage_dispatch_required/current_stage убраны из сигнатуры
# check_tool_call вместе со стадийной машиной. Вызовы, которые раньше
# блокировались «не та стадия», теперь проходят сами по себе.
print("\nB. Срез stage-dispatch — раньше блокировалось «не та стадия», теперь нет:")
r = check_tool_call(
    "meta_edit",
    {"object_path": "Catalogs/X", "definition": {}},
    [],
)
_ok(r is None, "meta_edit без стадий → проходит (stage-dispatch снят)")

# Раньше «План не построен → блок всего»; теперь plan_task не принуждается.
r = check_tool_call("meta_compile", {"definition": None}, [])
_ok(r is None, "meta_compile без плана → проходит (plan_task больше не принуждается)")

print("\nB2. Ядро живо (§0 / R7):")
# §0 — сырая запись XML через Bash по-прежнему блокируется
r = check_tool_call(
    "Bash",
    {"command": "sed -i 's/a/b/' ext_src/Subsystems/Продажи.xml"},
    [],
)
_ok(r is not None and "§0" in r, "§0: sed -i по .xml метаданных → BLOCKED")
# R7 — db_load без cfe_validate по-прежнему блокируется
r = check_tool_call("db_load", {}, [])
_ok(r is not None and "cfe_validate" in r, "R7: db_load без cfe_validate → BLOCKED")

print("\nВСЕ ПРОВЕРКИ ПРОШЛИ (Фаза 3 — защёлка записи в БД + срез stage-dispatch)")
