"""
agenter/app/mcp_registry.py — универсальный реестр MCP-серверов.

Цель: убрать N×M-проблему регистрации tools. Сейчас каждый новый MCP-сервер
требовал ручной правки backend/main.py (TOOL_DEFINITIONS) + desktop/main.py
(case в execute). Регистрация через config.json:

    "mcp_servers": [
      {"name": "bsl-atlas",      "transport": "http", "url": "http://localhost:8000"},
      {"name": "bsl-platform",   "transport": "http", "url": "http://localhost:8010"},
      {"name": "ssl",            "transport": "http", "url": "http://localhost:8020"}
    ]

Принципы:
  • Persistent aiohttp.ClientSession per сервер (не пересоздаём на каждый вызов)
  • Lazy initialize: MCP handshake выполняется при первом call_tool, не при старте
  • Dynamic tools discovery через tools/list (кешируется в self.tools_cache)
  • Health-check: GET /health если есть, иначе ping через initialize
  • Backward-compat: McpHttpClient.call_tool() / .ensure_session() — те же
    сигнатуры что у старого BslAtlasClient, чтобы ToolExecutor не переписывать.

Phase 1: только HTTP transport (JSON-RPC POST + SSE responses).
Phase 2 (после регрессии): STDIO transport (для Java/Node MCP).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


# ── Конфигурация одного MCP-сервера ──────────────────────────────────────────


@dataclass
class McpServerConfig:
    name: str                        # уникальное имя, напр. "bsl-atlas"
    transport: str = "http"          # "http" | "stdio" (stdio — позже)
    url: str = ""                    # для http
    command: str = ""                # для stdio (путь к exe/jar)
    args: list[str] = field(default_factory=list)  # для stdio
    enabled: bool = True
    init_timeout: int = 30           # сек на initialize
    call_timeout: int = 60           # сек на один tool call
    health_interval: int = 30        # сек между health-check (используется monitor'ом)
    description: str = ""            # человекочитаемое описание для UI/документации


# ── HTTP MCP клиент (как старый BslAtlasClient, но persistent) ───────────────


class McpHttpClient:
    """
    Клиент к одному HTTP MCP-серверу. Спецификация MCP-2025-03-26:
      POST {url}/mcp с JSON-RPC payload
      Accept: application/json, text/event-stream
      response: SSE-поток с одним `data: {...}` событием

    Persistent session, lazy initialize, retry на ConnectionError.
    """

    def __init__(self, cfg: McpServerConfig):
        self.cfg = cfg
        self.session: aiohttp.ClientSession | None = None  # persistent!
        self.session_id: str | None = None                 # mcp-session-id
        self.tools_cache: list[dict] = []
        self.healthy: bool = False
        self.last_check: float = 0.0
        self._call_counter = 0
        self._init_lock = asyncio.Lock()

    # Backward-compat: старый BslAtlasClient имел свойство base_url.
    # Несколько мест в app/main.py (например save_config) на него полагаются.
    @property
    def base_url(self) -> str:
        return self.cfg.url

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self):
        """Создать persistent ClientSession. Не делаем initialize — он lazy."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def stop(self):
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
        self.session_id = None
        self.healthy = False

    # ── MCP protocol ─────────────────────────────────────────────────────

    async def _initialize(self):
        """MCP handshake. Возвращает mcp-session-id из заголовков."""
        payload = {
            "jsonrpc": "2.0", "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "agenter", "version": "1.0"},
            },
        }
        assert self.session is not None
        async with self.session.post(
            f"{self.cfg.url}/mcp",
            json=payload,
            headers={"Accept": "application/json, text/event-stream"},
            timeout=aiohttp.ClientTimeout(total=self.cfg.init_timeout),
        ) as resp:
            self.session_id = resp.headers.get("mcp-session-id")
            if not self.session_id:
                raise RuntimeError(
                    f"MCP {self.cfg.name}: нет session-id в ответе на initialize"
                )
            log.info("MCP %s: session=%s", self.cfg.name, self.session_id)

    async def ensure_session(self):
        """Идемпотентный gateway: при первом вызове делает initialize,
        дальше — no-op. Под locка чтобы избежать гонки при первом
        одновременном tool call из нескольких корутин."""
        if self.session is None or self.session.closed:
            await self.start()
        if not self.session_id:
            async with self._init_lock:
                if not self.session_id:  # double-check
                    await self._initialize()

    def _parse_response(self, text: str) -> Any:
        """Разбор MCP-ответа. Современные серверы (MCP-2025-03-26) отвечают
        SSE-потоком: `event: message\\ndata: {...}`. Старые/упрощённые могут
        вернуть прямой JSON. Стратегия:
          1. Ищем строки `data: {...}` в порядке появления — это SSE.
          2. Если ни одной не нашли — пробуем весь текст как JSON.
        """
        # SSE-сканирование (первое не-пустое data:)
        for line in text.split("\n"):
            line = line.rstrip("\r")
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw:
                continue
            data = json.loads(raw)
            if "error" in data:
                raise RuntimeError(
                    f"MCP {self.cfg.name} error: "
                    f"{data['error'].get('message', data['error'])}"
                )
            if "result" in data:
                return data["result"]
        # Fallback: прямой JSON
        try:
            data = json.loads(text)
            if "error" in data:
                raise RuntimeError(
                    f"MCP {self.cfg.name} error: "
                    f"{data['error'].get('message', data['error'])}"
                )
            if "result" in data:
                return data["result"]
        except json.JSONDecodeError:
            pass
        raise RuntimeError(
            f"MCP {self.cfg.name}: не нашёл result в ответе: {text[:200]}"
        )

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """tools/call. Возвращает JSON-строку (как старый BslAtlasClient).
        При ClientError сбрасываем session_id — следующий вызов
        переинициализирует сессию."""
        await self.ensure_session()
        self._call_counter += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._call_counter,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        try:
            assert self.session is not None
            async with self.session.post(
                f"{self.cfg.url}/mcp",
                json=payload,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "mcp-session-id": self.session_id or "",
                },
                timeout=aiohttp.ClientTimeout(total=self.cfg.call_timeout),
            ) as resp:
                text = await resp.text()
                result = self._parse_response(text)
                return json.dumps(result, ensure_ascii=False)
        except aiohttp.ClientError as e:
            self.session_id = None
            self.healthy = False
            raise RuntimeError(f"MCP {self.cfg.name} недоступен: {e}")

    async def list_tools(self) -> list[dict]:
        """tools/list — список tools от сервера. Кешируется."""
        await self.ensure_session()
        self._call_counter += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._call_counter,
            "method": "tools/list",
            "params": {},
        }
        try:
            assert self.session is not None
            async with self.session.post(
                f"{self.cfg.url}/mcp",
                json=payload,
                headers={
                    "Accept": "application/json, text/event-stream",
                    "mcp-session-id": self.session_id or "",
                },
                timeout=aiohttp.ClientTimeout(total=self.cfg.call_timeout),
            ) as resp:
                text = await resp.text()
                result = self._parse_response(text)
                tools = result.get("tools", []) if isinstance(result, dict) else []
                self.tools_cache = tools
                return tools
        except aiohttp.ClientError as e:
            self.session_id = None
            raise RuntimeError(f"MCP {self.cfg.name} tools/list failed: {e}")

    async def health_check(self) -> bool:
        """Лёгкая проверка. Сначала GET /health (Agenter использует у BSL Atlas),
        если не отвечает — пробуем ensure_session как live-test."""
        try:
            assert self.session is not None
            async with self.session.get(
                f"{self.cfg.url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                self.healthy = resp.status == 200
                self.last_check = time.time()
                return self.healthy
        except Exception:
            pass
        # /health не отвечает — пробуем MCP-инициализацию
        try:
            await self.ensure_session()
            self.healthy = True
        except Exception:
            self.healthy = False
        self.last_check = time.time()
        return self.healthy


# ── Реестр ───────────────────────────────────────────────────────────────────


class McpServerRegistry:
    """Реестр MCP-серверов. Управляет жизненным циклом всех клиентов.

    Использование:
        reg = McpServerRegistry.from_config(app_config)
        await reg.start_all()                               # в lifespan startup
        result = await reg.call("bsl-atlas", "search_function", {"name": "..."})
        await reg.stop_all()                                # в lifespan shutdown
    """

    def __init__(self, configs: list[McpServerConfig]):
        self.clients: dict[str, McpHttpClient] = {}
        for cfg in configs:
            if not cfg.enabled:
                log.info("MCP %s: disabled — пропускаем", cfg.name)
                continue
            if cfg.transport == "http":
                self.clients[cfg.name] = McpHttpClient(cfg)
            elif cfg.transport == "stdio":
                log.warning(
                    "MCP %s: stdio transport пока не реализован — пропускаем",
                    cfg.name,
                )
            else:
                log.warning("MCP %s: неизвестный transport='%s'", cfg.name, cfg.transport)

    @classmethod
    def from_config(cls, app_cfg: dict) -> McpServerRegistry:
        """Строит из config.json. Backward-compat: если есть bsl_atlas_url
        и нет mcp_servers — создаём дефолтную запись для BSL Atlas, чтобы
        старые установки продолжали работать без правки конфига."""
        raw = app_cfg.get("mcp_servers", [])
        configs: list[McpServerConfig] = []
        for r in raw:
            try:
                configs.append(McpServerConfig(**r))
            except TypeError as e:
                log.warning("MCP config-entry error: %s — пропускаем: %s", e, r)
        # Backward-compat: дефолтная запись для BSL Atlas
        names = {c.name for c in configs}
        if "bsl-atlas" not in names and app_cfg.get("bsl_atlas_url"):
            configs.append(McpServerConfig(
                name="bsl-atlas",
                transport="http",
                url=app_cfg["bsl_atlas_url"],
            ))
        return cls(configs)

    async def start_all(self):
        await asyncio.gather(
            *(c.start() for c in self.clients.values()),
            return_exceptions=True,
        )
        log.info("MCP registry started: %s", list(self.clients.keys()))

    async def stop_all(self):
        await asyncio.gather(
            *(c.stop() for c in self.clients.values()),
            return_exceptions=True,
        )

    def get(self, name: str) -> McpHttpClient | None:
        """Возвращает клиент по имени, для backward-compat с прямым
        использованием BslAtlasClient. Если сервер не зарегистрирован —
        вернёт None."""
        return self.clients.get(name)

    async def call(self, server: str, tool: str, args: dict) -> str:
        client = self.clients.get(server)
        if client is None:
            raise RuntimeError(
                f"MCP сервер '{server}' не зарегистрирован. "
                f"Доступные: {list(self.clients.keys())}"
            )
        return await client.call_tool(tool, args)

    async def health_summary(self) -> dict[str, dict]:
        """Для UI: {name: {status: 'healthy'|'unhealthy', url, last_check}}.
        Параллельный опрос всех клиентов, ошибки не валят остальных."""
        async def _one(name: str, client: McpHttpClient) -> tuple[str, dict]:
            try:
                ok = await client.health_check()
                status = "healthy" if ok else "unhealthy"
            except Exception as e:
                log.debug("Health-check %s failed: %s", name, e)
                status = "unhealthy"
            return name, {
                "status": status,
                "url": client.cfg.url,
                "last_check": client.last_check,
                "tools_known": len(client.tools_cache),
            }

        results = await asyncio.gather(
            *(_one(n, c) for n, c in self.clients.items()),
            return_exceptions=False,
        )
        return dict(results)

    def has(self, server: str) -> bool:
        return server in self.clients

    def names(self) -> list[str]:
        return list(self.clients.keys())
