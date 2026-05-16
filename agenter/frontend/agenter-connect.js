"use strict";

/**
 * agenter-connect.js
 * Связывает UI с локальным процессом Agenter (single-process архитектура).
 *
 * Десктоп-агент отсутствует — tools выполняются в том же процессе, что и UI-server.
 * Поэтому здесь убраны: pollDesktopStatus, обработка desktop_status.
 *
 * Остаётся: отправка промпта в POST /tasks + подписка на WS /ws/events
 * с обработчиками log / task_done / task_error.
 */

const AgenterApp = (() => {
  let currentTaskId = null;

  // ── Composer ──────────────────────────────────────────────────────────────

  function getRawText() {
    const ce = document.querySelector(".composer-input[contenteditable]");
    if (ce) return ce.innerText.trim();
    const ta = document.querySelector("textarea.composer-input");
    if (ta) return ta.value.trim();
    return "";
  }

  // Собирает финальный промпт из:
  //   1) текста, набранного юзером (composer-input)
  //   2) содержимого прикреплённых файлов (window.__agenterAttachments)
  // Файлы идут перед промптом блоками с явными разделителями, чтобы LLM
  // отличала их от инструкций пользователя.
  function getPrompt() {
    const text = getRawText();
    const attachAPI = window.__agenterAttachments;
    const attachments = (attachAPI && typeof attachAPI.get === "function")
      ? attachAPI.get() : [];
    if (!attachments.length) return text;

    const blocks = attachments.map(a => {
      const fence = "─".repeat(60);
      return `📎 Прикреплённый файл: ${a.name}\n${fence}\n${a.content}\n${fence}`;
    });
    if (!text) return blocks.join("\n\n");
    return blocks.join("\n\n") + "\n\n" + text;
  }

  function clearComposer() {
    const ce = document.querySelector(".composer-input[contenteditable]");
    if (ce) { ce.innerText = ""; ce.focus(); }
    const ta = document.querySelector("textarea.composer-input");
    if (ta) { ta.value = ""; ta.focus(); }
    // Очищаем прикрепления после успешной отправки.
    const attachAPI = window.__agenterAttachments;
    if (attachAPI && typeof attachAPI.clear === "function") attachAPI.clear();
  }

  function ui() { return window.__agenterUI; }

  // ── Отправка задачи ───────────────────────────────────────────────────────

  async function sendTask(prompt) {
    if (!prompt) return;
    if (!ui()) { console.warn("[Agenter] UI не готов"); return; }

    // В UI-сообщение показываем ТОЛЬКО текст юзера, без вложений в виде строк.
    // Сами вложения уходят в LLM как часть полного промпта (см. getPrompt),
    // а в UI-bubble их meta отображается отдельными чипами под текстом.
    const rawText = getRawText();
    const attachAPI = window.__agenterAttachments;
    const attachments = (attachAPI && typeof attachAPI.get === "function")
      ? attachAPI.get() : [];
    const attachmentsMeta = attachments.map(a => ({ name: a.name, size: a.size }));

    ui().startTask(rawText, attachmentsMeta);
    clearComposer();
    currentTaskId = null;

    // Выбранная юзером модель (короткий ключ типа 'sonnet-4-6'). null →
    // бэкенд возьмёт дефолт. Хранилище — localStorage + React state в
    // ChatScreen, который кладёт текущее значение в window.__selectedModel.
    const model = window.__selectedModel || null;

    try {
      const data = await AgenterAPI.createTask(prompt, "erp", model);
      currentTaskId = data.task_id;
      console.log("[Agenter] Task created:", currentTaskId, "model:", data.model);
    } catch (err) {
      console.error("[Agenter] createTask failed:", err);
      ui().setError(String(err));
    }
  }

  async function stopTask() {
    if (!currentTaskId) {
      console.warn("[Agenter] Нет активной задачи для отмены");
      return;
    }
    try {
      await AgenterAPI.cancelTask(currentTaskId);
      console.log("[Agenter] Cancel requested:", currentTaskId);
    } catch (err) {
      console.error("[Agenter] cancelTask failed:", err);
    }
  }

  // ── WS события ────────────────────────────────────────────────────────────

  function setupWS() {
    AgenterWS.on("connected", () => {
      console.log("[Agenter] WS connected");
    });

    AgenterWS.on("log", (msg) => {
      if (!ui()) return;
      if (!currentTaskId || msg.task_id === currentTaskId) {
        ui().addLog(
          msg.ts || new Date().toTimeString().slice(0, 8),
          msg.text || "",
          msg.meta || "",
          msg.kind || "step",  // step | text — UI рендерит по-разному
        );
      }
    });

    AgenterWS.on("task_done", (msg) => {
      if (msg.task_id !== currentTaskId) return;
      if (ui()) ui().setDone();
    });

    AgenterWS.on("task_error", (msg) => {
      if (msg.task_id !== currentTaskId) return;
      if (ui()) ui().setError(msg.error || "Неизвестная ошибка");
    });

    AgenterWS.on("iteration_progress", (msg) => {
      if (msg.task_id !== currentTaskId) return;
      if (ui()) ui().setIteration(msg.current, msg.total);
    });

    // ask_user: агент остановился и спрашивает юзера. UI показывает модалку,
    // юзер отвечает → AgenterAPI.submitAnswer → бэк разбуживает tool.
    AgenterWS.on("ask_user", (msg) => {
      if (msg.task_id !== currentTaskId) return;
      if (ui() && ui().showAskUser) {
        ui().showAskUser({
          taskId:   msg.task_id,
          qid:      msg.qid,
          question: msg.question || "",
          options:  Array.isArray(msg.options) ? msg.options : [],
        });
      }
    });

    AgenterWS.on("ask_user_resolved", (msg) => {
      if (msg.task_id !== currentTaskId) return;
      // Скрываем модалку (если ещё открыта — например бэк сам прислал
      // resolved из-за cancel/timeout). UI сам добавит Q+A в exec-log
      // через обычный `log` kind=text — здесь только скрываем диалог.
      if (ui() && ui().hideAskUser) ui().hideAskUser(msg.qid);
    });

    // ── Sessions / Phases / Snapshots (ADR-018) ──────────────────
    // Транслируем события в React через window.__agenterUI.

    AgenterWS.on("session_updated", (msg) => {
      if (ui() && ui().onSessionUpdated) ui().onSessionUpdated(msg);
    });

    AgenterWS.on("session_reset", (msg) => {
      if (ui() && ui().onSessionReset) ui().onSessionReset(msg);
    });

    AgenterWS.on("phase_committed", (msg) => {
      if (ui() && ui().onPhaseCommitted) ui().onPhaseCommitted(msg);
    });

    AgenterWS.on("phase_failed", (msg) => {
      if (ui() && ui().onPhaseFailed) ui().onPhaseFailed(msg);
    });

    AgenterWS.on("task_state_changed", (msg) => {
      if (ui() && ui().onTaskStateChanged) ui().onTaskStateChanged(msg);
    });

    AgenterWS.on("snapshot_created", (msg) => {
      if (ui() && ui().onSnapshotCreated) ui().onSnapshotCreated(msg);
    });

    AgenterWS.on("snapshot_restored", (msg) => {
      if (ui() && ui().onSnapshotRestored) ui().onSnapshotRestored(msg);
    });

    // ── Operations (выгрузка/индексация/загрузка вне LLM-цикла) ──
    // Транслируем события в window.__opsUI который держит RightPanel.

    const opsUi = () => window.__opsUI;

    AgenterWS.on("op_started", (msg) => {
      if (opsUi()) opsUi().opStarted(msg.operation, msg.at);
    });

    AgenterWS.on("op_log", (msg) => {
      if (opsUi()) opsUi().opLog(msg.operation, msg.ts, msg.text, msg.meta);
    });

    AgenterWS.on("op_done", (msg) => {
      if (opsUi()) opsUi().opDone(msg.operation, msg.info, msg.duration_sec);
    });

    AgenterWS.on("op_error", (msg) => {
      if (opsUi()) opsUi().opError(msg.operation, msg.error);
    });

    // desktop_status больше не отслеживаем — в local-режиме всегда готовы.
    // Если backend пришлёт его (для совместимости со старым UI) — игнорируем.

    AgenterWS.connect();
  }

  // ── Обработчики кнопки и Ctrl+Enter ──────────────────────────────────────

  function setupInput() {
    document.addEventListener("click", (e) => {
      const btn = e.target.closest(".send-btn.primary");
      if (!btn) return;
      // Кнопка действует и как «Отправить», и как «Стоп» — отличаются data-action.
      const action = btn.dataset.action || "send";
      if (action === "stop") {
        stopTask();
      } else {
        sendTask(getPrompt());
      }
    });

    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        if (e.target.closest(".composer-input")) {
          e.preventDefault();
          // Если задача уже идёт — Ctrl+Enter ничего не делает (избегаем гонок).
          // Чтобы стопнуть — нажми кнопку «Стоп».
          const btn = document.querySelector(".send-btn.primary");
          if (btn && btn.dataset.action === "stop") return;
          sendTask(getPrompt());
        }
      }
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  function init() {
    const ready = () => {
      setupWS();
      setupInput();
      console.log("[Agenter] Ready (local mode). Backend: http://localhost:8080");
    };

    if (document.readyState === "complete") {
      setTimeout(ready, 600);
    } else {
      window.addEventListener("load", () => setTimeout(ready, 600));
    }
  }

  return { init, sendTask };
})();

AgenterApp.init();
