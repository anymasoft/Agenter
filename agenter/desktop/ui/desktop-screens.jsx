/* Desktop assistant components */

const { useState, useEffect } = React;

const Mark = ({ size = 14 }) => (
  <span className="mark" style={{ width: size, height: size }}></span>
);

const Icon = ({ name, size = 14 }) => {
  const props = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round" };
  switch (name) {
    case "minus": return <svg {...props}><path d="M5 12h14"/></svg>;
    case "square": return <svg {...props}><rect x="4" y="4" width="16" height="16" rx="1.5"/></svg>;
    case "x": return <svg {...props}><path d="M18 6 6 18M6 6l12 12"/></svg>;
    case "check": return <svg {...props}><path d="M20 6 9 17l-5-5"/></svg>;
    case "eye": return <svg {...props}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>;
    case "folder": return <svg {...props}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>;
    case "refresh": return <svg {...props}><path d="M3 12a9 9 0 0 1 15.5-6.3L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.3L3 16"/><path d="M3 21v-5h5"/></svg>;
    case "settings": return <svg {...props}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>;
    case "open": return <svg {...props}><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6M10 14 21 3"/></svg>;
    case "shield": return <svg {...props}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>;
    case "zap": return <svg {...props}><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z"/></svg>;
    case "chevron-down": return <svg {...props}><path d="m6 9 6 6 6-6"/></svg>;
    case "chevron-right": return <svg {...props}><path d="m9 6 6 6-6 6"/></svg>;
    case "log-out": return <svg {...props}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>;
    case "search": return <svg {...props}><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>;
    case "lock": return <svg {...props}><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>;
    case "terminal": return <svg {...props}><path d="m4 17 6-6-6-6M12 19h8"/></svg>;
    case "play": return <svg {...props}><path d="M5 3v18l15-9z" fill="currentColor"/></svg>;
    case "pause": return <svg {...props}><rect x="6" y="4" width="4" height="16" fill="currentColor"/><rect x="14" y="4" width="4" height="16" fill="currentColor"/></svg>;
    case "user": return <svg {...props}><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>;
    case "info": return <svg {...props}><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>;
    case "external": return <svg {...props}><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6M10 14 21 3"/></svg>;
    case "wifi": return <svg {...props}><path d="M5 12.55a11 11 0 0 1 14 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01"/></svg>;
    case "volume": return <svg {...props}><path d="M11 5 6 9H2v6h4l5 4V5zM15.54 8.46a5 5 0 0 1 0 7.07"/></svg>;
    case "battery": return <svg {...props}><rect x="2" y="7" width="18" height="10" rx="1.5"/><path d="M22 11v2"/></svg>;
    default: return null;
  }
};

/* TitleBar with real click handlers */
const TitleBar = ({ title, withMin = true, withMax = true }) => {
  const handleMouseDown = (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('.win-ctrl')) return;
    e.preventDefault();
    const startX = e.screenX;
    const startY = e.screenY;
    const winX = window.screenX;
    const winY = window.screenY;
    const onMove = (me) => {
      window.pywebview?.api?.move_window(
        winX + me.screenX - startX,
        winY + me.screenY - startY
      );
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  };

  return (
    <div className="win-titlebar header" onMouseDown={handleMouseDown}>
      <div className="win-title">
        <span className="mark"></span>
        {title}
      </div>
      <div className="win-controls">
        {withMin && (
          <div className="win-ctrl" onClick={() => window.pywebview?.api?.minimize_window()}>
            <Icon name="minus" size={11}/>
          </div>
        )}
        {withMax && (
          <div className="win-ctrl">
            <Icon name="square" size={9}/>
          </div>
        )}
        <div className="win-ctrl close" onClick={() => window.pywebview?.api?.hide_window()}>
          <Icon name="x" size={11}/>
        </div>
      </div>
    </div>
  );
};

