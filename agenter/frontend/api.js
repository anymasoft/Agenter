"use strict";

const AgenterAPI = (() => {
  const BASE = "http://localhost:8080";

  async function createTask(prompt, projectId = "erp", model = null) {
    const body = { prompt, project_id: projectId };
    if (model) body.model = model;
    const resp = await fetch(`${BASE}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    return resp.json();
  }

  // GET /models — список моделей для UI dropdown
  async function listModels() {
    const resp = await fetch(`${BASE}/models`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function getTask(taskId) {
    const resp = await fetch(`${BASE}/tasks/${taskId}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function cancelTask(taskId) {
    const resp = await fetch(`${BASE}/tasks/${taskId}/cancel`, { method: "POST" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  // ask_user: отправить ответ юзера на висящий вопрос агента. Разбуживает
  // tool ask_user на бэке. qid — опц., для верификации актуальности.
  async function submitAnswer(taskId, answer, qid) {
    const resp = await fetch(`${BASE}/tasks/${taskId}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer: String(answer || ""), qid: qid || null }),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    return resp.json();
  }

  // ── Sessions / Phases / Rollback ──────────────────────────────────────────
  // Auto-resume контекста между задачами + откат ext_src/ при сбое.
  // См. ADR-018 (agenter/docs/DECISIONS.md).

  // Текущая Claude SDK сессия проекта (для бейджа «🔗 Контекст активен»).
  async function getSession(projectId = "erp") {
    const resp = await fetch(`${BASE}/sessions/${encodeURIComponent(projectId)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  // Сброс сессии — следующая задача начнётся с чистого контекста.
  // Удаляется sdk_session_id и связанный snapshot.
  async function resetSession(projectId = "erp") {
    const resp = await fetch(
      `${BASE}/sessions/${encodeURIComponent(projectId)}/reset`,
      { method: "POST" },
    );
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    return resp.json();
  }

  // Фазы задачи (committed/failed/...) + final_state. UI рендерит PhasePill
  // и TaskFinalStatus.
  async function getTaskPhases(taskId) {
    const resp = await fetch(`${BASE}/tasks/${taskId}/phases`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  // Откат ext_src/ к snapshot'у сессии. БД 1С НЕ откатывается (это решает
  // юзер вручную через дополнительный db_load после успешного rollback'а).
  async function rollbackTask(taskId) {
    const resp = await fetch(`${BASE}/tasks/${taskId}/rollback`, { method: "POST" });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    return resp.json();
  }

  async function getHealth() {
    const resp = await fetch(`${BASE}/health`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function getDesktopStatus() {
    try {
      const resp = await fetch(`${BASE}/desktop/status`);
      if (!resp.ok) return { connected: false };
      return resp.json();
    } catch {
      return { connected: false };
    }
  }

  async function getConfig() {
    const resp = await fetch(`${BASE}/config`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function saveConfig(cfg) {
    const resp = await fetch(`${BASE}/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    return resp.json();
  }

  async function checkConfig() {
    const resp = await fetch(`${BASE}/config/check`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function runOperation(opName) {
    const resp = await fetch(`${BASE}/ops/${opName}`, { method: "POST" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function getOpsState() {
    const resp = await fetch(`${BASE}/ops/state`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  // ── Метаданные конфигурации 1С ────────────────────────────────────────────
  async function getMetadataTree(root = null, slim = true) {
    const params = new URLSearchParams();
    if (root) params.set("root", root);
    if (!slim) params.set("slim", "false");
    const resp = await fetch(`${BASE}/metadata/tree?${params.toString()}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function getMetadataObject(key, root = null) {
    const params = new URLSearchParams({ key });
    if (root) params.set("root", root);
    const resp = await fetch(`${BASE}/metadata/object?${params.toString()}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function invalidateMetadata(root = null) {
    const url = root ? `${BASE}/metadata/invalidate?root=${encodeURIComponent(root)}`
                     : `${BASE}/metadata/invalidate`;
    const resp = await fetch(url, { method: "POST" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  /**
   * Открыть SSE-стрим прогрессивной загрузки дерева.
   *
   * @param {object} handlers - { onStart, onType, onDone, onError }
   * @param {string} [root]
   * @returns {EventSource}
   */
  function streamMetadataTree(handlers, root = null) {
    const params = new URLSearchParams();
    if (root) params.set("root", root);
    const url = `${BASE}/metadata/tree/stream?${params.toString()}`;
    const es = new EventSource(url);
    if (handlers.onStart) {
      es.addEventListener("start", (e) => handlers.onStart(JSON.parse(e.data)));
    }
    if (handlers.onType) {
      es.addEventListener("type-loaded", (e) => handlers.onType(JSON.parse(e.data)));
    }
    if (handlers.onDone) {
      es.addEventListener("done", (e) => {
        handlers.onDone(JSON.parse(e.data));
        es.close();
      });
    }
    if (handlers.onError) {
      es.addEventListener("error", (e) => {
        if (e.data) {
          try { handlers.onError(JSON.parse(e.data)); } catch { handlers.onError({ message: "stream error" }); }
        }
      });
    }
    return es;
  }

  return {
    createTask, getTask, cancelTask, submitAnswer, getHealth, getDesktopStatus,
    getConfig, saveConfig, checkConfig,
    runOperation, getOpsState, listModels,
    getMetadataTree, getMetadataObject, invalidateMetadata, streamMetadataTree,
    // Sessions / Phases / Rollback (ADR-018)
    getSession, resetSession, getTaskPhases, rollbackTask,
  };
})();

window.AgenterAPI = AgenterAPI;
