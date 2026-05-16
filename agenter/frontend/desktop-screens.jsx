/* Desktop assistant components */

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

const TitleBar = ({ title, withMin = true, withMax = true }) => (
  <div className="win-titlebar">
    <div className="win-title">
      <span className="mark"></span>
      {title}
    </div>
    <div className="win-controls">
      {withMin && <div className="win-ctrl"><Icon name="minus" size={11}/></div>}
      {withMax && <div className="win-ctrl"><Icon name="square" size={9}/></div>}
      <div className="win-ctrl close"><Icon name="x" size={11}/></div>
    </div>
  </div>
);

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
          <div className="sub">v1.4.2</div>
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
const Step1Welcome = () => (
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
      <button className="dsk-btn ghost">Пропустить</button>
      <button className="dsk-btn primary lg">Начать настройку <Icon name="chevron-right" size={11}/></button>
    </div>
  </div>
);

/* Step 2 — Params */
const Step2Params = () => (
  <div className="win wizard">
    <TitleBar title="Agenter Desktop · Подключение базы 1С" />
    <div className="wizard-body">
      <WizardSide stepIndex={1} />
      <main className="wizard-main">
        <div className="wizard-eyebrow">Шаг 2 из 4 · Параметры базы</div>
        <h1 className="wizard-title">Подключение к информационной базе</h1>
        <p className="wizard-sub">Ассистент использует ваши учётные данные 1С для входа в конфигуратор. Логин и пароль остаются в защищённом локальном хранилище Windows и не передаются на серверы Agenter.</p>

        <div className="field">
          <label className="field-label">Путь к информационной базе</label>
          <div className="field-row">
            <input className="field-input mono focused" defaultValue='Srvr="dc-srv-01:1541";Ref="erp_prod";' />
            <button className="browse-btn"><Icon name="folder" size={12}/> Обзор…</button>
          </div>
          <div className="field-help">Файловая база (.1CD) или строка подключения к серверу 1С. Поддерживаются 8.3.20+.</div>
        </div>

        <div className="field-row split">
          <div className="field" style={{ marginBottom: 0 }}>
            <label className="field-label">Логин 1С</label>
            <input className="field-input" defaultValue="Администратор" />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label className="field-label">Пароль</label>
            <div style={{ position: "relative" }}>
              <input className="field-input" type="password" defaultValue="••••••••••••" />
              <span style={{ position: "absolute", right: 10, top: 10, color: "var(--text-3)", cursor: "pointer" }}>
                <Icon name="eye" size={14}/>
              </span>
            </div>
          </div>
        </div>

        <div className="field-row split" style={{ marginTop: 18 }}>
          <div className="field" style={{ marginBottom: 0 }}>
            <label className="field-label">Версия платформы</label>
            <div className="field-input" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>8.3.24.1819 <span style={{ color: "var(--text-4)", marginLeft: 6, fontFamily: "var(--font-mono)", fontSize: 11 }}>(автоопределение)</span></span>
              <Icon name="chevron-down" size={11}/>
            </div>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label className="field-label">Конфигурация</label>
            <div className="field-input" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>1С:ERP 2 (УП v4.2.5.198)</span>
              <Icon name="chevron-down" size={11}/>
            </div>
          </div>
        </div>

        <div style={{ marginTop: 22, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
          <div className="checkbox checked">
            <span className="box"><Icon name="check" size={10}/></span>
            <span>Это тестовая копия базы (рекомендуется для первого подключения)</span>
          </div>
          <div className="checkbox">
            <span className="box"></span>
            <span>Запускать ассистент при старте Windows</span>
          </div>
        </div>
      </main>
    </div>
    <div className="wizard-foot">
      <span className="meta"><Icon name="lock" size={10}/> Учётные данные шифруются Windows DPAPI</span>
      <div className="spacer"></div>
      <button className="dsk-btn ghost">Назад</button>
      <button className="dsk-btn primary lg">Подключиться и проиндексировать <Icon name="chevron-right" size={11}/></button>
    </div>
  </div>
);

/* Step 3 — Process */
const Step3Process = () => {
  const steps = [
    { name: "Выгрузка конфигурации в XML", desc: "≈ 2–4 минуты", pct: 100, status: "done" },
    { name: "Локальная индексация (BSL Atlas)", desc: "Анализ 124 873 модулей · ≈ 4–6 минут", pct: 64, status: "active" },
    { name: "Создание семантического графа", desc: "Связи объектов конфигурации", pct: 0, status: "pending" },
    { name: "Загрузка индекса в облако (только эмбеддинги)", desc: "≈ 248 МБ зашифрованных векторов", pct: 0, status: "pending" },
  ];
  const log = [
    { ts: "09:41:02", text: "Подключение к базе ERP Производство · OK" },
    { ts: "09:41:07", text: "Запуск конфигуратора в фоновом режиме" },
    { ts: "09:42:18", text: "Выгрузка метаданных завершена · 1 284 объектов" },
    { ts: "09:42:24", text: "Запуск BSL Atlas · версия 2.4.1" },
    { ts: "09:43:51", text: "Индексация модулей: 38 % (47 412 / 124 873)" },
    { ts: "09:44:42", text: "Индексация модулей: 64 % (79 918 / 124 873)", run: true },
  ];
  return (
    <div className="win wizard">
      <TitleBar title="Agenter Desktop · Индексация ERP Производство" />
      <div className="wizard-body">
        <WizardSide stepIndex={2} />
        <main className="wizard-main">
          <div className="wizard-eyebrow">Шаг 3 из 4 · Индексация · идёт прямо сейчас</div>
          <h1 className="wizard-title">Готовим вашу базу к работе</h1>
          <p className="wizard-sub" style={{ marginBottom: 24 }}>Не закрывайте окно. Ассистент работает локально и не передаёт исходный код наружу. Можно свернуть в трей и продолжить заниматься другими задачами.</p>

          <div className="proc-stepper">
            {steps.map((s, i) => (
              <div key={i} className={`proc-step ${s.status}`}>
                <div className="proc-step-bullet">{s.status === "done" ? <Icon name="check" size={11}/> : i + 1}</div>
                <div className="proc-step-meta">
                  <div className="proc-step-name">{s.name}</div>
                  <div className="proc-step-desc">{s.desc}</div>
                  <div className="proc-step-bar">
                    <div className="proc-step-bar-fill" style={{ width: `${s.pct}%` }}></div>
                  </div>
                </div>
                <div className="proc-step-pct">{s.pct}%</div>
              </div>
            ))}
          </div>

          <div className="proc-log">
            <div className="proc-log-head">
              <Icon name="terminal" size={11}/>
              <span>Журнал выполнения · ~/.agenter/logs/setup-04may.log</span>
              <span style={{ marginLeft: "auto", color: "var(--accent)" }}>RUNNING</span>
            </div>
            <div className="proc-log-rows">
              {log.map((r, i) => (
                <div key={i} className={`proc-log-row ${r.run ? "run" : ""}`} style={{ animationDelay: `${i * 100}ms` }}>
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
        <span className="meta">осталось ≈ 6 мин 12 с · CPU 32% · RAM 1.4 ГБ</span>
        <div className="spacer"></div>
        <button className="dsk-btn"><Icon name="pause" size={11}/> Пауза</button>
        <button className="dsk-btn danger">Отменить</button>
      </div>
    </div>
  );
};

/* Step 4 — Done */
const Step4Done = () => (
  <div className="win wizard">
    <TitleBar title="Agenter Desktop · Подключение базы 1С" />
    <div className="wizard-body">
      <WizardSide stepIndex={3} />
      <main className="wizard-main">
        <div className="wizard-eyebrow">Шаг 4 из 4 · Готово</div>
        <div className="success-hero">
          <div className="success-icon"><Icon name="check" size={36}/></div>
          <h1 className="wizard-title" style={{ fontSize: 30 }}>База успешно подключена</h1>
          <p className="wizard-sub">Ассистент свернётся в трей и будет работать в фоне. Все задачи теперь можно ставить через веб-кабинет — изменения автоматически попадут в эту базу.</p>

          <div className="success-summary">
            <div className="success-row">
              <div className="success-row-name">ERP Производство v4.2</div>
              <div className="success-row-tag">ИНДЕКС АКТУАЛЕН</div>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>
              Srvr="dc-srv-01:1541";Ref="erp_prod";
            </div>
            <div className="success-grid">
              <div className="success-stat">
                <div className="success-stat-label">Объектов</div>
                <div className="success-stat-value">1 284</div>
              </div>
              <div className="success-stat">
                <div className="success-stat-label">Модулей</div>
                <div className="success-stat-value">124 873</div>
              </div>
              <div className="success-stat">
                <div className="success-stat-label">Размер индекса</div>
                <div className="success-stat-value">248 МБ</div>
              </div>
              <div className="success-stat">
                <div className="success-stat-label">Время</div>
                <div className="success-stat-value">8 м 14 с</div>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
            <button className="dsk-btn primary lg"><Icon name="external" size={12}/> Перейти в веб-кабинет</button>
            <button className="dsk-btn lg">Свернуть в трей</button>
          </div>
        </div>
      </main>
    </div>
    <div className="wizard-foot">
      <span className="meta">десктоп-ассистент работает в фоне · WIN-DEV-04 · ping 12ms</span>
      <div className="spacer"></div>
      <button className="dsk-btn ghost">Закрыть</button>
    </div>
  </div>
);

/* Main app window */
const MainAppWindow = () => (
  <div className="win app-win">
    <TitleBar title="Agenter Desktop" withMax={false} />
    <div className="app-body">
      <div className="app-status">
        <span className="app-status-pulse"></span>
        <div className="app-status-meta">
          <div className="app-status-title">Подключено · работает в фоне</div>
          <div className="app-status-sub">v1.4.2 · WIN-DEV-04 · ping 12ms</div>
        </div>
      </div>

      <div className="app-card">
        <div className="app-card-head">
          <div className="app-card-ic">ERP</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="app-card-title">ERP Производство v4.2</div>
            <div className="app-card-sub">Индекс актуален · 47 мин назад</div>
          </div>
          <button className="dsk-btn ghost" style={{ height: 26, padding: "0 8px" }}><Icon name="refresh" size={12}/></button>
        </div>
        <div className="app-card-stats">
          <div className="acs"><div className="acs-label">Объектов</div><div className="acs-value">1 284</div></div>
          <div className="acs"><div className="acs-label">Индекс</div><div className="acs-value">248 МБ</div></div>
          <div className="acs"><div className="acs-label">Платформа</div><div className="acs-value">8.3.24</div></div>
        </div>
      </div>

      <div className="app-actions">
        <button className="dsk-btn primary"><Icon name="external" size={11}/> Веб-кабинет</button>
        <button className="dsk-btn"><Icon name="refresh" size={11}/> Переиндексировать</button>
        <button className="dsk-btn"><Icon name="settings" size={11}/></button>
      </div>

      <div className="app-section-label">Последние действия</div>
      <div className="app-log">
        <div className="app-log-row">
          <span className="app-log-tag add">+</span>
          <span className="app-log-text">Расширение СЕРИИ_НОМЕНКЛАТУРЫ.cfe загружено</span>
          <span className="app-log-time">09:45</span>
        </div>
        <div className="app-log-row">
          <span className="app-log-tag mod">~</span>
          <span className="app-log-text">Форма документа РТУ модифицирована</span>
          <span className="app-log-time">09:43</span>
        </div>
        <div className="app-log-row">
          <span className="app-log-tag add">+</span>
          <span className="app-log-text">РН ОстаткиТоваровПоСериям</span>
          <span className="app-log-time">09:42</span>
        </div>
        <div className="app-log-row">
          <span className="app-log-tag idx">↻</span>
          <span className="app-log-text">Инкрементальная переиндексация</span>
          <span className="app-log-time">09:41</span>
        </div>
        <div className="app-log-row">
          <span className="app-log-tag add">+</span>
          <span className="app-log-text">Отчёт ДебиторскаяЗадолженность</span>
          <span className="app-log-time">вчера</span>
        </div>
      </div>
    </div>
    <div className="app-foot">
      <span>Agenter Desktop · v1.4.2</span>
      <span className="sep"></span>
      <span>build 4821</span>
      <span style={{ marginLeft: "auto", color: "#047857" }}>● онлайн</span>
    </div>
  </div>
);

/* Settings modal */
const SettingsWindow = () => (
  <div className="win settings-win">
    <TitleBar title="Настройки · Agenter Desktop" withMax={false} />
    <div className="settings-body">
      <nav className="settings-nav">
        <div className="settings-nav-item active"><Icon name="settings" size={12}/> Общие</div>
        <div className="settings-nav-item"><Icon name="terminal" size={12}/> Базы 1С</div>
        <div className="settings-nav-item"><Icon name="shield" size={12}/> Безопасность</div>
        <div className="settings-nav-item"><Icon name="folder" size={12}/> Хранилище</div>
        <div className="settings-nav-item"><Icon name="user" size={12}/> Аккаунт</div>
        <div className="settings-nav-item"><Icon name="info" size={12}/> О программе</div>
      </nav>
      <main className="settings-main">
        <h2 className="settings-h">Общие</h2>
        <p className="settings-hsub">Поведение ассистента в системе и журналирование</p>

        <div className="settings-row">
          <div className="settings-row-meta">
            <div className="settings-row-title">Запускать вместе с Windows</div>
            <div className="settings-row-desc">Ассистент будет автоматически стартовать в трее при входе в систему</div>
          </div>
          <div className="toggle on"></div>
        </div>

        <div className="settings-row">
          <div className="settings-row-meta">
            <div className="settings-row-title">Сворачивать в трей при закрытии</div>
            <div className="settings-row-desc">Иначе при нажатии × приложение будет полностью закрываться</div>
          </div>
          <div className="toggle on"></div>
        </div>

        <div className="settings-row">
          <div className="settings-row-meta">
            <div className="settings-row-title">Папка для временных файлов</div>
            <div className="settings-row-desc">Здесь хранятся выгруженные XML и кэш индекса</div>
          </div>
          <button className="dsk-btn"><Icon name="folder" size={11}/> C:\Users\…\.agenter</button>
        </div>

        <div className="settings-row">
          <div className="settings-row-meta">
            <div className="settings-row-title">Уровень логирования</div>
            <div className="settings-row-desc">Подробные логи помогают поддержке быстрее найти проблему</div>
          </div>
          <div className="settings-select">Standard <Icon name="chevron-down" size={10}/></div>
        </div>

        <div className="settings-row">
          <div className="settings-row-meta">
            <div className="settings-row-title">Включить подробный лог выполнения</div>
            <div className="settings-row-desc">Каждый шаг агента сохраняется на диск (увеличивает размер логов)</div>
          </div>
          <div className="toggle"></div>
        </div>

        <div className="settings-row">
          <div className="settings-row-meta">
            <div className="settings-row-title">Автоматические обновления</div>
            <div className="settings-row-desc">Текущая версия 1.4.2 · последняя проверка 12 мин назад</div>
          </div>
          <div className="toggle on"></div>
        </div>

        <div className="danger-zone">
          <div className="danger-zone-title">Опасная зона</div>
          <div className="danger-zone-desc">
            Отключение базы удаляет локальный индекс и разрывает связь с веб-кабинетом. Историю задач это не затрагивает.
          </div>
          <button className="dsk-btn danger"><Icon name="log-out" size={11}/> Отключить базу ERP Производство</button>
        </div>
      </main>
    </div>
  </div>
);

/* Tray notification */
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
        <code>СЕРИИ_НОМЕНКЛАТУРЫ.cfe</code> применено к базе <strong>ERP Производство v4.2</strong>. 12 объектов изменено, валидация BSL прошла без ошибок. Можно тестировать.
      </div>
      <div className="toast-actions">
        <button className="toast-btn primary">Открыть в 1С</button>
        <button className="toast-btn">Веб-кабинет</button>
      </div>
    </div>
  </div>
);

/* Tray context menu */
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
          <span style={{ marginLeft: "auto", color: "rgba(255,255,255,0.5)", fontFamily: "var(--font-mono)", fontSize: 10 }}>v1.4.2</span>
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
      <div className="tray-menu-item"><Icon name="info" size={12}/> О программе · 1.4.2</div>
      <div className="tray-menu-sep"></div>
      <div className="tray-menu-item" style={{ color: "rgba(239,68,68,0.85)" }}><Icon name="log-out" size={12}/> Выйти</div>
    </div>
  </div>
);

window.Step1Welcome = Step1Welcome;
window.Step2Params = Step2Params;
window.Step3Process = Step3Process;
window.Step4Done = Step4Done;
window.MainAppWindow = MainAppWindow;
window.SettingsWindow = SettingsWindow;
window.TrayNotification = TrayNotification;
window.TrayContextMenu = TrayContextMenu;