const WizardSide = ({ stepIndex }) => {
  const steps = [
    { name: "Приветствие", desc: "О чём этот мастер" },
    { name: "Параметры базы", desc: "Путь, логин, версия" },
    { name: "Индексация", desc: "5–12 минут локально" },
    { name: "Готово", desc: "Передача в веб" },
  ];
  return (
    <aside className="wizard-side">
      <div className="wizard-brand">
        <div className="mark"></div>
        <div>
          <div className="name">Agenter Desktop</div>
          <div className="sub">v1.0.0</div>
        </div>
      </div>
      <div>
        {steps.map((s, i) => {
          const cls = i < stepIndex ? "done" : i === stepIndex ? "active" : "";
          return (
            <div key={i} className={`wstep ${cls}`}>
              <div className="wstep-bullet">{i < stepIndex ? <Icon name="check" size={11}/> : i + 1}</div>
              <div className="wstep-meta">
                <div className="wstep-name">{s.name}</div>
                <div className="wstep-desc">{s.desc}</div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="wizard-side-foot">
        контур · локально<br/>
        ↳ конфигурация не покидает машину
      </div>
    </aside>
  );
};

/* Step 1 — Welcome */
const Step1Welcome = ({ onNext = ()=>{}, onSkip = ()=>{} }) => (
  <div className="win wizard">
    <TitleBar title="Agenter Desktop · Подключение базы 1С" />
    <div className="wizard-body">
      <WizardSide stepIndex={0} />
      <main className="wizard-main">
        <div className="wizard-eyebrow">Шаг 1 из 4 · Приветствие</div>
        <div className="welcome-hero">
          <div className="welcome-illu"></div>
          <h1 className="wizard-title" style={{ fontSize: 30 }}>Подключение базы 1С к Agenter</h1>
          <p className="wizard-sub">
            Настройка займёт 5–12 минут. После этого вы сможете ставить задачи через веб-кабинет, а ассистент будет выполнять их в фоне на этой машине — без отправки исходного кода в облако.
          </p>
          <div className="welcome-features">
            <div className="welcome-feat">
              <div className="welcome-feat-ic"><Icon name="shield" size={13}/></div>
              <div className="welcome-feat-title">Локальный контур</div>
              <div className="welcome-feat-desc">XML и BSL остаются на вашей машине</div>
            </div>
            <div className="welcome-feat">
              <div className="welcome-feat-ic"><Icon name="zap" size={13}/></div>
              <div className="welcome-feat-title">Один раз настроить</div>
              <div className="welcome-feat-desc">Дальше работа идёт в трее</div>
            </div>
            <div className="welcome-feat">
              <div className="welcome-feat-ic"><Icon name="terminal" size={13}/></div>
              <div className="welcome-feat-title">8.3.20 и выше</div>
              <div className="welcome-feat-desc">Серверные и файловые базы</div>
            </div>
          </div>
        </div>
      </main>
    </div>
    <div className="wizard-foot">
      <span className="meta">подключений · 0 · агент готов к настройке</span>
      <div className="spacer"></div>
      <button className="dsk-btn ghost" onClick={onSkip}>Пропустить</button>
      <button className="dsk-btn primary lg" onClick={onNext}>Начать настройку <Icon name="chevron-right" size={11}/></button>
    </div>
  </div>
);

/* Step 2 — Params (stateful form with real validation) */
const Step2Params = ({ onNext = ()=>{}, onBack = ()=>{} }) => {
  const [form, setForm] = useState({
    name:           "",
    base_path:      "",
    username:       "",
    password:       "",
    v8_path:        "",
    extension:      "",
    ext_src_path:   "",
    scheme_path:    "",
    backend_ws_url: "ws://localhost:8080/ws/desktop",
    bsl_atlas_url:  "http://localhost:8000",
  });
  const [validation, setValidation] = useState(null);
  const [checking, setChecking]     = useState(false);
  const [showPwd, setShowPwd]       = useState(false);

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const browse = async (field) => {
    try {
      const result = await window.pywebview.api.browse_folder();
      if (result) setForm(f => ({ ...f, [field]: result }));
    } catch (_) {}
  };

  const check = async () => {
    setChecking(true);
    setValidation(null);
    try {
      const res = await window.pywebview.api.validate_config(form);
      setValidation(res);
    } catch (e) {
      setValidation({ ok: false, errors: [String(e)] });
    } finally {
      setChecking(false);
    }
  };

  const browseBtn = (field) => (
    <button
      className="dsk-btn"
      style={{ padding: "0 10px", height: 36, flexShrink: 0 }}
      onClick={() => browse(field)}
      title="Выбрать папку"
    >
      <Icon name="folder" size={13}/>
    </button>
  );

  return (
    <div className="win wizard">
      <TitleBar title="Agenter Desktop · Подключение базы 1С" />
      <div className="wizard-body">
        <WizardSide stepIndex={1} />
        <main className="wizard-main">
          <div className="wizard-eyebrow">Шаг 2 из 4 · Параметры базы</div>
          <h1 className="wizard-title">Подключение к информационной базе</h1>
          <p className="wizard-sub">Учётные данные остаются на этой машине и не передаются на серверы Agenter.</p>

          <div className="field">
            <label className="field-label">Путь к информационной базе</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                className="field-input mono"
                placeholder='C:\Users\...\База или Srvr="host:1541";Ref="base";'
                value={form.base_path}
                onChange={set("base_path")}
              />
              {browseBtn("base_path")}
            </div>
            <div className="field-help">Файловая база (папка с .1CD) или строка подключения к серверу 1С</div>
          </div>

          <div className="field-row split">
            <div className="field" style={{ marginBottom: 0 }}>
              <label className="field-label">Логин 1С</label>
              <input className="field-input" placeholder="Имя пользователя" value={form.username} onChange={set("username")} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label className="field-label">Пароль</label>
              <div style={{ position: "relative" }}>
                <input
                  className="field-input"
                  type={showPwd ? "text" : "password"}
                  value={form.password}
                  onChange={set("password")}
                />
                <span
                  style={{ position: "absolute", right: 10, top: 10, color: "var(--text-3)", cursor: "pointer" }}
                  onClick={() => setShowPwd(v => !v)}
                >
                  <Icon name="eye" size={14}/>
                </span>
              </div>
            </div>
          </div>

          <div className="field" style={{ marginTop: 18 }}>
            <label className="field-label">Путь к платформе 1С</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                className="field-input mono"
                placeholder="C:\Program Files\1cv8\8.3.xx.xxxx\bin"
                value={form.v8_path}
                onChange={set("v8_path")}
              />
              {browseBtn("v8_path")}
            </div>
          </div>

          <div className="field-row split" style={{ marginTop: 4 }}>
            <div className="field" style={{ marginBottom: 0 }}>
              <label className="field-label">Имя расширения</label>
              <input className="field-input mono" placeholder="МоёРасширение" value={form.extension} onChange={set("extension")} />
            </div>
            <div className="field" style={{ marginBottom: 0 }}>
              <label className="field-label">Папка ext_src</label>
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  className="field-input mono"
                  placeholder="C:\...\ext_src"
                  value={form.ext_src_path}
                  onChange={set("ext_src_path")}
                />
                {browseBtn("ext_src_path")}
              </div>
            </div>
          </div>

          <div className="field" style={{ marginTop: 12 }}>
            <label className="field-label">
              Папка для кэша конфигурации
              <span style={{ marginLeft: 8, fontSize: 10, fontWeight: 400, color: "var(--text-3)", textTransform: "none", letterSpacing: 0 }}>
                необязательно · 20–40 мин · однократно
              </span>
            </label>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                className="field-input mono"
                placeholder="C:\AgenterData\scheme"
                value={form.scheme_path}
                onChange={set("scheme_path")}
              />
              {browseBtn("scheme_path")}
            </div>
            <div className="field-help">
              Если указана — будет выгружена вся конфигурация 1С и проиндексирована для поиска по базовому коду
            </div>
          </div>

          {validation && (
            <div style={{
              marginTop: 14,
              padding: "10px 14px",
              borderRadius: 8,
              background: validation.ok ? "rgba(5,150,105,0.08)" : "rgba(239,68,68,0.08)",
              border: `1px solid ${validation.ok ? "rgba(5,150,105,0.2)" : "rgba(239,68,68,0.2)"}`,
              fontSize: 12,
            }}>
              {validation.ok ? (
                <span style={{ color: "#059669" }}>✓ Всё в порядке — можно продолжить</span>
              ) : (
                <div style={{ color: "#dc2626" }}>
                  {(validation.errors || []).map((err, i) => <div key={i}>✗ {err}</div>)}
                </div>
              )}
            </div>
          )}
        </main>
      </div>
      <div className="wizard-foot">
        <span className="meta"><Icon name="lock" size={10}/> Учётные данные хранятся только локально</span>
        <div className="spacer"></div>
        <button className="dsk-btn ghost" onClick={onBack}>Назад</button>
        <button className="dsk-btn" onClick={check} disabled={checking}>
          {checking ? "Проверка…" : "Проверить"}
        </button>
        <button
          className="dsk-btn primary lg"
          onClick={() => onNext(form)}
          disabled={!validation?.ok}
        >
          Подключиться и проиндексировать <Icon name="chevron-right" size={11}/>
        </button>
      </div>
    </div>
  );
};

/* Индикатор одной фазы */
const PhaseRow = ({ label, hint, status }) => {
  const icon = status === "done"    ? <Icon name="check" size={11}/>
             : status === "skip"    ? <span style={{ fontSize: 10, opacity: .5 }}>—</span>
             : status === "running" ? <span style={{ fontSize: 9 }}>⟳</span>
             : null;
  const col  = status === "done"    ? "#059669"
             : status === "error"   ? "#dc2626"
             : status === "running" ? "var(--accent)"
             : "var(--text-3)";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "8px 12px",
      borderRadius: 6,
      background: status === "running" ? "rgba(37,99,235,0.05)" : "transparent",
      border: "1px solid",
      borderColor: status === "running" ? "rgba(37,99,235,0.15)"
                 : status === "done"    ? "rgba(5,150,105,0.15)"
                 : "transparent",
      marginBottom: 4,
    }}>
      <div style={{
        width: 20, height: 20, borderRadius: 10, flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: status === "done" ? "rgba(5,150,105,0.12)" : "var(--surface-2)",
        color: col, fontSize: 11,
      }}>{icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: col }}>{label}</div>
        {hint && <div style={{ fontSize: 10, color: "var(--text-4)", marginTop: 1 }}>{hint}</div>}
      </div>
      <div style={{ fontSize: 10, color: col, fontFamily: "var(--font-mono)", flexShrink: 0 }}>
        {status === "done" ? "DONE" : status === "skip" ? "SKIP" : status === "running" ? "..." : ""}
      </div>
    </div>
  );
};

