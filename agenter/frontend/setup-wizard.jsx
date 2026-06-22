/* Setup Wizard + AppRouter.
 *
 * AppRouter — корень приложения. При старте читает config:
 *   - если ключевые поля пусты или невалидны → SetupWizard (без возможности закрыть)
 *   - иначе → ChatScreen (с возможностью открыть мастер по кнопке Настройки)
 *
 * SetupWizard — форма с inline-проверкой каждого поля.
 * Сохраняет в agenter/config/config.json через POST /config.
 */

const REQUIRED_FIELDS = ["v8_path", "base_path", "ext_src_path", "extension"];

// ── Утилиты ────────────────────────────────────────────────────────────────

function isConfigComplete(cfg) {
  if (!cfg) return false;
  return REQUIRED_FIELDS.every(k => (cfg[k] || "").trim().length > 0);
}

// ── Иконки статуса ─────────────────────────────────────────────────────────

const StatusBadge = ({ check }) => {
  if (!check) {
    return (
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        fontSize: 11, color: "var(--text-4)",
        fontFamily: "var(--font-mono)",
      }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#cbd5e1" }} />
        ожидание
      </span>
    );
  }
  const color = check.ok ? "var(--success)" : "#dc2626";
  const bg    = check.ok ? "rgba(16,185,129,0.08)" : "rgba(220,38,38,0.06)";
  const icon  = check.ok ? "check" : "x";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "3px 9px",
      borderRadius: 12,
      fontSize: 11.5,
      background: bg,
      color: color,
      fontFamily: "var(--font-mono)",
      maxWidth: "100%",
    }}>
      <Icon name={icon} size={11} />
      <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {check.message}
      </span>
    </span>
  );
};

// ── Одно поле формы ────────────────────────────────────────────────────────

const Field = ({ label, hint, value, onChange, type = "text", placeholder = "", check, mono = true, required = false }) => (
  <div className="field">
    <label className="field-label" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
      <span>
        {label}
        {required && <span style={{ color: "#dc2626", marginLeft: 4 }}>*</span>}
      </span>
      <StatusBadge check={check} />
    </label>
    <input
      className={`field-input ${mono ? "mono" : ""}`}
      type={type}
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      autoComplete="off"
    />
    {hint && <div className="field-help">{hint}</div>}
  </div>
);

// ── SetupWizard ────────────────────────────────────────────────────────────

