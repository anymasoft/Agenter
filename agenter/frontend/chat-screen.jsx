/* Main chat workspace screen */

const { useState, useEffect, useRef } = React;

function nowTs() {
  return new Date().toTimeString().slice(0, 8);
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

const Sidebar = ({ config = {} }) => {
  const hasProject = Boolean(config.extension || config.name);
  const openSetup = () => {
    if (typeof window.__openSetup === "function") window.__openSetup();
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"></div>
        <div className="brand-name">Agenter</div>
        <div className="brand-version">v0.9.4</div>
      </div>

      <div className="side-section">
        <div className="side-section-header">
          <div className="side-label">Мои базы</div>
          <div className="side-count">{hasProject ? 1 : 0}</div>
        </div>
        {hasProject ? (
          <div className="base-card active" style={{ cursor: "default" }}>
            <div className="base-icon">{(config.extension || "EXT").slice(0, 3).toUpperCase()}</div>
            <div className="base-meta">
              <div className="base-name">{config.name || config.extension}</div>
              <div className="base-sub">
                <span className="dot green"></span>
                <span>{config.extension}</span>
              </div>
            </div>
          </div>
        ) : (
          <div style={{ padding: "12px 8px", fontSize: 12, color: "var(--text-4)", textAlign: "center", lineHeight: 1.6 }}>
            Нет подключённых баз
          </div>
        )}
        {!hasProject && (
          <button className="add-base" onClick={openSetup}>
            <Icon name="plus" size={13} />
            <span>Подключить базу</span>
          </button>
        )}
      </div>

      <div className="divider"></div>

      {/* Метаданные конфигурации — главный navigator проекта 1С.
          Занимает всё свободное вертикальное место sidebar (flex: 1). */}
      <div
        className="side-section"
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          paddingBottom: 8,
        }}
      >
        <div className="side-section-header">
          <div className="side-label">Метаданные конфигурации</div>
          <span
            className="side-count"
            title="Дерево объектов 1С (SCHEME)"
            style={{ fontWeight: 500, fontSize: 10, letterSpacing: 0.4 }}
          >
            SCHEME
          </span>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflow: "hidden", padding: "0 8px" }}>
          {typeof MetadataTree !== "undefined" ? (
            <MetadataTree config={config} autoLoad={false} />
          ) : (
            <div
              style={{
                padding: "12px 8px",
                fontSize: 12,
                color: "var(--text-4)",
                textAlign: "center",
                lineHeight: 1.6,
              }}
            >
              MetadataTree не загружен
            </div>
          )}
        </div>
      </div>

      <div className="divider"></div>

      {/* История задач — оперативная справка, фиксированная высота. */}
      <div
        className="side-section"
        style={{ maxHeight: 200, overflow: "auto", paddingBottom: 8 }}
      >
        <div className="side-section-header">
          <div className="side-label">История задач</div>
          <Icon name="history" size={12} className="ic-sm" />
        </div>
        <div className="history-list">
          <div style={{ padding: "12px 8px", fontSize: 12, color: "var(--text-4)", textAlign: "center", lineHeight: 1.6 }}>
            Нет задач
          </div>
        </div>
      </div>

      <div className="sidebar-footer">
        <div className="avatar">—</div>
        <div className="user-meta">
          <div className="user-name">Пользователь</div>
          <div className="user-org">{config.name || "Local mode"}</div>
        </div>
        <button
          onClick={openSetup}
          title="Настройки"
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "none",
            cursor: "pointer",
            padding: 6,
            borderRadius: 6,
            color: "var(--text-3)",
            display: "inline-flex", alignItems: "center", justifyContent: "center",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(15,27,42,0.05)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
        >
          <Icon name="settings" size={14} className="ic" />
        </button>
      </div>
    </aside>
  );
};

// ── Markdown renderer ────────────────────────────────────────────────────────
// Использует marked + DOMPurify, подключённые в app.html через CDN.