/* Step 3 — Process (реальная индексация через Python API, три фазы) */
const Step3Process = ({ config = null, onDone = ()=>{}, onBack = ()=>{}, onSkip = ()=>{} }) => {
  const [logs, setLogs]             = useState([{ ts: "--:--:--", text: "Запуск…" }]);
  const [done, setDone]             = useState(false);
  const [error, setError]           = useState("");
  const [phase, setPhase]           = useState("");
  const [phasesDone, setPhasesDone] = useState({ scheme: false, ext: false, atlas: false });
  const [phasesSkip, setPhasesSkip] = useState({ scheme: false, ext: false, atlas: false });
  const [retryKey, setRetryKey]     = useState(0);

  const startIndexing = () => {
    setLogs([{ ts: "--:--:--", text: "Запуск…" }]);
    setDone(false);
    setError("");
    setPhase("");
    setPhasesDone({ scheme: false, ext: false, atlas: false });
    setPhasesSkip({ scheme: false, ext: false, atlas: false });
    window.pywebview?.api?.start_indexing(config).catch(console.error);
  };

  useEffect(() => {
    if (!config || !config.base_path) {
      setLogs([{ ts: "--:--:--", text: "Конфигурация не задана — шаг пропущен" }]);
      setDone(true);
      const t = setTimeout(onSkip, 1500);
      return () => clearTimeout(t);
    }

    startIndexing();

    const iv = setInterval(async () => {
      try {
        const s = await window.pywebview.api.get_indexing_status();
        if (s.logs && s.logs.length > 0) setLogs(s.logs);
        if (s.phase !== undefined) setPhase(s.phase);
        if (s.phases_done) setPhasesDone(s.phases_done);
        if (s.phases_skipped) setPhasesSkip(s.phases_skipped);
        if (s.done) {
          clearInterval(iv);
          setDone(true);
          setError(s.error || "");
          if (!s.error) setTimeout(onDone, 2000);
        }
      } catch (e) {
        console.warn("poll:", e);
      }
    }, 1000);

    return () => clearInterval(iv);
  }, [retryKey]);

  const phaseStatus = (key) => {
    if (phasesDone[key]) return "done";
    if (phasesSkip[key]) return "skip";
    if (phase === key)   return "running";
    return "idle";
  };

  const hasScheme = config?.scheme_path;

  return (
    <div className="win wizard">
      <TitleBar title="Agenter Desktop · Локальная индексация" />
      <div className="wizard-body">
        <WizardSide stepIndex={2} />
        <main className="wizard-main">
          <div className="wizard-eyebrow">
            Шаг 3 из 4 · Индексация · {done ? (error ? "ошибка" : "завершена") : "выполняется"}
          </div>
          <h1 className="wizard-title">Готовим вашу базу к работе</h1>
          <p className="wizard-sub" style={{ marginBottom: 16 }}>
            Можно свернуть окно в трей — индексация продолжится в фоне.
          </p>

          <div style={{ marginBottom: 16 }}>
            <PhaseRow
              label="Выгрузка конфигурации 1С"
              hint={hasScheme ? config.scheme_path : "пропущено — папка не указана"}
              status={hasScheme ? phaseStatus("scheme") : "skip"}
            />
            <PhaseRow
              label="Выгрузка расширения"
              hint={config?.ext_src_path || "ext_src"}
              status={phaseStatus("ext")}
            />
            <PhaseRow
              label="Индексация BSL Atlas"
              hint="localhost:8000"
              status={phaseStatus("atlas")}
            />
          </div>

          {error && (
            <div style={{
              marginBottom: 12,
              padding: "10px 14px",
              borderRadius: 8,
              background: "rgba(239,68,68,0.08)",
              border: "1px solid rgba(239,68,68,0.2)",
              fontSize: 12,
              color: "#dc2626",
            }}>
              ✗ {error}
            </div>
          )}

          <div className="proc-log" style={{ maxHeight: 160 }}>
            <div className="proc-log-head">
              <Icon name="terminal" size={11}/>
              <span>Журнал</span>
              <span style={{ marginLeft: "auto", color: done ? (error ? "#ef4444" : "#10b981") : "var(--accent)" }}>
                {done ? (error ? "ERROR" : "DONE") : "RUNNING"}
              </span>
            </div>
            <div className="proc-log-rows">
              {logs.map((r, i) => (
                <div key={i} className={`proc-log-row ${!done && i === 0 ? "run" : ""}`}>
                  <span className="ts">[{r.ts}]</span>
                  <span className="mk"></span>
                  <span>{r.text}</span>
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>
      <div className="wizard-foot">
        <span className="meta">
          {done ? (error ? "Ошибка — исправьте параметры и повторите" : "Готово") : "Индексация выполняется…"}
        </span>
        <div className="spacer"></div>
        {done && error ? (
          <>
            <button className="dsk-btn ghost" onClick={onBack}>Назад</button>
            <button className="dsk-btn primary" onClick={() => setRetryKey(k => k + 1)}>Повторить</button>
          </>
        ) : !done ? (
          <button className="dsk-btn ghost" onClick={onSkip}>Пропустить</button>
        ) : null}
      </div>
    </div>
  );
};

/* Step 4 — Done */
const Step4Done = ({ config = null, onFinish = ()=>{} }) => {
  const name    = config?.name      || "База 1С";
  const path    = config?.base_path || "";
  const extName = config?.extension || "";

  return (
    <div className="win wizard">
      <TitleBar title="Agenter Desktop · Подключение базы 1С" />
      <div className="wizard-body">
        <WizardSide stepIndex={3} />
        <main className="wizard-main">
          <div className="wizard-eyebrow">Шаг 4 из 4 · Готово</div>
          <div className="success-hero">
            <div className="success-icon"><Icon name="check" size={36}/></div>
            <h1 className="wizard-title" style={{ fontSize: 30 }}>База успешно подключена</h1>
            <p className="wizard-sub">Ассистент свернётся в трей и будет работать в фоне. Все задачи теперь можно ставить через веб-кабинет.</p>

            <div className="success-summary">
              <div className="success-row">
                <div className="success-row-name">{name}</div>
                <div className="success-row-tag">ИНДЕКС ГОТОВ</div>
              </div>
              {path && (
                <div style={{ fontSize: 12, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>
                  {path}
                </div>
              )}
              {extName && (
                <div style={{ fontSize: 12, color: "var(--text-4)", marginTop: 4 }}>
                  Расширение: {extName}
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
              <button className="dsk-btn primary lg" onClick={() => { window.pywebview?.api?.open_web_ui(); onFinish(); }}>
                <Icon name="external" size={12}/> Перейти в веб-кабинет
              </button>
              <button className="dsk-btn lg" onClick={() => { window.pywebview?.api?.finish_setup(); window.pywebview?.api?.hide_window(); }}>
                Свернуть в трей
              </button>
            </div>
          </div>
        </main>
      </div>
      <div className="wizard-foot">
        <span className="meta">десктоп-ассистент работает в фоне</span>
        <div className="spacer"></div>
        <button className="dsk-btn ghost" onClick={onFinish}>Закрыть</button>
      </div>
    </div>
  );
};

/* Main app window (stateful: polls get_status, loads config) */
const MainAppWindow = ({ onOpenSettings = ()=>{} }) => {
  const [status, setStatus] = useState({
    backend_connected: false,
    hostname: "",
    version: "1.0.0",
    logs: [],
  });
  const [baseName, setBaseName] = useState("");

  useEffect(() => {
    const init = () => {
      // Загрузить имя базы из конфига однократно
      window.pywebview.api.get_config().then(cfg => {
        if (cfg && cfg.name) setBaseName(cfg.name);
      }).catch(() => {});

      // Опрос статуса каждые 2 секунды
      const poll = () => {
        window.pywebview.api.get_status().then(s => {
          if (s) setStatus(s);
        }).catch(() => {});
      };
      poll();
      const iv = setInterval(poll, 2000);
      return () => clearInterval(iv);
    };

    let cleanup = () => {};
    if (window.pywebview) {
      cleanup = init();
    } else {
      window.addEventListener("pywebviewready", () => { cleanup = init(); }, { once: true });
    }
    return () => cleanup();
  }, []);

  // Открытие настроек через глобальное событие (из трея)
  useEffect(() => {
    const handler = () => onOpenSettings();
    window.addEventListener("agenter:open-settings", handler);
    return () => window.removeEventListener("agenter:open-settings", handler);
  }, [onOpenSettings]);

  const connected = status.backend_connected;
  const tagCls = { "+": "add", "✓": "add", "→": "mod", "○": "idx", "!": "idx", "↻": "idx" };

  return (
    <div className="win app-win">
      <TitleBar title="Agenter Desktop" withMax={false} />
      <div className="app-body">
        <div className="app-status" style={{
          background:   connected ? "" : "rgba(239,68,68,0.05)",
          borderColor:  connected ? "" : "rgba(239,68,68,0.2)",
        }}>
          <span className="app-status-pulse" style={{
            background: connected ? "" : "#9ca3af",
            boxShadow:  connected ? "" : "none",
          }}></span>
          <div className="app-status-meta">
            <div className="app-status-title" style={{ color: connected ? "" : "#b91c1c" }}>
              {connected ? "Подключено · работает в фоне" : "Нет подключения"}
            </div>
            <div className="app-status-sub" style={{ color: connected ? "" : "#6b7280" }}>
              {connected
                ? `v${status.version} · ${status.hostname}`
                : (baseName ? `${baseName} · ожидание backend…` : "Ожидание backend…")}
            </div>
          </div>
        </div>

        <div className="app-actions">
          <button className="dsk-btn primary" onClick={() => window.pywebview?.api?.open_web_ui()}>
            <Icon name="external" size={11}/> Веб-кабинет
          </button>
          <button className="dsk-btn" onClick={() => window.pywebview?.api?.reindex()}>
            <Icon name="refresh" size={11}/> Переиндексировать
          </button>
          <button className="dsk-btn" onClick={onOpenSettings}>
            <Icon name="settings" size={11}/>
          </button>
        </div>

        <div className="app-section-label">Последние действия</div>
        <div className="app-log">
          {(!status.logs || status.logs.length === 0) ? (
            <div className="app-log-row" style={{ justifyContent: "center", color: "var(--text-4)", fontSize: 11, padding: 12 }}>
              нет событий
            </div>
          ) : status.logs.map((entry, i) => (
            <div key={i} className="app-log-row">
              <span className={`app-log-tag ${tagCls[entry.tag] || "mod"}`}>{entry.tag}</span>
              <span className="app-log-text">{entry.text}</span>
              <span className="app-log-time">{entry.time}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="app-foot">
        <span>Agenter Desktop · v{status.version}</span>
        <span className="sep"></span>
        <span style={{ marginLeft: "auto", color: connected ? "#047857" : "#9ca3af" }}>
          {connected ? "● онлайн" : "○ офлайн"}
        </span>
      </div>
    </div>
  );
};

/* Settings window (loads config, saves on button click) */
const SettingsWindow = ({ onClose = ()=>{} }) => {
  const [form, setForm]     = useState({});
  const [saved, setSaved]   = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const load = () => {
      window.pywebview.api.get_config().then(cfg => {
        if (cfg) setForm(cfg);
      }).catch(() => {});
    };
    if (window.pywebview) load();
    else window.addEventListener("pywebviewready", load, { once: true });
  }, []);

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      await window.pywebview.api.save_config(form);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (_) {}
    setSaving(false);
  };

  const resetWizard = () => {
    localStorage.removeItem("agenter_setup_done");
    window.pywebview?.api?.quit_app();
  };

  return (
    <div className="win settings-win">
      <TitleBar title="Настройки · Agenter Desktop" withMax={false} />
      <div className="settings-body">
        <nav className="settings-nav">
          <div className="settings-nav-item active"><Icon name="settings" size={12}/> Общие</div>
          <div className="settings-nav-item"><Icon name="terminal" size={12}/> Базы 1С</div>
          <div className="settings-nav-item"><Icon name="shield" size={12}/> Безопасность</div>
          <div className="settings-nav-item"><Icon name="folder" size={12}/> Хранилище</div>
          <div className="settings-nav-item"><Icon name="info" size={12}/> О программе</div>
        </nav>
        <main className="settings-main">
          <h2 className="settings-h">Параметры базы 1С</h2>
          <p className="settings-hsub">Подключение и пути к конфигурации</p>

          <div className="settings-row" style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            <div className="settings-row-title">Путь к информационной базе</div>
            <input className="field-input mono" style={{ width: "100%", boxSizing: "border-box" }}
              value={form.base_path || ""} onChange={set("base_path")} />
          </div>

          <div className="settings-row" style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            <div className="settings-row-title">Логин 1С</div>
            <input className="field-input" style={{ width: "100%", boxSizing: "border-box" }}
              value={form.username || ""} onChange={set("username")} />
          </div>

          <div className="settings-row" style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            <div className="settings-row-title">Путь к платформе 1С</div>
            <input className="field-input mono" style={{ width: "100%", boxSizing: "border-box" }}
              value={form.v8_path || ""} onChange={set("v8_path")} />
          </div>

          <div className="settings-row" style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            <div className="settings-row-title">Имя расширения</div>
            <input className="field-input mono" style={{ width: "100%", boxSizing: "border-box" }}
              value={form.extension || ""} onChange={set("extension")} />
          </div>

          <div className="settings-row" style={{ flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
            <div className="settings-row-title">Папка ext_src</div>
            <input className="field-input mono" style={{ width: "100%", boxSizing: "border-box" }}
              value={form.ext_src_path || ""} onChange={set("ext_src_path")} />
          </div>

          <div style={{ marginTop: 20, display: "flex", gap: 10, alignItems: "center" }}>
            <button className="dsk-btn primary" onClick={save} disabled={saving}>
              {saving ? "Сохранение…" : "Сохранить"}
            </button>
            <button className="dsk-btn ghost" onClick={onClose}>Закрыть</button>
            {saved && <span style={{ fontSize: 12, color: "#059669" }}>✓ Сохранено</span>}
          </div>

          <div className="danger-zone" style={{ marginTop: 32 }}>
            <div className="danger-zone-title">Опасная зона</div>
            <div className="danger-zone-desc">
              Сброс запустит мастер при следующем открытии приложения.
            </div>
            <button className="dsk-btn danger" onClick={resetWizard}>
              <Icon name="log-out" size={11}/> Сбросить и перезапустить мастер
            </button>
          </div>
        </main>
      </div>
    </div>
  );
};

/* Tray notification (design mockup only) */
const TrayNotification = () => (
  <div className="tray-stage">
    <div className="taskbar">
      <div className="tb-icons">
        <div className="tb-icon" style={{ width: 32, background: "rgba(37,99,235,0.6)" }}>
          <span style={{ width: 14, height: 14, background: "#fff", borderRadius: 3 }}></span>
        </div>
      </div>
      <div className="tb-search"><Icon name="search" size={11}/> Поиск</div>
      <div className="tb-icons">
        <div className="tb-icon active"><span style={{ width: 12, height: 12, background: "#fff", borderRadius: 2 }}></span></div>
        <div className="tb-icon"><span style={{ width: 12, height: 12, background: "rgba(255,255,255,0.6)", borderRadius: 2 }}></span></div>
        <div className="tb-icon"><span style={{ width: 12, height: 12, background: "rgba(255,255,255,0.6)", borderRadius: 2 }}></span></div>
      </div>
      <div className="tb-tray">
        <div className="tb-tray-ic"><Icon name="wifi" size={12}/></div>
        <div className="tb-tray-ic"><Icon name="volume" size={12}/></div>
        <div className="tb-tray-ic"><Icon name="battery" size={14}/></div>
        <div className="tb-tray-ic"><span className="mark"></span></div>
        <span style={{ marginLeft: 8 }}>09:45<br/><span style={{ fontSize: 9 }}>04.05.2026</span></span>
      </div>
    </div>

    <div className="toast">
      <div className="toast-head">
        <div className="toast-mark"></div>
        <div className="toast-app"><strong>Agenter</strong> · Desktop Assistant</div>
        <div className="toast-time">сейчас</div>
        <div className="toast-close"><Icon name="x" size={11}/></div>
      </div>
      <div className="toast-title">
        <span className="check"><Icon name="check" size={10}/></span>
        Расширение загружено в базу
      </div>
      <div className="toast-body">
        <code>СЕРИИ_НОМЕНКЛАТУРЫ.cfe</code> применено к базе <strong>ERP Производство</strong>. 12 объектов изменено, валидация BSL прошла без ошибок. Можно тестировать.
      </div>
      <div className="toast-actions">
        <button className="toast-btn primary">Открыть в 1С</button>
        <button className="toast-btn">Веб-кабинет</button>
      </div>
    </div>
  </div>
);

/* Tray context menu (design mockup only) */
const TrayContextMenu = () => (
  <div className="tray-stage">
    <div className="taskbar">
      <div className="tb-icons">
        <div className="tb-icon" style={{ width: 32, background: "rgba(37,99,235,0.6)" }}>
          <span style={{ width: 14, height: 14, background: "#fff", borderRadius: 3 }}></span>
        </div>
      </div>
      <div className="tb-search"><Icon name="search" size={11}/> Поиск</div>
      <div style={{ flex: 1 }}></div>
      <div className="tb-tray">
        <div className="tb-tray-ic"><Icon name="wifi" size={12}/></div>
        <div className="tb-tray-ic"><Icon name="volume" size={12}/></div>
        <div className="tb-tray-ic"><Icon name="battery" size={14}/></div>
        <div className="tb-tray-ic" style={{ background: "rgba(37,99,235,0.3)", borderRadius: 4 }}><span className="mark"></span></div>
        <span style={{ marginLeft: 8 }}>09:45<br/><span style={{ fontSize: 9 }}>04.05.2026</span></span>
      </div>
    </div>

    <div className="tray-menu">
      <div className="tray-menu-status">
        <div className="tray-menu-status-row">
          <span className="dot"></span>
          <strong>Подключено</strong>
          <span style={{ marginLeft: "auto", color: "rgba(255,255,255,0.5)", fontFamily: "var(--font-mono)", fontSize: 10 }}>v1.0.0</span>
        </div>
        <div className="tray-menu-status-meta">ERP Производство · ping 12ms</div>
      </div>
      <div className="tray-menu-item"><Icon name="open" size={12}/> Открыть главное окно</div>
      <div className="tray-menu-item"><Icon name="external" size={12}/> Открыть веб-кабинет <span className="tray-menu-shortcut">Ctrl+Shift+A</span></div>
      <div className="tray-menu-sep"></div>
      <div className="tray-menu-item"><Icon name="refresh" size={12}/> Переиндексировать</div>
      <div className="tray-menu-item"><Icon name="pause" size={12}/> Приостановить агента</div>
      <div className="tray-menu-sep"></div>
      <div className="tray-menu-item"><Icon name="settings" size={12}/> Настройки</div>
      <div className="tray-menu-item"><Icon name="info" size={12}/> О программе · 1.0.0</div>
      <div className="tray-menu-sep"></div>
      <div className="tray-menu-item" style={{ color: "rgba(239,68,68,0.85)" }}><Icon name="log-out" size={12}/> Выйти</div>
    </div>
  </div>
);

window.Step1Welcome    = Step1Welcome;
window.Step2Params     = Step2Params;
window.Step3Process    = Step3Process;
window.Step4Done       = Step4Done;
window.MainAppWindow   = MainAppWindow;
window.SettingsWindow  = SettingsWindow;
window.TrayNotification = TrayNotification;
window.TrayContextMenu  = TrayContextMenu;
