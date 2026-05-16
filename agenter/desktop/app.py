"""
Agenter Desktop — GUI launcher.

Запускает:
  • Окно (pywebview, frameless)
  • Трей-иконку (pystray)
  • Агента (main.py) в фоновом потоке

Запуск:
    python app.py
    python app.py --debug   # открывает DevTools
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path

import pystray
import webview
from PIL import Image, ImageDraw

# main.py лежит рядом в той же папке desktop/
sys.path.insert(0, str(Path(__file__).parent))
import websockets as _ws_lib
from main import (
    AgentWSClient,
    BslAtlasClient,
    ToolExecutor,
    load_config,
)

log = logging.getLogger(__name__)

_ERP_ROOT = Path(__file__).parent.parent.parent            # C:\BUFFER\ERP

# Конфиг — тот же файл что читает desktop/main.py (config.json)
# В frozen (PyInstaller) режиме — рядом с EXE, в dev — в agenter/config/
if getattr(sys, "frozen", False):
    _CONFIG_PATH = Path(sys.executable).parent / "config" / "config.json"
else:
    _CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"

_DUMP_SCRIPT = _ERP_ROOT / ".claude" / "skills" / "db-dump-xml" / "scripts" / "db-dump-xml.ps1"

# ---------------------------------------------------------------------------
# Общее состояние приложения
# ---------------------------------------------------------------------------

class _AppState:
    def __init__(self):
        self.backend_connected: bool = False
        self.bsl_connected: bool = False
        self.logs: deque = deque(maxlen=60)
        self.cfg: dict = {}
        self.tray_icon: pystray.Icon | None = None
        self.indexing_running: bool = False
        self.indexing_done: bool = False
        self.indexing_error: str = ""
        self.indexing_logs: deque = deque(maxlen=200)
        # Фазы индексации: scheme → ext → atlas
        self.indexing_phase: str = ""
        self.indexing_phases_done: dict = {"scheme": False, "ext": False, "atlas": False}
        self.indexing_phases_skipped: dict = {"scheme": False, "ext": False, "atlas": False}

    def add_log(self, tag: str, text: str):
        self.logs.appendleft({"tag": tag, "text": text[:64], "time": time.strftime("%H:%M")})


state = _AppState()
_win: webview.Window | None = None


# ---------------------------------------------------------------------------
# Агент с хуками GUI
# ---------------------------------------------------------------------------

class GUIAgentWSClient(AgentWSClient):
    """Расширяет AgentWSClient: обновляет state и посылает уведомления."""

    async def _connect_and_loop(self):
        state.backend_connected = True
        state.add_log("+", "Backend подключён")
        try:
            async with _ws_lib.connect(
                self.url,
                ping_interval=self.HEARTBEAT_INTERVAL,
                ping_timeout=60,
                open_timeout=30,
            ) as ws:
                self._ws = ws
                log.info("✓ Подключён к backend")
                _cfg_safe = {k: v for k, v in self.cfg.items() if k != "password"}
                await ws.send(json.dumps({
                    "type": "hello", "version": "1.0.0", "config": _cfg_safe
                }))

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type")
                    if msg_type == "tool_call":
                        asyncio.create_task(self._handle_tool_call(ws, msg))
                    elif msg_type == "task_done_notify":
                        state.add_log("✓", "Задача выполнена")
                        _show_notification("Задача выполнена", "Изменения применены в базе 1С")
                    elif msg_type == "pong":
                        pass

        except Exception as exc:
            log.warning("WS loop error: %s", exc)
        finally:
            state.backend_connected = False
            state.add_log("○", "Backend отключён")

    async def _handle_tool_call(self, ws, msg: dict):
        tool = msg.get("tool", "?")
        state.add_log("→", tool)
        await super()._handle_tool_call(ws, msg)


# ---------------------------------------------------------------------------
# Pywebview JS-bridge
# ---------------------------------------------------------------------------

class DesktopAPI:
    """Методы, доступные из JS через window.pywebview.api.*"""

    def get_status(self) -> dict:
        return {
            "backend_connected": state.backend_connected,
            "bsl_connected":     state.bsl_connected,
            "hostname":          socket.gethostname(),
            "version":           "1.0.0",
            "backend_url":       state.cfg.get("backend_ws_url", ""),
            "logs":              list(state.logs),
        }

    def open_web_ui(self):
        webbrowser.open("http://localhost:8080/ui/app.html")

    def hide_window(self):
        if _win:
            _win.hide()

    def minimize_window(self):
        if _win:
            _win.minimize()

    def quit_app(self):
        _quit()

    def set_window_size(self, width: int, height: int):
        """Ресайз окна — вызывается из JS при переходе wizard ↔ main."""
        if _win:
            _win.resize(int(width), int(height))

    def move_window_by(self, dx: int, dy: int) -> None:
        """Сдвинуть окно на (dx, dy) пикселей."""
        if not _win:
            return
        try:
            import ctypes
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "Agenter Desktop")
            if not hwnd:
                return
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            user32.SetWindowPos(
                hwnd, None,
                rect.left + int(dx), rect.top + int(dy),
                0, 0,
                0x0001 | 0x0010,
            )
        except Exception as exc:
            log.warning("move_window_by: %s", exc)

    def move_window(self, x: int, y: int) -> None:
        """Переместить окно в абсолютные экранные координаты. Вызывается из JS drag."""
        if not _win:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "Agenter Desktop")
            if not hwnd:
                return
            user32.SetWindowPos(hwnd, None, int(x), int(y), 0, 0, 0x0001 | 0x0010)
        except Exception as exc:
            log.warning("move_window: %s", exc)

    def finish_setup(self):
        """Мастер завершён: записываем флаг-файл и ресайзим в 420×560."""
        try:
            flag = _CONFIG_PATH.parent / ".setup_done"
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.touch()
        except Exception:
            pass
        self.set_window_size(420, 560)

    # ── Конфигурация ──────────────────────────────────────────────────────────

    def browse_folder(self) -> str:
        if _win:
            result = _win.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
            if result:
                return result[0]
        return ""

    def validate_config(self, data: dict) -> dict:
        errors = []
        v8_path   = data.get("v8_path", "").strip()
        base_path = data.get("base_path", "").strip()
        ext_src   = data.get("ext_src_path", "").strip()
        extension = data.get("extension", "").strip()

        if not v8_path:
            errors.append("Не указан путь к платформе 1С")
        elif not (Path(v8_path) / "1cv8.exe").exists():
            errors.append(f"Файл 1cv8.exe не найден: {v8_path}")

        if not base_path:
            errors.append("Не указан путь к информационной базе")
        elif not base_path.startswith("Srvr=") and not Path(base_path).exists():
            errors.append(f"Папка базы не найдена: {base_path}")

        if not extension:
            errors.append("Не указано имя расширения")

        if ext_src and not Path(ext_src).exists():
            errors.append(f"Папка ext_src не найдена: {ext_src}")

        # Проверяем, что скрипты db-dump/db-load существуют
        if getattr(sys, "frozen", False):
            _scripts = Path(sys._MEIPASS) / "scripts"
        else:
            _scripts = Path(__file__).parent.parent / "scripts"

        _ds = (data.get("dump_script") or "").strip()
        _ls = (data.get("load_script") or "").strip()
        _dump = Path(_ds) if _ds and Path(_ds).is_file() else (_scripts / "db-dump-xml.ps1")
        _load = Path(_ls) if _ls and Path(_ls).is_file() else (_scripts / "db-load-xml.ps1")
        if not _dump.is_file():
            errors.append(f"Скрипт db-dump-xml.ps1 не найден: {_dump}")
        if not _load.is_file():
            errors.append(f"Скрипт db-load-xml.ps1 не найден: {_load}")

        return {"ok": len(errors) == 0, "errors": errors}

    def save_config(self, data: dict) -> dict:
        try:
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            enriched = dict(data)

            # Добавляем пути к скриптам если их нет или они нерабочие
            if getattr(sys, "frozen", False):
                _scripts = Path(sys._MEIPASS) / "scripts"
            else:
                _scripts = Path(__file__).parent.parent / "scripts"

            for _key, _name in (("dump_script", "db-dump-xml.ps1"),
                                 ("load_script",  "db-load-xml.ps1")):
                _cur = enriched.get(_key, "")
                if not _cur or not Path(_cur).exists():
                    _candidate = _scripts / _name
                    if _candidate.exists():
                        enriched[_key] = str(_candidate)

            _CONFIG_PATH.write_text(
                json.dumps(enriched, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            state.cfg.update(enriched)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_config(self) -> dict:
        try:
            if _CONFIG_PATH.exists():
                return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    # ── Индексация ────────────────────────────────────────────────────────────

    def start_indexing(self, data: dict) -> dict:
        if state.indexing_running:
            return {"ok": False, "error": "Индексация уже запущена"}
        self.save_config(data)
        state.indexing_running = True
        state.indexing_done    = False
        state.indexing_error   = ""
        state.indexing_phase   = ""
        state.indexing_phases_done    = {"scheme": False, "ext": False, "atlas": False}
        state.indexing_phases_skipped = {"scheme": False, "ext": False, "atlas": False}
        state.indexing_logs.clear()
        threading.Thread(target=_run_indexing, args=(data,), daemon=True, name="indexing").start()
        return {"ok": True}

    def get_indexing_status(self) -> dict:
        return {
            "running":         state.indexing_running,
            "done":            state.indexing_done,
            "error":           state.indexing_error,
            "logs":            list(state.indexing_logs),
            "phase":           state.indexing_phase,
            "phases_done":     state.indexing_phases_done,
            "phases_skipped":  state.indexing_phases_skipped,
        }

    def get_atlas_status(self) -> dict:
        try:
            with urllib.request.urlopen("http://localhost:8000/health", timeout=3) as r:
                return {"ok": True, "body": r.read().decode()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def reindex(self) -> dict:
        cfg = self.get_config()
        if not cfg:
            return {"ok": False, "error": "Нет конфигурации — сначала пройдите мастер"}
        return self.start_indexing(cfg)


# ---------------------------------------------------------------------------
# BSL Atlas: автозапуск и конфигурация
# ---------------------------------------------------------------------------

def _get_bsl_atlas_dir() -> Path | None:
    """Ищет установку BSL Atlas: сначала рядом с EXE (бандл), затем dev-путь."""
    candidates = [
        Path(sys.executable).parent / "bsl-atlas",
        Path("C:/BUFFER/tools/bsl-atlas"),
    ]
    for d in candidates:
        if d.exists() and ((d / "start.bat").exists() or (d / ".env").exists()):
            return d
    return None


def _start_bsl_atlas():
    """Запускает BSL Atlas если он не запущен."""
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=2)
        log.info("BSL Atlas уже запущен")
        return
    except Exception:
        pass

    atlas_dir = _get_bsl_atlas_dir()
    if not atlas_dir:
        log.warning("BSL Atlas не найден — bsl_* инструменты недоступны")
        return

    start_bat = atlas_dir / "start.bat"
    if start_bat.exists():
        subprocess.Popen(
            ["cmd", "/c", str(start_bat)],
            cwd=str(atlas_dir),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        log.info("BSL Atlas запущен: %s", start_bat)
    else:
        log.warning("BSL Atlas: start.bat не найден в %s", atlas_dir)


def _update_bsl_atlas_env(scheme_path: str = "", ext_src_path: str = ""):
    """Обновляет .env BSL Atlas чтобы он знал где SCHEME/ и ext_src/."""
    atlas_dir = _get_bsl_atlas_dir()
    if not atlas_dir:
        return
    env_path = atlas_dir / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)

    def _set(key: str, value: str):
        nonlocal lines
        lines = [l for l in lines if not l.startswith(f"{key}=")]
        if value:
            lines.append(f"{key}={value}\n")

    if scheme_path:
        _set("SCHEME_PATH", scheme_path.replace("\\", "/"))
    if ext_src_path:
        _set("EXT_SRC_PATH", ext_src_path.replace("\\", "/"))
    _set("SQLITE_AUTO_REBUILD", "true")

    env_path.write_text("".join(lines), encoding="utf-8")
    log.info("BSL Atlas .env обновлён: SCHEME=%s EXT_SRC=%s", scheme_path, ext_src_path)


# ---------------------------------------------------------------------------
# Фоновая индексация: scheme dump → ext dump → BSL Atlas reindex
# ---------------------------------------------------------------------------

_POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def _run_ps(script: Path, args: list[str]) -> None:
    """Запускает PowerShell скрипт, пишет stdout в state.indexing_logs, бросает при ошибке."""
    def add(text: str):
        ts = time.strftime("%H:%M:%S")
        state.indexing_logs.appendleft({"ts": ts, "text": text})
        log.info("[indexing] %s", text)

    cmd = [_POWERSHELL, "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", str(script), *args]

    log.info("[ps] script: %s", script)
    for i in range(0, len(args), 2):
        log.info("[ps] arg: %s = %s", args[i], args[i + 1] if i + 1 < len(args) else "")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            add(line)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Скрипт завершился с кодом {proc.returncode}")


def _run_indexing(data: dict):
    def add(text: str):
        ts = time.strftime("%H:%M:%S")
        state.indexing_logs.appendleft({"ts": ts, "text": text})
        log.info("[indexing] %s", text)

    if getattr(sys, "frozen", False):
        scripts_dir = Path(sys._MEIPASS) / "scripts"
    else:
        scripts_dir = Path(__file__).parent.parent / "scripts"

    try:
        v8_path    = data.get("v8_path", "").strip()
        base_path  = data.get("base_path", "").strip()
        username   = data.get("username", "")
        password   = data.get("password", "")
        extension  = data.get("extension", "")
        ext_src    = data.get("ext_src_path", "").strip()
        scheme_dir = data.get("scheme_path", "").strip()

        # ── Фаза 1: Выгрузка SCHEME (полная конфигурация) ────────────────
        state.indexing_phase = "scheme"
        scheme_script = scripts_dir / "dump-scheme.ps1"

        if not scheme_dir:
            add("Фаза 1/3: SCHEME — пропущена (папка не указана)")
            state.indexing_phases_skipped["scheme"] = True
        elif not scheme_script.exists():
            add(f"Фаза 1/3: SCHEME — пропущена (скрипт не найден: {scheme_script})")
            state.indexing_phases_skipped["scheme"] = True
        else:
            add(f"Фаза 1/3: Выгрузка конфигурации 1С → {scheme_dir}")
            add("Это займёт 20-40 минут — можно свернуть окно и работать...")
            _run_ps(scheme_script, [
                "-V8Path",       v8_path,
                "-InfoBasePath", base_path,
                "-UserName",     username,
                "-Password",     password,
                "-SchemeDir",    scheme_dir,
            ])
            _update_bsl_atlas_env(scheme_path=scheme_dir, ext_src_path=ext_src)
            state.indexing_phases_done["scheme"] = True
            add("✓ Фаза 1/3: Конфигурация выгружена")

        # ── Фаза 2: Выгрузка расширения (ext_src) ────────────────────────
        state.indexing_phase = "ext"
        dump_script = Path(data.get("dump_script", "") or "")
        if not dump_script.is_file():
            dump_script = scripts_dir / "db-dump-xml.ps1"

        if not ext_src:
            add("Фаза 2/3: Расширение — пропущена (ext_src не задан)")
            state.indexing_phases_skipped["ext"] = True
        elif not dump_script.is_file():
            add(f"Фаза 2/3: Расширение — пропущена (скрипт не найден: {dump_script})")
            state.indexing_phases_skipped["ext"] = True
        else:
            add(f"Фаза 2/3: Выгрузка расширения {extension} → {ext_src}")
            _run_ps(dump_script, [
                "-V8Path",       v8_path,
                "-InfoBasePath", base_path,
                "-UserName",     username,
                "-Password",     password,
                "-ConfigDir",    ext_src,
                "-Extension",    extension,
                "-Mode",         "Full",
            ])
            if not state.indexing_phases_done["scheme"]:
                # SCHEME не выгружали — обновляем .env хотя бы для ext_src
                _update_bsl_atlas_env(ext_src_path=ext_src)
            state.indexing_phases_done["ext"] = True
            add("✓ Фаза 2/3: Расширение выгружено")

        # ── Фаза 3: Переиндексация BSL Atlas ─────────────────────────────
        state.indexing_phase = "atlas"
        add("Фаза 3/3: Переиндексация BSL Atlas...")
        try:
            req = urllib.request.Request("http://localhost:8000/reindex", method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                add(f"BSL Atlas: {r.read().decode()[:120]}")
            state.indexing_phases_done["atlas"] = True
            add("✓ Фаза 3/3: Индекс BSL Atlas обновлён")
        except Exception as e:
            add(f"BSL Atlas недоступен: {e} — запустите BSL Atlas и переиндексируйте вручную")
            state.indexing_phases_skipped["atlas"] = True

        state.indexing_phase = ""
        add("✓ Индексация завершена")

    except Exception as exc:
        state.indexing_error = str(exc)
        log.exception("Indexing failed")
        add(f"ОШИБКА: {exc}")
    finally:
        state.indexing_running = False
        state.indexing_done    = True


# ---------------------------------------------------------------------------
# Запуск агента (отдельный поток → отдельный event loop)
# ---------------------------------------------------------------------------

def _run_agent(cfg: dict):
    async def _async():
        bsl = BslAtlasClient(cfg["bsl_atlas_url"])
        executor = ToolExecutor(cfg, bsl)

        try:
            await bsl.ensure_session()
            state.bsl_connected = True
            state.add_log("+", "BSL Atlas подключён")
        except Exception as e:
            state.add_log("!", f"BSL Atlas: {str(e)[:48]}")

        client = GUIAgentWSClient(cfg["backend_ws_url"], executor, cfg=cfg)
        await client.run()

    asyncio.run(_async())


# ---------------------------------------------------------------------------
# Трей
# ---------------------------------------------------------------------------

def _make_icon_image() -> Image.Image:
    """Генерирует иконку в памяти (не нужен внешний файл)."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=12, fill="#111827")
    cx, cy, r = size // 2, size // 2, 17
    d.polygon(
        [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
        outline="#FAFBFC",
        width=2,
    )
    d.ellipse([41, 41, 57, 57], fill="#2563EB")
    return img


def _show_notification(title: str, message: str):
    if state.tray_icon:
        try:
            state.tray_icon.notify(title, message)
        except Exception:
            pass


def _show_window():
    if _win:
        _win.show()


def _quit(_icon=None, _item=None):
    if state.tray_icon:
        try:
            state.tray_icon.stop()
        except Exception:
            pass
    os._exit(0)


def _tray_reindex():
    cfg = DesktopAPI().get_config()
    if cfg:
        DesktopAPI().start_indexing(cfg)
        _show_notification("Agenter", "Переиндексация запущена")
    else:
        _show_notification("Agenter", "Нет конфигурации — откройте мастер")
        _show_window()


def _tray_settings():
    _show_window()
    if _win:
        try:
            _win.evaluate_js("window.dispatchEvent(new CustomEvent('agenter:open-settings'))")
        except Exception:
            pass


def _setup_tray(icon_image: Image.Image) -> pystray.Icon:
    menu = pystray.Menu(
        pystray.MenuItem("Открыть окно",      lambda i, it: _show_window(),     default=True),
        pystray.MenuItem("Веб-кабинет",       lambda i, it: webbrowser.open("http://localhost:8080/ui/app.html")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Переиндексировать", lambda i, it: _tray_reindex()),
        pystray.MenuItem("Настройки",         lambda i, it: _tray_settings()),
        pystray.MenuItem("О программе",       lambda i, it: _show_notification("Agenter Desktop", "v1.0.0 · Локальный ИИ-ассистент для 1С")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выйти",             _quit),
    )
    icon = pystray.Icon("agenter", icon_image, "Agenter Desktop", menu)
    state.tray_icon = icon
    return icon


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _win

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    cfg = load_config()
    state.cfg = cfg

    # 1. BSL Atlas — запустить если не запущен
    threading.Thread(target=_start_bsl_atlas, daemon=True, name="bsl-atlas").start()

    # 2. Агент в фоновом потоке
    threading.Thread(target=_run_agent, args=(cfg,), daemon=True, name="agent").start()

    # 2. Трей в фоновом потоке
    icon_image = _make_icon_image()
    tray = _setup_tray(icon_image)
    threading.Thread(target=tray.run, daemon=True, name="tray").start()

    # 3. Окно в главном потоке (pywebview требует main thread)
    ui_dir = Path(__file__).parent / "ui"
    api = DesktopAPI()

    # Первый запуск → мастер 880×620, повторный → главное окно 420×560
    _setup_done = (_CONFIG_PATH.parent / ".setup_done").exists()
    _win_w, _win_h = (420, 560) if _setup_done else (880, 620)

    _win = webview.create_window(
        title="Agenter Desktop",
        url=str(ui_dir / "index.html"),
        width=_win_w,
        height=_win_h,
        resizable=False,
        frameless=True,
        easy_drag=False,
        js_api=api,
        background_color="#FFFFFF",
        confirm_close=False,
    )

    # Перехватываем закрытие окна: скрываем в трей вместо завершения
    def _on_closing():
        if _win:
            _win.hide()
        return False  # False = отменить закрытие

    _win.events.closing += _on_closing

    debug = "--debug" in sys.argv
    webview.start(debug=debug)


if __name__ == "__main__":
    main()