const MarkdownBlock = ({ text, ts }) => {
  const html = React.useMemo(() => {
    if (typeof window.marked === "undefined") return null;
    try {
      let rendered = window.marked.parse(text || "");
      if (typeof window.DOMPurify !== "undefined") {
        rendered = window.DOMPurify.sanitize(rendered, {
          // Разрешаем стандартные элементы markdown
          ALLOWED_TAGS: [
            "p", "br", "strong", "em", "del", "ins", "code", "pre", "blockquote",
            "h1", "h2", "h3", "h4", "h5", "h6",
            "ul", "ol", "li",
            "table", "thead", "tbody", "tr", "th", "td",
            "a", "img", "hr", "span", "div",
          ],
          ALLOWED_ATTR: ["href", "title", "alt", "src", "class", "target", "rel"],
        });
      }
      return rendered;
    } catch (e) {
      console.error("[Agenter] markdown render failed:", e);
      return null;
    }
  }, [text]);

  // Fallback если marked не загрузился: показать как plain text с переносами
  if (html === null) {
    return (
      <div className="md-block md-fallback">
        {ts && <span className="md-ts">[{ts}]</span>}
        <pre style={{ margin: 0, fontFamily: "inherit", whiteSpace: "pre-wrap" }}>{text}</pre>
      </div>
    );
  }

  return (
    <div className="md-block">
      {ts && <span className="md-ts">[{ts}]</span>}
      <div className="md-body" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
};


// ── ExecLog ───────────────────────────────────────────────────────────────────

const ExecLog = ({ rows, taskStatus, iter }) => {
  // Подсчитываем только технические step-строки для статусов done/active
  const stepIndices = rows
    .map((r, i) => (r.kind !== "text" ? i : -1))
    .filter(i => i >= 0);
  const lastStepIdx = stepIndices[stepIndices.length - 1];

  const getRowStatus = (i) => {
    if (taskStatus === "done" || taskStatus === "error") return "done";
    if (taskStatus === "running") {
      if (i < lastStepIdx) return "done";
      if (i === lastStepIdx) return "active";
    }
    return "pending";
  };

  let stateLabel;
  if (taskStatus === "running") {
    // Во время выполнения показываем прогресс итерации: "RUNNING · 12/50"
    stateLabel = iter
      ? `RUNNING · ${iter.current}/${iter.total}`
      : "RUNNING";
  } else if (taskStatus === "done")  stateLabel = "COMPLETED";
  else if (taskStatus === "error")   stateLabel = "ERROR";
  else                                stateLabel = "IDLE";

  return (
    <div className="exec-log">
      <div className="exec-log-head">
        <Icon name="terminal" size={13} className="ic" style={{ color: "var(--text-2)" }} />
        <div className="exec-title">Выполнение задачи</div>
        <div
          className={`exec-state ${taskStatus === "running" ? "running" : ""}`}
          style={taskStatus === "error" ? { color: "#ef4444" } : {}}
        >
          <span className="pulse"></span>
          <span>{stateLabel}</span>
        </div>
      </div>
      <div className="exec-rows">
        {rows.map((r, i) => {
          // Текстовые блоки от LLM → markdown
          if (r.kind === "text") {
            return <MarkdownBlock key={i} text={r.text} ts={r.ts} />;
          }
          // Per-turn usage (text="tokens") и финальная сводка ("📊 Итого") —
          // мелкий серый стиль, чтобы не шумели в логе.
          const isUsage = r.text === "tokens" || r.text.startsWith("📊");
          return (
            <div
              key={i}
              className={`exec-row ${getRowStatus(i)} ${isUsage ? "usage" : ""}`}
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <span className="ts">[{r.ts}]</span>
              <span className="marker"></span>
              <span className="text">{r.text}</span>
              <span className="meta">{r.meta || ""}</span>
            </div>
          );
        })}
      </div>
      <div className="exec-foot">
        {taskStatus === "done" && (
          <span style={{ marginLeft: "auto" }} className="ok">
            <span className="check"><Icon name="check" size={8} /></span>
            {stepIndices.length} шагов · выполнено
          </span>
        )}
      </div>
    </div>
  );
};

// ── Message components ────────────────────────────────────────────────────────

// Форматирование размера файла для чипа: 320 → "320 Б", 12000 → "11.7 КБ", и т.д.
function fmtFileSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024)       return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(2)} МБ`;
}

const UserMessage = ({ text, attachments }) => {
  const atts = Array.isArray(attachments) ? attachments : [];
  return (
    <div className="msg user">
      <div className="bubble">
        {text && <div className="bubble-text">{text}</div>}
        {atts.length > 0 && (
          <div className="bubble-attachments">
            {atts.map((a, i) => (
              <span
                key={i}
                className="bubble-attach-chip"
                title={`${a.name}${a.size != null ? ` · ${a.size} байт` : ""}`}
              >
                <Icon name="paperclip" size={10} />
                <span className="bubble-attach-name">{a.name}</span>
                {a.size != null && (
                  <span className="bubble-attach-size">{fmtFileSize(a.size)}</span>
                )}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// ── TaskFinalStatus ──────────────────────────────────────────────────────────
// Заменяет старое ложное «Готово. Изменения применены в 1С». Показывает
// РЕАЛЬНОЕ состояние применения изменений в БД на основе подсчёта успешных
// db_load в orchestrator'е (см. ADR-018, _compute_final_state в main.py):
//   applied — все запланированные фазы committed (db_load успешен)
//   partial — какие-то фазы committed, но не все (BUDGET / ошибка по дороге)
//   staged  — изменения только в ext_src/, db_load не вызывался ни разу
//   failed  — задача в статусе error и нет успешных db_load
//   (fallback) — taskState не пришёл, показываем нейтральный вариант
const TaskFinalStatus = ({ taskState, status, onRollback, canRollback }) => {
  // Не дождались task_state_changed (старая задача / WS пропустили) —
  // показываем нейтральный fallback. Не врём: «Задача завершена» без указания
  // что она применена в БД.
  if (!taskState) {
    if (status === "done") {
      return (
        <div className="final-summary task-status-done-fallback">
          <div className="final-summary-head">
            <span className="final-status-icon success"><Icon name="check" size={11} /></span>
            <strong>Задача завершена</strong>
          </div>
          <div className="final-summary-body">
            Откройте 1С и проверьте результат. Состояние применения в БД будет
            обновлено через несколько секунд.
          </div>
        </div>
      );
    }
    return null;  // error отрисуется ниже отдельным блоком
  }

  const fs = taskState.finalState;
  const committed = taskState.phasesCommitted || 0;
  const total     = taskState.phasesTotal || 0;
  const phaseLine = total > 0 ? `${committed} из ${total} фаз` : `${committed} db_load`;

  if (fs === "applied") {
    return (
      <div className="final-summary task-status-applied">
        <div className="final-summary-head">
          <span className="final-status-icon success"><Icon name="check" size={11} /></span>
          <strong>Применено в БД 1С</strong>
          <span className="final-status-meta">{phaseLine}</span>
        </div>
        <div className="final-summary-body">
          Изменения загружены в базу. Откройте 1С и проверьте результат — если
          что-то нужно скорректировать, напишите в чат.
        </div>
      </div>
    );
  }

  if (fs === "partial") {
    return (
      <div className="final-summary task-status-partial">
        <div className="final-summary-head">
          <span className="final-status-icon warn">⚠</span>
          <strong>Частично применено в БД</strong>
          <span className="final-status-meta">{phaseLine}</span>
        </div>
        <div className="final-summary-body">
          Часть фаз успешно применена в БД, но задача не доведена до конца.
          В ext_src/ остались незавершённые изменения. Продолжите задачу, или
          откатите ext_src/ к моменту до начала сессии.
        </div>
        {canRollback && (
          <div className="summary-actions">
            <button className="chip rollback-btn" onClick={onRollback}>
              <Icon name="refresh-cw" size={11} /> Откатить ext_src/
            </button>
          </div>
        )}
      </div>
    );
  }

  if (fs === "staged") {
    return (
      <div className="final-summary task-status-staged">
        <div className="final-summary-head">
          <span className="final-status-icon warn">⚠</span>
          <strong>Только в ext_src/, БД не обновлена</strong>
        </div>
        <div className="final-summary-body">
          Изменения подготовлены в файлах расширения, но НЕ загружены в базу
          1С (db_load не вызывался). Если хотите применить — напишите «загрузи
          в БД». Если хотите откатить — кнопка ниже.
        </div>
        {canRollback && (
          <div className="summary-actions">
            <button className="chip rollback-btn" onClick={onRollback}>
              <Icon name="refresh-cw" size={11} /> Откатить ext_src/
            </button>
          </div>
        )}
      </div>
    );
  }

  // legacy — задача создана ДО ADR-018 (без session_id и tracking'а).
  // Sprint 2 S2.4: не врём «applied»/«staged», говорим как есть.
  if (fs === "legacy") {
    return (
      <div className="final-summary task-status-legacy">
        <div className="final-summary-head">
          <span className="final-status-icon neutral">•</span>
          <strong>Завершено (статус не отслеживался)</strong>
        </div>
        <div className="final-summary-body">
          Задача выполнена до того, как Agenter научился точно различать
          «применено в БД» / «только в ext_src/». Если хотите проверить — откройте
          1С и посмотрите.
        </div>
      </div>
    );
  }

  // failed
  return (
    <div className="final-summary task-status-failed">
      <div className="final-summary-head">
        <span className="final-status-icon error">✕</span>
        <strong>Не применено в БД</strong>
      </div>
      <div className="final-summary-body">
        Задача завершилась с ошибкой до того, как был вызван db_load.
        База 1С не изменена.
      </div>
      {canRollback && (
        <div className="summary-actions">
          <button className="chip rollback-btn" onClick={onRollback}>
            <Icon name="refresh-cw" size={11} /> Откатить ext_src/
          </button>
        </div>
      )}
    </div>
  );
};


// ── PhasePill ────────────────────────────────────────────────────────────────
// Маленький чип внутри ExecLog показывающий статус фазы. Зелёный для
// committed, серый для pending/running, красный для failed.
const PhasePill = ({ phase }) => {
  const cls = `phase-pill phase-pill-${phase.status || "pending"}`;
  const label = phase.title || `Фаза ${phase.index}`;
  return (
    <span className={cls} title={phase.error_msg || ""}>
      {phase.status === "committed" && <Icon name="check" size={9} />}
      {phase.status === "failed" && "✕"}
      {label}
    </span>
  );
};


// ── ConfirmDialog ────────────────────────────────────────────────────────────
// Универсальный модальный confirm. Используется для reset session / rollback.
// Подсветка cancel-варианта по умолчанию — деструктивные действия требуют
// двойного click'а через эту обёртку.
const ConfirmDialog = ({ title, message, confirmLabel, danger, onConfirm, onCancel }) => {
  return (
    <div className="ask-user-overlay" onClick={onCancel}>
      <div className="ask-user-dialog" onClick={e => e.stopPropagation()} style={{ maxWidth: 480 }}>
        <div className="ask-user-question">{title}</div>
        <div style={{ fontSize: 13, color: "var(--text-2)", marginBottom: 16, lineHeight: 1.5 }}>
          {message}
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="chip" onClick={onCancel}>Отмена</button>
          <button
            className={`chip ${danger ? "rollback-btn" : "primary"}`}
            onClick={onConfirm}
          >
            {confirmLabel || "Подтвердить"}
          </button>
        </div>
      </div>
    </div>
  );
};


// ── SessionBadge ─────────────────────────────────────────────────────────────
// Тонкая полоска над composer: «🔗 Контекст активен (N задач)». Клик по
// «🆕 Новая» — открывает confirm на сброс сессии (ADR-018, auto-resume).
const SessionBadge = ({ session, onReset, disabled }) => {
  if (!session.active) {
    return (
      <div className="session-badge session-badge-inactive">
        <span className="session-dot session-dot-new"></span>
        <span>Новая сессия — контекст будет создан с первой задачей</span>
      </div>
    );
  }
  return (
    <div className="session-badge">
      <span className="session-dot session-dot-active"></span>
      <span>
        🔗 Контекст активен · {session.tasksCount} {pluralize(session.tasksCount, ["задача", "задачи", "задач"])}
        {session.hasSnapshot && <span className="session-snapshot-mark" title="Snapshot ext_src/ доступен для отката"> · snapshot ✓</span>}
      </span>
      <button
        className="session-reset-btn"
        onClick={onReset}
        disabled={disabled}
        title="Начать новую сессию (контекст прошлых задач будет потерян)"
      >
        <Icon name="refresh-cw" size={11} /> Новая
      </button>
    </div>
  );
};

// Простой плюрализатор для русского "1 задача / 2 задачи / 5 задач"
function pluralize(n, forms) {
  const m100 = n % 100;
  const m10  = n % 10;
  if (m100 >= 11 && m100 <= 14) return forms[2];
  if (m10 === 1) return forms[0];
  if (m10 >= 2 && m10 <= 4) return forms[1];
  return forms[2];
}


const AgentMessage = ({ msg, taskState, onRollback, canRollback }) => {
  const { logs, status, errorMsg, time, iter } = msg;

  return (
    <div className="msg agent">
      <div className="agent-avatar"></div>
      <div className="agent-body">
        <div className="agent-head">
          <span className="agent-name">Agenter</span>
          <span className="agent-time">{time}</span>
        </div>

        {logs.length > 0 && (
          <ExecLog rows={logs} taskStatus={status} iter={iter} />
        )}

        {/* Список фаз с их статусами (если задача была фазированной) */}
        {taskState && taskState.phases && taskState.phases.length > 0 && (
          <div className="phase-list">
            {taskState.phases.map(p => <PhasePill key={p.index} phase={p} />)}
          </div>
        )}

        {/* Финал задачи: ЧЕСТНЫЙ статус применения в БД на основе db_load */}
        {(status === "done" || status === "error") && (
          <TaskFinalStatus
            taskState={taskState}
            status={status}
            onRollback={onRollback}
            canRollback={canRollback}
          />
        )}

        {status === "error" && (
          <div className="final-summary" style={{ borderColor: "#fecaca", background: "#fff5f5", marginTop: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <span style={{ width: 18, height: 18, borderRadius: "50%", background: "#ef4444", color: "#fff", display: "grid", placeItems: "center", fontSize: 11 }}>✕</span>
              <strong style={{ fontFamily: "var(--font-display)", fontSize: 13.5, color: "#dc2626" }}>Текст ошибки</strong>
            </div>
            <div style={{ color: "#b91c1c", fontFamily: "var(--font-mono)", fontSize: 11.5 }}>{errorMsg}</div>
          </div>
        )}
      </div>
    </div>
  );
};

// ── ModelPicker ──────────────────────────────────────────────────────────────
// Минималистичный переключатель модели Claude в composer-bar. Текст с маленькой
// стрелкой ▾ → клик открывает popup со списком. Закрывается по клику вне.
// Сохранение выбора управляется родителем (ChatScreen → localStorage).
const ModelPicker = ({ models, value, onChange }) => {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);

  React.useEffect(() => {
    if (!open) return;
    const onDocClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const current = models.find(m => m.key === value) || models[0];
  if (!current) return null;

  return (
    <div className="model-picker" ref={ref}>
      <button
        type="button"
        className="model-picker-btn"
        title="Выбрать модель Claude для следующей задачи"
        onClick={() => setOpen(o => !o)}
      >
        <span className="model-picker-label">{current.label}</span>
        <span className="model-picker-caret">▾</span>
      </button>
      {open && (
        <div className="model-picker-popup" role="menu">
          {models.map((m) => {
            const active = m.key === value;
            // Формат цены: $3/$15 за 1M токенов
            const price = (m.in_per_mtok != null && m.out_per_mtok != null)
              ? `$${m.in_per_mtok}/$${m.out_per_mtok} /Mtok`
              : "";
            return (
              <button
                key={m.key}
                type="button"
                className={`model-picker-item ${active ? "active" : ""}`}
                onClick={() => { onChange(m.key); setOpen(false); }}
                role="menuitemradio"
                aria-checked={active}
              >
                <span className="model-picker-item-label">{m.label}</span>
                {price && <span className="model-picker-item-price">{price}</span>}
                {active && <span className="model-picker-item-check">✓</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

// ── ChatScreen ────────────────────────────────────────────────────────────────

const ChatScreen = ({ config = {} }) => {
  // messages = [{role:'user', text, time} | {role:'agent', time, status, logs, errorMsg, iter:{c,t}}]
  const [messages, setMessages] = useState([]);
  // В local-режиме (single process) tools всегда доступны. Оставлено для совместимости.
  const [desktopOnline, setDesktopOnline] = useState(true);
  // Прикреплённые файлы: [{name, size, content}]. content — это уже декодированный
  // текст (FileReader.readAsText). Передаётся в промпт через getPrompt() в
  // agenter-connect.js: блоки склеиваются перед текстом юзера.
  const [attachments, setAttachments] = useState([]);
  // ask_user: висящий вопрос от агента. null когда вопроса нет.
  //   { taskId, qid, question, options:[], sending:bool, answer:str }
  const [askUser, setAskUser] = useState(null);
  // Модель Claude — выбор юзера для следующей задачи.
  //   models  — список из GET /models: [{key, alias, label, in_per_mtok, out_per_mtok}]
  //   selected — короткий ключ (sonnet-4-6 | opus-4-6 | haiku-4-5)
  // Восстанавливается из localStorage; синхронизируется в window.__selectedModel
  // чтобы agenter-connect.js (vanilla JS) мог его прочитать при отправке.
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState(() => {
    try { return localStorage.getItem("agenter.model") || ""; } catch { return ""; }
  });
  // Сессия Claude SDK для project_id="erp". Когда active=true — над composer
  // показывается бейдж «🔗 Контекст активен (N задач)», кнопка «🆕 Новая»
  // активна. Сбрасывается через AgenterAPI.resetSession() (ADR-018).
  const [session, setSession] = useState({
    active: false,
    tasksCount: 0,
    hasSnapshot: false,
  });
  // Per-task финальное состояние и список фаз. Ключ — task_id.
  // Заполняется через WS task_state_changed / phase_committed + начальный
  // GET /tasks/{id}/phases в момент клика «Откатить».
  //   { [taskId]: { finalState, phasesTotal, phasesCommitted, phases:[...] } }
  const [taskStates, setTaskStates] = useState({});
  // Подтверждение действий (reset session / rollback) — модальный confirm.
  // null = ничего не подтверждаем; { kind:'reset'|'rollback', payload:{...} } = открыт диалог.
  const [confirmAction, setConfirmAction] = useState(null);
  const fileInputRef = useRef(null);
  const bottomRef = useRef(null);
  // project_id фиксированный пока — мультипроектность в backlog.
  const projectId = "erp";

  // Загружаем список моделей один раз при монтировании
  useEffect(() => {
    AgenterAPI.listModels().then(data => {
      setModels(data.models || []);
      // Если в localStorage пусто или невалидно — возьмём дефолт с бэкенда
      const valid = (data.models || []).some(m => m.key === selectedModel);
      if (!valid) {
        setSelectedModel(data.default || "");
      }
    }).catch(err => {
      console.warn("[Agenter] listModels failed:", err);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Синхронизация выбранной модели в localStorage + global для agenter-connect.js
  useEffect(() => {
    if (!selectedModel) return;
    try { localStorage.setItem("agenter.model", selectedModel); } catch {}
    window.__selectedModel = selectedModel;
  }, [selectedModel]);

  // Загрузка текущей сессии при монтировании — чтобы бейдж сразу показал
  // правильное состояние (если юзер закрыл вкладку, а сессия осталась).
  useEffect(() => {
    AgenterAPI.getSession(projectId).then(data => {
      setSession({
        active: !!data.active,
        tasksCount: data.tasks_count || 0,
        hasSnapshot: !!data.has_snapshot,
      });
    }).catch(err => {
      console.warn("[Agenter] getSession failed:", err);
    });
  }, []);

  // Сброс сессии: подтверждение → API call → стейт. После reset'а следующая
  // задача начнётся с чистого контекста (без resume) и создаст новый snapshot.
  const handleResetSession = async () => {
    setConfirmAction(null);
    try {
      await AgenterAPI.resetSession(projectId);
      setSession({ active: false, tasksCount: 0, hasSnapshot: false });
    } catch (err) {
      alert(`Не удалось сбросить сессию: ${err}`);
    }
  };

  // Откат ext_src/ к snapshot'у. БД 1С НЕ откатывается автоматически — это
  // решение юзера (отдельный db_load после rollback). UI это поясняет в
  // confirm-диалоге.
  const handleRollback = async (taskId) => {
    setConfirmAction(null);
    try {
      const r = await AgenterAPI.rollbackTask(taskId);
      alert(`Откат выполнен. Восстановлено файлов: ${r.files_restored || 0}.\n\nБД 1С НЕ откачена — если нужно, запустите задачу «загрузи расширение из ext_src в БД».`);
    } catch (err) {
      alert(`Откат провален: ${err}`);
    }
  };

  // Мост для agenter-connect.js: getPrompt() читает прикрепления отсюда,
  // setupInput() — очищает после отправки. Окно — единственное место, к
  // которому имеет доступ ванильный JS, отсюда window.* ─ остальное живёт
  // в React state.
  useEffect(() => {
    window.__agenterAttachments = {
      get: () => attachments,
      clear: () => setAttachments([]),
    };
  }, [attachments]);

  // Поддерживаемые форматы: текстовые типы, актуальные для 1С + универсальные.
  // PDF/изображения сюда не относятся — для них в backlog отдельная multimodal-кнопка.
  const ATTACH_ACCEPT = ".txt,.md,.bsl,.os,.xml,.json,.csv,.yaml,.yml,.log,.html,.htm,.tsv,.ini,.cfg,.conf,text/*";
  const ATTACH_MAX_BYTES = 2 * 1024 * 1024; // 2 МБ на файл

  const handlePickFiles = () => {
    if (fileInputRef.current) fileInputRef.current.click();
  };

  const handleFilesSelected = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = ""; // чтобы повторный выбор того же файла снова сработал
    if (!files.length) return;
    const newOnes = [];
    for (const f of files) {
      if (f.size > ATTACH_MAX_BYTES) {
        alert(`Файл «${f.name}» слишком большой (${(f.size / 1024).toFixed(0)} КБ). Лимит — ${ATTACH_MAX_BYTES / 1024 / 1024} МБ.`);
        continue;
      }
      try {
        const text = await f.text();
        newOnes.push({ name: f.name, size: f.size, content: text });
      } catch (err) {
        console.error("[Agenter] failed to read file:", f.name, err);
        alert(`Не удалось прочитать файл «${f.name}». Поддерживаются только текстовые форматы (txt, md, bsl, xml, json, csv…).`);
      }
    }
    if (newOnes.length) {
      setAttachments(prev => [...prev, ...newOnes]);
    }
  };

  const handleRemoveAttachment = (idx) => {
    setAttachments(prev => prev.filter((_, i) => i !== idx));
  };

  const handleSubmitAskUser = async () => {
    if (!askUser || askUser.sending) return;
    const answer = (askUser.answer || "").trim();
    if (!answer) return;
    setAskUser(prev => prev ? { ...prev, sending: true } : prev);
    try {
      await AgenterAPI.submitAnswer(askUser.taskId, answer, askUser.qid);
      // Закрытие модалки придёт через WS ask_user_resolved, но для
      // отзывчивости закроем сразу.
      setAskUser(null);
    } catch (err) {
      console.error("[Agenter] submitAnswer failed:", err);
      setAskUser(prev => prev ? { ...prev, sending: false } : prev);
      alert(`Не удалось отправить ответ: ${err}`);
    }
  };

  const projectLabel = config.name || config.extension || "";
  const extLabel     = config.extension || "";

  // Производное состояние — запущена ли сейчас задача
  const isRunning =
    messages.length > 0 &&
    messages[messages.length - 1].role === "agent" &&
    messages[messages.length - 1].status === "running";

  // Прокрутка вниз при новых сообщениях / логах
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Мост React → agenter-connect.js
  useEffect(() => {
    window.__agenterUI = {
      // Начало задачи: добавить сообщение пользователя + пустой ответ агента.
      // attachmentsMeta: опц. массив [{name, size}] — рендерится чипами под
      // текстом юзера. Сам контент файлов в UI не сохраняется (он уже ушёл
      // в LLM как часть полного промпта), храним только meta для отображения.
      startTask: (userText, attachmentsMeta = []) => {
        setMessages(prev => [
          ...prev,
          {
            role: "user",
            text: userText,
            time: nowTs(),
            attachments: Array.isArray(attachmentsMeta) ? attachmentsMeta : [],
          },
          { role: "agent", time: nowTs(), status: "running", logs: [], errorMsg: "" },
        ]);
      },

      // Добавить строку лога в текущее сообщение агента.
      // kind: "step" (по умолч.) — техническая строка для exec-row сетки.
      //       "text" — markdown-блок от LLM, рендерится через marked.
      addLog: (ts, text, meta, kind) => {
        setMessages(prev => {
          const updated = [...prev];
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === "agent") {
              updated[i] = {
                ...updated[i],
                logs: [...updated[i].logs, { ts, text, meta, kind: kind || "step" }],
              };
              break;
            }
          }
          return updated;
        });
      },

      // Задача завершена успешно
      setDone: () => {
        setMessages(prev => {
          const updated = [...prev];
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === "agent") {
              updated[i] = { ...updated[i], status: "done" };
              break;
            }
          }
          return updated;
        });
      },

      // Задача завершена с ошибкой
      setError: (errMsg) => {
        setMessages(prev => {
          const updated = [...prev];
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === "agent") {
              updated[i] = { ...updated[i], status: "error", errorMsg: errMsg };
              break;
            }
          }
          return updated;
        });
      },

      // Прогресс итерации LLM-цикла — N из M
      setIteration: (current, total) => {
        setMessages(prev => {
          const updated = [...prev];
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === "agent") {
              updated[i] = { ...updated[i], iter: { current, total } };
              break;
            }
          }
          return updated;
        });
      },

      setDesktopOnline: (v) => setDesktopOnline(v),

      // ── Sessions / Phases / Snapshots (ADR-018) ──
      onSessionUpdated: (msg) => {
        setSession(prev => ({
          active: true,
          tasksCount: msg.tasks_count || prev.tasksCount + 1,
          hasSnapshot: prev.hasSnapshot,  // обновится через snapshot_created
        }));
      },
      onSessionReset: () => {
        setSession({ active: false, tasksCount: 0, hasSnapshot: false });
      },
      onSnapshotCreated: (msg) => {
        setSession(prev => ({ ...prev, hasSnapshot: true }));
      },
      onSnapshotRestored: (msg) => {
        // Snapshot восстановлен — оставляем активным (юзер может ещё откатить)
      },
      onPhaseCommitted: (msg) => {
        setTaskStates(prev => {
          const cur = prev[msg.task_id] || { phases: [] };
          const existing = (cur.phases || []).filter(p => p.index !== msg.phase_index);
          const phases = [
            ...existing,
            { index: msg.phase_index, title: msg.title, status: "committed" },
          ].sort((a, b) => a.index - b.index);
          return {
            ...prev,
            [msg.task_id]: {
              ...cur,
              phases,
              phasesCommitted: phases.filter(p => p.status === "committed").length,
            },
          };
        });
      },
      onPhaseFailed: (msg) => {
        setTaskStates(prev => {
          const cur = prev[msg.task_id] || { phases: [] };
          const phases = (cur.phases || []).map(p =>
            p.index === msg.phase_index ? { ...p, status: "failed", error: msg.error } : p,
          );
          return { ...prev, [msg.task_id]: { ...cur, phases } };
        });
      },
      onTaskStateChanged: (msg) => {
        // Финал задачи: финальное состояние + перечень фаз. UI рендерит
        // TaskFinalStatus вместо ложного «Готово. Изменения применены».
        setTaskStates(prev => ({
          ...prev,
          [msg.task_id]: {
            finalState:       msg.final_state,
            phases:           msg.phases || [],
            phasesCommitted:  msg.phases_committed || 0,
            phasesTotal:      msg.phases_total || 0,
          },
        }));
        // В messages найдём последнее сообщение агента (которое только что
        // получило статус done/error) и привяжем к нему taskId — для рендера
        // TaskFinalStatus. Это идентификация без явного task_id в state.
        setMessages(prev => {
          const updated = [...prev];
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === "agent" && !updated[i].taskId) {
              updated[i] = { ...updated[i], taskId: msg.task_id };
              break;
            }
          }
          return updated;
        });
      },

      // ── ask_user: показать/скрыть модалку с вопросом от агента ──
      showAskUser: ({ taskId, qid, question, options }) => {
        setAskUser({
          taskId, qid,
          question: question || "",
          options: Array.isArray(options) ? options : [],
          sending: false,
          // Если есть options — предвыбираем первый, чтобы не нужно было целиться
          answer: (options && options.length > 0) ? options[0] : "",
        });
      },
      hideAskUser: (qid) => {
        // Скрываем только если qid совпадает (защита от race: пришёл новый
        // вопрос, потом resolved старого). Если qid не передан — скрываем
        // всё подряд.
        setAskUser(prev => {
          if (!prev) return null;
          if (qid && prev.qid !== qid) return prev;
          return null;
        });
      },
    };
  }, []);

  const today = new Date().toLocaleDateString("ru-RU", {
    day: "2-digit", month: "long", year: "numeric",
  });

  return (
    <div className="workspace" data-screen-label="01 Chat workspace">
      <Sidebar config={config} />
      <main className="main">
        <div className="topbar">
          <div className="crumbs">
            <Icon name="database" size={14} className="ic" style={{ color: "var(--text-3)" }} />
            {projectLabel ? (
              <React.Fragment>
                <strong>{projectLabel}</strong>
                {extLabel && projectLabel !== extLabel && (
                  <React.Fragment>
                    <span className="crumb-sep">/</span>
                    <span>{extLabel}</span>
                  </React.Fragment>
                )}
              </React.Fragment>
            ) : (
              <span style={{ color: "var(--text-3)" }}>Нет выбранной базы</span>
            )}
          </div>
          <div className="topbar-spacer"></div>
          <button className="icon-btn"><Icon name="more" size={14} /></button>
        </div>

        <div className="chat">
          <div className="chat-scroll">
            <div className="chat-inner">
              <div className="session-meta">сессия · {today} · {nowTs()} МСК</div>

              {messages.length === 0 && (
                <div style={{ textAlign: "center", padding: "64px 24px", color: "var(--text-3)", fontSize: 13, lineHeight: 1.7 }}>
                  <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>◈</div>
                  <div>Опишите задачу — агент проанализирует конфигурацию<br/>и внесёт изменения в расширение</div>
                </div>
              )}

              {messages.map((m, i) =>
                m.role === "user"
                  ? <UserMessage key={i} text={m.text} attachments={m.attachments} />
                  : <AgentMessage
                      key={i}
                      msg={m}
                      taskState={m.taskId ? taskStates[m.taskId] : null}
                      canRollback={session.hasSnapshot && !isRunning}
                      onRollback={m.taskId ? () => setConfirmAction({
                        kind: "rollback",
                        taskId: m.taskId,
                      }) : null}
                    />
              )}

              <div ref={bottomRef} />
            </div>
          </div>

          {/* Бейдж текущей сессии над composer'ом (ADR-018) */}
          <SessionBadge
            session={session}
            onReset={() => setConfirmAction({ kind: "reset" })}
            disabled={isRunning}
          />

          <div className="composer-wrap">
            <div className="composer-inner">
              <div className="composer">
                {attachments.length > 0 && (
                  <div className="composer-attachments">
                    {attachments.map((a, i) => (
                      <div key={i} className="attach-chip" title={`${a.name} · ${a.size} байт`}>
                        <Icon name="paperclip" size={11} />
                        <span className="attach-name">{a.name}</span>
                        <span className="attach-size">
                          {a.size < 1024
                            ? `${a.size} Б`
                            : a.size < 1024 * 1024
                              ? `${(a.size / 1024).toFixed(1)} КБ`
                              : `${(a.size / 1024 / 1024).toFixed(2)} МБ`}
                        </span>
                        <button
                          type="button"
                          className="attach-remove"
                          title="Убрать вложение"
                          onClick={() => handleRemoveAttachment(i)}
                        >×</button>
                      </div>
                    ))}
                  </div>
                )}
                <div
                  className="composer-input"
                  contentEditable
                  suppressContentEditableWarning
                  data-placeholder="Опишите задачу или уточнение…"
                />
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={ATTACH_ACCEPT}
                  multiple
                  style={{ display: "none" }}
                  onChange={handleFilesSelected}
                />
                <div className="composer-bar">
                  <div className="composer-tag">
                    <span className="dot" style={{ background: extLabel ? "var(--success)" : "var(--text-4)" }}></span>
                    <span style={{ color: extLabel ? "var(--text)" : "var(--text-3)" }}>
                      {extLabel || "База не выбрана"}
                    </span>
                  </div>
                  {models.length > 0 && (
                    <ModelPicker
                      models={models}
                      value={selectedModel}
                      onChange={setSelectedModel}
                    />
                  )}
                  <button
                    type="button"
                    className="icon-btn"
                    title="Прикрепить файл (.txt, .md, .bsl, .xml, .json, .csv — до 2 МБ)"
                    onClick={handlePickFiles}
                  >
                    <Icon name="paperclip" size={14} />
                  </button>
                  <button className="icon-btn" title="Скриншот"><Icon name="image" size={14} /></button>
                  <button className="icon-btn" title="Код"><Icon name="code" size={14} /></button>
                  <div className="composer-spacer"></div>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--text-4)", marginRight: 8 }}>Ctrl+Enter</span>
                  <button
                    className="send-btn primary"
                    data-action={isRunning ? "stop" : "send"}
                    title={isRunning ? "Прервать выполнение задачи" : "Отправить (Ctrl+Enter)"}
                    aria-label={isRunning ? "Прервать" : "Отправить"}
                    style={{
                      width: 32,
                      height: 32,
                      padding: 0,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      borderRadius: 8,
                      // В работе — приглушённый серый, не агрессивный красный.
                      // Клик по самой кнопке (с tooltip "Прервать") — отменяет задачу.
                      background: isRunning ? "var(--text-2, #475569)" : undefined,
                      borderColor: isRunning ? "var(--text-2, #475569)" : undefined,
                    }}
                  >
                    {isRunning ? (
                      // Мини-спиннер: круг с одним светлым сегментом, крутится бесконечно
                      <span
                        style={{
                          display: "inline-block",
                          width: 14,
                          height: 14,
                          border: "2px solid rgba(255,255,255,0.28)",
                          borderTopColor: "#fff",
                          borderRadius: "50%",
                          animation: "spin 0.8s linear infinite",
                        }}
                      />
                    ) : (
                      <Icon name="send" size={14} />
                    )}
                  </button>
                </div>
              </div>
              <div className="composer-hints">
                <span className="hint-chip">/ команды</span>
                <span className="hint-chip">@объект конфигурации</span>
                <span className="hint-chip">↑ редактировать последний</span>
                <span className="hint-chip">⇧⏎ перенос</span>
              </div>
            </div>
          </div>
        </div>
      </main>

      <RightPanel desktopOnline={desktopOnline} config={config} />

      {askUser && (
        <AskUserDialog
          data={askUser}
          onChangeAnswer={(v) => setAskUser(prev => prev ? { ...prev, answer: v } : prev)}
          onSubmit={handleSubmitAskUser}
        />
      )}

      {confirmAction && confirmAction.kind === "reset" && (
        <ConfirmDialog
          title="Сбросить контекст сессии?"
          message={
            <>
              <p style={{ margin: "0 0 12px" }}>
                Текущая Claude SDK сессия будет завершена. Прошлые задачи
                останутся в истории, но агент <strong>не сможет продолжить</strong>
                их через «продолжай» — каждая следующая задача начнёт диалог
                с нуля.
              </p>
              <p style={{ margin: "0 0 12px" }}>
                Snapshot ext_src/ для отката тоже будет удалён.
              </p>
              <p style={{ margin: 0, color: "var(--text-3)", fontSize: 12 }}>
                Состояние ext_src/ и БД 1С не меняется.
              </p>
            </>
          }
          confirmLabel="Сбросить сессию"
          danger
          onConfirm={handleResetSession}
          onCancel={() => setConfirmAction(null)}
        />
      )}

      {confirmAction && confirmAction.kind === "rollback" && (
        <ConfirmDialog
          title="Откатить ext_src/ к моменту до сессии?"
          message={
            <>
              <p style={{ margin: "0 0 12px" }}>
                Содержимое ext_src/ будет <strong>полностью заменено</strong> на
                snapshot, созданный перед первой задачей текущей сессии. Любые
                изменения в файлах расширения после этой точки будут потеряны.
              </p>
              <p style={{ margin: "0 0 12px", color: "var(--text-2)" }}>
                <strong>База 1С НЕ откатывается.</strong> Если в БД были применены
                фазы (db_load) — они там и останутся. Чтобы синхронизировать БД с
                откаченным ext_src/, после отката напишите задачу «загрузи
                расширение из ext_src в БД».
              </p>
            </>
          }
          confirmLabel="Откатить ext_src/"
          danger
          onConfirm={() => handleRollback(confirmAction.taskId)}
          onCancel={() => setConfirmAction(null)}
        />
      )}
    </div>
  );
};

// ── AskUserDialog ─────────────────────────────────────────────────────────────
// Блокирующий модальный диалог для tool ask_user. Показывается когда агент
// вызвал ask_user и ждёт ответа. Закрывается:
//   1) Юзер ответил → POST /tasks/{id}/answer → ask_user_resolved → hideAskUser
//   2) Юзер нажал «Прервать задачу» в самой модалке → cancelTask → бэк сам
//      разбудит tool с CANCELLED-sentinel
//   3) Бэк прислал ask_user_resolved (timeout/cancel)
const AskUserDialog = ({ data, onChangeAnswer, onSubmit }) => {
  const { question, options, answer, sending } = data;
  const hasOptions = options && options.length > 0;
  const inputRef = React.useRef(null);

  // Авто-фокус на поле/первой опции при появлении
  React.useEffect(() => {
    if (inputRef.current) inputRef.current.focus();
  }, []);

  const handleKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      onSubmit();
    }
  };

  const handleCancelTask = async () => {
    try {
      await AgenterAPI.cancelTask(data.taskId);
    } catch (err) {
      console.error("[Agenter] cancel from ask_user failed:", err);
    }
  };

  const canSubmit = !sending && (answer || "").trim().length > 0;

  return (
    <div
      className="ask-user-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ask-user-title"
    >
      <div className="ask-user-dialog">
        <div className="ask-user-head">
          <div className="ask-user-icon" aria-hidden="true">❓</div>
          <div id="ask-user-title" className="ask-user-title">Агент задал вопрос</div>
        </div>
        <div className="ask-user-question">{question}</div>

        {hasOptions ? (
          <div className="ask-user-options">
            {options.map((opt, i) => (
              <label key={i} className={`ask-user-option ${answer === opt ? "active" : ""}`}>
                <input
                  type="radio"
                  name="ask-user-opt"
                  value={opt}
                  checked={answer === opt}
                  onChange={() => onChangeAnswer(opt)}
                  ref={i === 0 ? inputRef : null}
                />
                <span>{opt}</span>
              </label>
            ))}
          </div>
        ) : (
          <textarea
            ref={inputRef}
            className="ask-user-textarea"
            placeholder="Ответ агенту…"
            value={answer || ""}
            onChange={(e) => onChangeAnswer(e.target.value)}
            onKeyDown={handleKey}
            rows={4}
            disabled={sending}
          />
        )}

        <div className="ask-user-actions">
          <button
            type="button"
            className="ask-user-cancel"
            onClick={handleCancelTask}
            disabled={sending}
            title="Прервать задачу полностью"
          >
            Прервать задачу
          </button>
          <span style={{ flex: 1 }} />
          <span className="ask-user-hint">{hasOptions ? "Enter" : "Ctrl+Enter"}</span>
          <button
            type="button"
            className="ask-user-submit"
            onClick={onSubmit}
            disabled={!canSubmit}
          >
            {sending ? "Отправляю…" : "Ответить"}
          </button>
        </div>
      </div>
    </div>
  );
};

// ── RightPanel ────────────────────────────────────────────────────────────────

// Утилита для форматирования больших чисел: 25509 → "25 509"
function fmtNum(n) {
  if (n === null || n === undefined) return "—";
  try {
    return Number(n).toLocaleString("ru-RU");
  } catch {
    return String(n);
  }
}

// Утилита: МБ → "9.0 ГБ" если > 1024, иначе "934.1 МБ"
function fmtSize(mb) {
  if (mb === null || mb === undefined || isNaN(mb)) return "—";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} ГБ`;
  if (mb >= 10)   return `${Math.round(mb)} МБ`;
  return `${mb.toFixed(1)} МБ`;
}