const SetupWizard = ({ initialConfig, onSave, onClose, canClose }) => {
  const [cfg, setCfg] = React.useState({
    name: "",
    extension: "",
    v8_path: "",
    base_path: "",
    username: "Администратор",
    password: "",
    ext_src_path: "",
    scheme_path: "",
    bsl_atlas_url: "http://localhost:8000",
    ...(initialConfig || {}),
  });
  const [checks, setChecks] = React.useState({});
  const [allOk, setAllOk] = React.useState(false);
  const [checking, setChecking] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [savingStage, setSavingStage] = React.useState("");  // "saving" | "auth" | ""
  const [authCheck, setAuthCheck] = React.useState(null);    // {ok, message, raw} | null
  const [passwordTouched, setPasswordTouched] = React.useState(false);

  const update = (k) => (v) => setCfg(prev => ({ ...prev, [k]: v }));

  // При монтировании — сразу запускаем проверку
  React.useEffect(() => {
    runCheck();
  }, []);

  const runCheck = async () => {
    setChecking(true);
    try {
      const data = await AgenterAPI.checkConfig();
      setChecks(data.checks || {});
      setAllOk(Boolean(data.all_required_ok));
    } catch (e) {
      console.error("check failed", e);
    } finally {
      setChecking(false);
    }
  };

  const handleSaveAndCheck = async () => {
    setSaving(true);
    setSavingStage("saving");
    setAuthCheck(null);
    try {
      // password: если пользователь не трогал поле — не отправляем (null = "не менять")
      const payload = { ...cfg };
      if (!passwordTouched) {
        payload.password = null;
      }

      // POST /config — на бэке: запись + автоматическая проверка авторизации в 1С (10-30 сек)
      setSavingStage("auth");
      const saveResp = await AgenterAPI.saveConfig(payload);
      const auth = saveResp.auth_check;  // null если не делалась, иначе {ok, message, raw?}
      setAuthCheck(auth);

      // Параллельно — обновляем чеки путей
      setSavingStage("");
      const data = await AgenterAPI.checkConfig();
      setChecks(data.checks || {});
      setAllOk(Boolean(data.all_required_ok));

      // Авто-продолжение в чат: пути ok И auth прошёл (или не было — например bsl_atlas без 1с)
      const authOk = auth === null || auth.ok === true;
      if (data.all_required_ok && authOk && onSave) {
        const fresh = await AgenterAPI.getConfig();
        onSave(fresh);
      }
    } catch (e) {
      console.error("save failed", e);
      setAuthCheck({ ok: false, message: "Не удалось сохранить: " + String(e) });
    } finally {
      setSaving(false);
      setSavingStage("");
    }
  };

  return (
    <div className="connect" data-screen-label="00 Setup">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"></div>
          <div className="brand-name">Agenter</div>
          <div className="brand-version">v0.9.4</div>
        </div>
        <div className="side-section">
          <div className="side-section-header">
            <div className="side-label">Настройка</div>
          </div>
          <div style={{ padding: "16px 12px", fontSize: 12, color: "var(--text-3)", lineHeight: 1.6 }}>
            {canClose
              ? "Изменения путей и параметров текущего проекта"
              : "Чтобы начать работать, укажите пути к платформе 1С, базе и расширению."}
          </div>
        </div>
        <div className="divider"></div>
        <div className="side-section" style={{ flex: 1 }}>
          <div className="side-section-header">
            <div className="side-label">Подсказки</div>
          </div>
          <div className="history-list">
            {[
              "v8_path — папка bin платформы 1С",
              "base_path — папка файловой базы или Srvr=...",
              "ext_src — куда выгружать XML расширения",
              "SCHEME — куда выгружать XML конфигурации",
              "BSL Atlas — индекс на http://localhost:8000",
            ].map((t, i) => (
              <div key={i} className="history-item">
                <div className="history-text" style={{ fontSize: 11.5, fontFamily: "var(--font-mono)" }}>{t}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="sidebar-footer">
          <div className="avatar">—</div>
          <div className="user-meta">
            <div className="user-name">Пользователь</div>
            <div className="user-org">Local mode</div>
          </div>
        </div>
      </aside>

      <main className="connect-main">
        <div className="connect-eyebrow">
          {canClose ? "Настройки" : "Подключение базы · первый запуск"}
        </div>
        <h1 className="connect-title">
          {canClose ? "Параметры подключения к 1С" : "Подключите вашу базу 1С"}
        </h1>
        <p className="connect-sub">
          Agenter работает локально: выгружает конфигурацию и расширение в XML,
          анализирует через BSL Atlas, применяет изменения только после подтверждения.
          Конфигурация и пароли остаются на этой машине.
          <br />
          В облако уходят только промпты к LLM.
        </p>

        <div className="connect-card" style={{ marginTop: 24 }}>
          <h3 style={{ marginBottom: 4 }}>Пути и параметры</h3>
          <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 18 }}>
            Поля со звёздочкой обязательны. Статусы обновляются после нажатия «Проверить и сохранить».
          </div>

          <Field
            label="Название проекта"
            hint="Только для отображения внутри Agenter"
            value={cfg.name}
            onChange={update("name")}
            placeholder="Например: ERP компании"
            mono={false}
          />

          <Field
            label="Путь к платформе 1С (папка bin)"
            hint="Папка содержащая 1cv8.exe"
            value={cfg.v8_path}
            onChange={update("v8_path")}
            placeholder="C:\Program Files\1cv8\8.3.X.XXXX\bin"
            check={checks.v8_path}
            required
          />

          <Field
            label="Путь к информационной базе"
            hint='Папка файловой базы или строка Srvr="..."'
            value={cfg.base_path}
            onChange={update("base_path")}
            placeholder="C:\Users\User\Documents\МояБаза"
            check={checks.base_path}
            required
          />

          <div className="field-row split">
            <Field
              label="Логин 1С"
              value={cfg.username}
              onChange={update("username")}
              placeholder="Администратор"
              mono={false}
            />
            <Field
              label="Пароль 1С"
              type="password"
              value={passwordTouched
                ? (cfg.password || "")
                : (initialConfig?.password_set ? "••••••••••" : "")}
              onChange={(v) => { setPasswordTouched(true); update("password")(v); }}
              placeholder="(пусто если без пароля)"
              mono={false}
            />
          </div>

          <Field
            label="Имя расширения"
            hint="Как оно называется в Конфигураторе 1С"
            value={cfg.extension}
            onChange={update("extension")}
            placeholder="МоеРасширение"
            check={checks.extension}
            required
          />

          <Field
            label="Папка ext_src (выгрузка расширения в XML)"
            hint="Сюда агент будет выгружать и редактировать XML расширения"
            value={cfg.ext_src_path}
            onChange={update("ext_src_path")}
            placeholder="D:\CURSORIC\agenter\ext_src"
            check={checks.ext_src_path}
            required
          />

          <Field
            label="Папка SCHEME (выгрузка конфигурации в XML)"
            hint="Опционально. Нужна если планируете брать образцы объектов из основной конфы"
            value={cfg.scheme_path}
            onChange={update("scheme_path")}
            placeholder="D:\CURSORIC\agenter\SCHEME"
            check={checks.scheme_path}
          />

          <Field
            label="URL BSL Atlas"
            hint="Индексатор кода 1С. Запускается отдельно через start.bat"
            value={cfg.bsl_atlas_url}
            onChange={update("bsl_atlas_url")}
            placeholder="http://localhost:8000"
            check={checks.bsl_atlas_url}
          />

          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 22, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
            <span style={{ fontSize: 11, color: "var(--text-3)" }}>
              <Icon name="lock" size={10} /> Сохраняется локально в agenter/config/config.json
            </span>
            <div style={{ flex: 1 }}></div>
            {canClose && (
              <button className="btn ghost" onClick={onClose}>Закрыть без изменений</button>
            )}
            <button
              className="btn primary"
              onClick={handleSaveAndCheck}
              disabled={saving || checking}
              style={{ opacity: (saving || checking) ? 0.6 : 1 }}
            >
              {savingStage === "auth"
                ? "Проверяю авторизацию в 1С…"
                : saving
                ? "Сохраняю…"
                : checking
                ? "Проверяю пути…"
                : "Проверить и сохранить"}
              {!saving && !checking && <Icon name="chevron-right" size={12} className="ic-sm" />}
            </button>
          </div>

          {/* Прогресс долгой проверки в 1С */}
          {savingStage === "auth" && (
            <div style={{
              marginTop: 14, padding: "10px 14px",
              background: "rgba(37,99,235,0.05)",
              border: "1px solid rgba(37,99,235,0.2)",
              borderRadius: 8,
              fontSize: 12, color: "var(--accent)",
              display: "flex", alignItems: "center", gap: 10,
            }}>
              <span style={{
                width: 12, height: 12, borderRadius: "50%",
                border: "2px solid rgba(37,99,235,0.25)",
                borderTopColor: "var(--accent)",
                animation: "rotate360 0.7s linear infinite",
                flexShrink: 0,
              }}></span>
              <span>
                Запускаю 1С и проверяю что логин/пароль работают. Это занимает 10–30 секунд (зависит от размера базы).
              </span>
            </div>
          )}

          {/* Результат auth-проверки */}
          {authCheck && !saving && (
            <div style={{
              marginTop: 14, padding: "10px 14px",
              background: authCheck.ok ? "rgba(16,185,129,0.06)" : "rgba(220,38,38,0.05)",
              border: authCheck.ok ? "1px solid rgba(16,185,129,0.3)" : "1px solid rgba(220,38,38,0.2)",
              borderRadius: 8,
              fontSize: 12,
              color: authCheck.ok ? "#047857" : "#991b1b",
              userSelect: "text",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: authCheck.ok ? 0 : 8 }}>
                <Icon name={authCheck.ok ? "check" : "x"} size={13} />
                <strong style={{ fontFamily: "var(--font-display)" }}>
                  {authCheck.ok ? "Авторизация в 1С — OK" : "Не удалось войти в 1С"}
                </strong>
              </div>
              {!authCheck.ok && (
                <div className="op-log-box" style={{
                  marginTop: 4,
                  fontSize: 12,
                  fontFamily: "var(--font-sans)",
                  color: "#7f1d1d",
                  background: "transparent",
                  padding: 0,
                  lineHeight: 1.6,
                  whiteSpace: "pre-wrap",
                }}>
                  {authCheck.message}
                </div>
              )}
              {!authCheck.ok && authCheck.raw && (
                <details style={{ marginTop: 8, fontSize: 11 }}>
                  <summary style={{ cursor: "pointer", color: "#991b1b", userSelect: "none" }}>
                    Технические подробности (PowerShell stderr)
                  </summary>
                  <div className="op-log-box" style={{
                    marginTop: 6,
                    padding: "8px 10px",
                    background: "rgba(220,38,38,0.04)",
                    border: "1px solid rgba(220,38,38,0.15)",
                    borderRadius: 6,
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    color: "#7f1d1d",
                    whiteSpace: "pre-wrap",
                  }}>
                    {authCheck.raw}
                  </div>
                </details>
              )}
            </div>
          )}

          {!allOk && Object.keys(checks).length > 0 && (
            <div style={{
              marginTop: 14, padding: "10px 14px",
              background: "rgba(220,38,38,0.05)",
              border: "1px solid rgba(220,38,38,0.2)",
              borderRadius: 8,
              fontSize: 12, color: "#991b1b",
              userSelect: "text",
            }}>
              Не все обязательные поля проверены успешно. Исправь красные пункты и нажми «Проверить и сохранить» ещё раз.
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

// ── AppRouter ──────────────────────────────────────────────────────────────

const AppRouter = () => {
  const [screen, setScreen] = React.useState("loading");
  const [config, setConfig] = React.useState({});

  // Загружаем конфиг при монтировании, решаем что показать
  React.useEffect(() => {
    AgenterAPI.getConfig()
      .then((cfg) => {
        setConfig(cfg);
        setScreen(isConfigComplete(cfg) ? "chat" : "wizard");
      })
      .catch((err) => {
        console.error("Не удалось загрузить config:", err);
        setScreen("wizard");
      });

    // Глобальный хук для кнопки «Настройки» из ChatScreen
    window.__openSetup = () => setScreen("wizard");
  }, []);

  const handleWizardSave = (newCfg) => {
    setConfig(newCfg);
    setScreen("chat");
  };

  const handleWizardClose = () => {
    if (isConfigComplete(config)) setScreen("chat");
  };

  if (screen === "loading") {
    return (
      <div style={{
        display: "grid", placeItems: "center", height: "100vh",
        fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-3)",
      }}>
        Загрузка конфигурации…
      </div>
    );
  }

  if (screen === "wizard") {
    return (
      <SetupWizard
        initialConfig={config}
        onSave={handleWizardSave}
        onClose={handleWizardClose}
        canClose={isConfigComplete(config)}
      />
    );
  }

  return <ChatScreen config={config} />;
};

window.AppRouter = AppRouter;
window.SetupWizard = SetupWizard;