// ── OpRow — переиспользуемая строка операции в правой панели ─────────────────
// Используется для всех operations (dump-config, dump-extension, reindex и т.д.)
//
// Если у opState есть stats — subtitle подменяется на функцию subtitleWithStats,
// которая формирует строку из реальных счётчиков. Иначе показываем дефолтный
// (статичный) subtitle.
const OpRow = ({
  title, subtitle, subtitleWithStats,
  opName, ops, running, opLog, onRun,
  runLabel, runIcon = "download", disabledHint,
}) => {
  const opState   = ops[opName];
  const isRunning = Boolean(running[opName]);
  const lastLog   = opLog[opName];

  // Динамический subtitle из stats. derived → лёгкая пометка, что цифры
  // взяты автодетекцией, а не от реального запуска операции.
  let effectiveSubtitle = subtitle;
  if (opState && opState.stats && typeof subtitleWithStats === "function") {
    try {
      const fromStats = subtitleWithStats(opState.stats);
      if (fromStats) effectiveSubtitle = fromStats;
    } catch (e) {
      console.error("subtitleWithStats:", e);
    }
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 8, gap: 8 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{
            fontSize: 12, fontWeight: 500, color: "var(--text)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{title}</div>
          {effectiveSubtitle && (
            <div style={{
              fontSize: 11, color: "var(--text-3)", marginTop: 2,
              fontVariantNumeric: "tabular-nums",
            }}>{effectiveSubtitle}</div>
          )}
        </div>
        {opState && (
          <span style={{
            fontSize: 10.5,
            color: opState.ok ? "var(--success)" : "#dc2626",
            fontFamily: "var(--font-mono)",
            whiteSpace: "nowrap",
            flexShrink: 0,
            opacity: opState.derived ? 0.7 : 1,
          }} title={
            `${opState.at}\n` +
            (opState.derived ? "(определено по файлам на диске)\n" : "") +
            (opState.info || opState.error || "")
          }>
            {opState.ok ? "✓" : "✕"} {timeAgo(opState.at)}
            {opState.derived && (
              <span style={{ marginLeft: 4, fontSize: 9, opacity: 0.7 }}>auto</span>
            )}
          </span>
        )}
      </div>

      <button
        onClick={() => onRun(opName)}
        disabled={isRunning || Boolean(disabledHint)}
        title={disabledHint || ""}
        style={{
          width: "100%",
          padding: "8px 12px",
          borderRadius: 8,
          border: "1px solid var(--border)",
          background: isRunning ? "rgba(37,99,235,0.06)" : "#fff",
          color: isRunning ? "var(--accent)" : "var(--text)",
          fontSize: 12, fontWeight: 500,
          cursor: isRunning ? "wait" : (disabledHint ? "not-allowed" : "pointer"),
          opacity: disabledHint ? 0.5 : 1,
          display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
          transition: "all 0.15s ease",
        }}
        onMouseEnter={(e) => {
          if (!isRunning && !disabledHint) {
            e.currentTarget.style.borderColor = "var(--accent)";
            e.currentTarget.style.background = "rgba(37,99,235,0.04)";
          }
        }}
        onMouseLeave={(e) => {
          if (!isRunning) {
            e.currentTarget.style.borderColor = "var(--border)";
            e.currentTarget.style.background = "#fff";
          }
        }}
      >
        {isRunning ? (
          <span style={{
            width: 11, height: 11, borderRadius: "50%",
            border: "2px solid rgba(37,99,235,0.25)",
            borderTopColor: "var(--accent)",
            animation: "rotate360 0.7s linear infinite",
          }}></span>
        ) : (
          <Icon name={runIcon} size={12} />
        )}
        <span>{isRunning ? "Выполняется…" : runLabel}</span>
      </button>

      {lastLog && (
        <div
          className="op-log-box"
          style={{
            marginTop: 8,
            padding: "8px 10px",
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: lastLog.startsWith("Ошибка") ? "#dc2626" : "var(--text-3)",
            background: lastLog.startsWith("Ошибка") ? "rgba(220,38,38,0.05)" : "rgba(15,27,42,0.03)",
            border: lastLog.startsWith("Ошибка") ? "1px solid rgba(220,38,38,0.2)" : "1px solid transparent",
            borderRadius: 6,
            wordBreak: "break-word",
            lineHeight: 1.5,
          }}
        >
          {lastLog}
        </div>
      )}
    </div>
  );
};

// Утилита для отображения "2 мин назад"
function timeAgo(iso) {
  if (!iso) return "никогда";
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 0) return "только что";
    if (ms < 60_000) return "только что";
    if (ms < 3_600_000) return `${Math.floor(ms / 60_000)} мин назад`;
    if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)} ч назад`;
    return `${Math.floor(ms / 86_400_000)} д назад`;
  } catch {
    return "—";
  }
}

const RightPanel = ({ desktopOnline = true, config = {} }) => {
  const changes = [];

  // ── Operations state ─────────────────────────────────────────────────────
  const [ops, setOps]          = useState({});       // { "dump-extension": {at, ok, info, ...} }
  const [running, setRunning]  = useState({});       // { "dump-extension": bool }
  const [opLog, setOpLog]      = useState({});       // { "dump-extension": "последняя строка лога" }

  // Загружаем начальное состояние из backend
  useEffect(() => {
    AgenterAPI.getOpsState().then(setOps).catch(() => {});
  }, []);

  // Мост для agenter-connect.js (он шлёт op_started/op_log/op_done/op_error)
  useEffect(() => {
    window.__opsUI = {
      opStarted: (op /*, at*/) => {
        setRunning(r => ({ ...r, [op]: true }));
        setOpLog(l => ({ ...l, [op]: "Запуск…" }));
      },
      opLog: (op, _ts, text, meta) => {
        setOpLog(l => ({ ...l, [op]: text + (meta ? ` · ${meta}` : "") }));
      },
      opDone: (op, info /*, duration_sec*/) => {
        setRunning(r => ({ ...r, [op]: false }));
        setOpLog(l => ({ ...l, [op]: `Готово · ${info || "OK"}` }));
        AgenterAPI.getOpsState().then(setOps).catch(() => {});
      },
      opError: (op, error) => {
        setRunning(r => ({ ...r, [op]: false }));
        // НЕ обрезаем — пусть юзер видит полный текст ошибки 1С
        // и может его выделить и скопировать.
        const fullText = String(error || "Неизвестная ошибка");
        setOpLog(l => ({ ...l, [op]: `Ошибка: ${fullText}` }));
        AgenterAPI.getOpsState().then(setOps).catch(() => {});
      },
    };
  }, []);

  const handleRunOp = async (opName) => {
    if (running[opName]) return;
    try {
      await AgenterAPI.runOperation(opName);
    } catch (e) {
      console.error("op failed", e);
      setRunning(r => ({ ...r, [opName]: false }));
      setOpLog(l => ({ ...l, [opName]: `Ошибка: ${String(e)}` }));
    }
  };

  return (
    <aside className="rightbar">
      <div className="rb-section">
        <div className="rb-head">
          <div className="rb-title">Локальный агент</div>
          <span className="rb-action">Настройки</span>
        </div>
        <div className="assistant-card">
          <div className="assistant-row">
            <div className="host-icon"><Icon name="terminal" size={14} className="ic" /></div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="assistant-name">
                <span style={{
                  width: 7, height: 7, borderRadius: "50%",
                  background: "var(--success)",
                  boxShadow: "0 0 0 3px rgba(16,185,129,0.18)",
                }}></span>
                Готов к работе
              </div>
              <div className="assistant-meta">
                Tools выполняются локально · BSL Atlas + 1С
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Состояние базы — operations bar ─────────────────────────────── */}
      <div className="rb-section">
        <div className="rb-head">
          <div className="rb-title">Состояние базы</div>
        </div>
        <div className="assistant-card" style={{ padding: "14px 14px 4px" }}>
          <OpRow
            title="Конфигурация (SCHEME)"
            subtitle="Основная конфигурация 1С"
            subtitleWithStats={(s) => {
              const parts = [];
              if (s.xml_count)    parts.push(`${fmtNum(s.xml_count)} XML`);
              if (s.object_types) parts.push(`${s.object_types} типов`);
              if (s.size_mb)      parts.push(fmtSize(s.size_mb));
              return parts.length ? parts.join(" · ") : null;
            }}
            opName="dump-config"
            ops={ops} running={running} opLog={opLog}
            onRun={handleRunOp}
            runLabel="Выгрузить конфигурацию"
            disabledHint={!config.scheme_path ? "Сначала укажи scheme_path в Настройках" : null}
          />

          <div style={{
            height: 1, background: "var(--border)",
            margin: "4px -14px 14px", opacity: 0.6,
          }} />

          <OpRow
            title="Индекс BSL Atlas"
            subtitle="Структурный поиск по конфигурации"
            subtitleWithStats={(s) => {
              const parts = [];
              if (s.objects_count) parts.push(`${fmtNum(s.objects_count)} объектов`);
              if (s.symbols_count) parts.push(`${fmtNum(s.symbols_count)} символов`);
              if (s.db_size_mb)    parts.push(`БД ${fmtSize(s.db_size_mb)}`);
              return parts.length ? parts.join(" · ") : null;
            }}
            opName="reindex"
            ops={ops} running={running} opLog={opLog}
            onRun={handleRunOp}
            runLabel="Переиндексировать"
            runIcon="refresh"
            disabledHint={!config.bsl_atlas_url ? "URL BSL Atlas не задан" : null}
          />

          <div style={{
            height: 1, background: "var(--border)",
            margin: "4px -14px 14px", opacity: 0.6,
          }} />

          <OpRow
            title={config.extension ? `Расширение «${config.extension}»` : "Расширение"}
            subtitle="Текущее рабочее расширение"
            subtitleWithStats={(s) => {
              const parts = [];
              if (s.xml_count)    parts.push(`${fmtNum(s.xml_count)} XML`);
              if (s.files_count && s.files_count !== s.xml_count) {
                parts.push(`${fmtNum(s.files_count)} файлов`);
              }
              if (s.size_mb)      parts.push(fmtSize(s.size_mb));
              return parts.length ? parts.join(" · ") : null;
            }}
            opName="dump-extension"
            ops={ops} running={running} opLog={opLog}
            onRun={handleRunOp}
            runLabel="Выгрузить расширение"
            disabledHint={!config.extension ? "Не задано имя расширения" : null}
          />

          <div style={{
            height: 1, background: "var(--border)",
            margin: "4px -14px 14px", opacity: 0.6,
          }} />

          <OpRow
            title="Документация платформы 1С (точно)"
            subtitle="Индекс shcntx_ru.hbk → SQLite + FTS5"
            subtitleWithStats={(s) => {
              const parts = [];
              if (s.records_count) parts.push(`${fmtNum(s.records_count)} записей`);
              if (s.db_size_mb)    parts.push(`БД ${fmtSize(s.db_size_mb)}`);
              return parts.length ? parts.join(" · ") : null;
            }}
            opName="rebuild-platform-docs"
            ops={ops} running={running} opLog={opLog}
            onRun={handleRunOp}
            runLabel="Обновить документацию"
            runIcon="refresh"
            disabledHint={!config.v8_path ? "Не задан путь к платформе 1С" : null}
          />

          <div style={{
            height: 1, background: "var(--border)",
            margin: "4px -14px 14px", opacity: 0.6,
          }} />

          <OpRow
            title="Семантический поиск платформы"
            subtitle="ChromaDB + USER-bge-m3 (поиск по смыслу)"
            subtitleWithStats={(s) => {
              const parts = [];
              if (s.indexed)        parts.push(`${fmtNum(s.indexed)} векторов`);
              if (s.chroma_size_mb) parts.push(`${fmtSize(s.chroma_size_mb)}`);
              return parts.length ? parts.join(" · ") : null;
            }}
            opName="rebuild-platform-docs-semantic"
            ops={ops} running={running} opLog={opLog}
            onRun={handleRunOp}
            runLabel="Построить семантический индекс"
            runIcon="refresh"
            disabledHint={!ops["rebuild-platform-docs"]?.ok
              ? "Сначала построй SQLite-индекс (точный)"
              : null}
          />
        </div>
      </div>

      <div className="rb-section">
        <div className="rb-head">
          <div className="rb-title">Последние изменения</div>
          <span className="rb-action">Журнал</span>
        </div>
        <div className="changes-list">
          {changes.length === 0 ? (
            <div style={{ padding: "12px 8px", fontSize: 12, color: "var(--text-4)", textAlign: "center", lineHeight: 1.6 }}>
              Нет изменений
            </div>
          ) : changes.map((c, i) => (
            <div key={i} className="change-row">
              <span className={`change-tag ${c.tagClass}`}>{c.tag}</span>
              <span className="change-text">{c.text}</span>
              <span className="change-time">{c.time}</span>
            </div>
          ))}
        </div>
      </div>

    </aside>
  );
};

window.ChatScreen = ChatScreen;
