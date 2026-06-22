/* First-base connection screen */

const ConnectSidebar = () => (
  <aside className="sidebar">
    <div className="brand">
      <div className="brand-mark"></div>
      <div className="brand-name">Agenter</div>
      <div className="brand-version">v0.9.4</div>
    </div>
    <div className="side-section">
      <div className="side-section-header">
        <div className="side-label">Мои базы</div>
        <div className="side-count">0</div>
      </div>
      <div style={{
        padding: "20px 12px",
        textAlign: "center",
        fontSize: 12,
        color: "var(--text-3)",
        border: "1px dashed var(--border)",
        borderRadius: 8,
        margin: "4px 0",
        lineHeight: 1.5,
      }}>
        Подключите первую базу,<br/>чтобы начать работу
      </div>
    </div>
    <div className="divider"></div>
    <div className="side-section" style={{ flex: 1 }}>
      <div className="side-section-header">
        <div className="side-label">Документация</div>
      </div>
      <div className="history-list">
        {[
          "Что умеет Agenter",
          "Как работает индексация",
          "Безопасность и приватность",
          "Десктоп-ассистент 1.4",
          "Тарифы и лимиты",
        ].map((t, i) => (
          <div key={i} className="history-item">
            <div className="history-text">{t}</div>
          </div>
        ))}
      </div>
    </div>
    <div className="sidebar-footer">
      <div className="avatar">ДК</div>
      <div className="user-meta">
        <div className="user-name">Дмитрий К.</div>
        <div className="user-org">Trial · 13 дней</div>
      </div>
    </div>
  </aside>
);

const ConnectScreen = () => {
  return (
    <div className="connect" data-screen-label="02 Connect base">
      <ConnectSidebar />
      <main className="connect-main">
        <div className="connect-eyebrow">Подключение базы · шаг 2 из 3</div>
        <h1 className="connect-title">Подключите вашу базу 1С</h1>
        <p className="connect-sub">
          Agenter работает локально через десктоп-ассистент — конфигурация никогда не покидает ваш контур. Индексация выполняется на вашей машине, в облако уходят только зашифрованные эмбеддинги для поиска.
        </p>

        <div className="steps">
          <div className="step done">
            <div className="step-num">01 ✓</div>
            <div className="step-title">Установка ассистента</div>
            <div className="step-desc">Десктоп-приложение установлено и подключено к аккаунту</div>
            <div className="step-bar"></div>
          </div>
          <div className="step active">
            <div className="step-num">02</div>
            <div className="step-title">Параметры базы</div>
            <div className="step-desc">Укажите путь и платформу — ассистент проверит доступ</div>
            <div className="step-bar"></div>
          </div>
          <div className="step">
            <div className="step-num">03</div>
            <div className="step-title">Индексация конфигурации</div>
            <div className="step-desc">Локальный анализ метаданных и BSL-кода — обычно 8–25 мин</div>
            <div className="step-bar"></div>
          </div>
        </div>

        <div className="connect-grid">
          <div className="connect-card">
            <h3>Параметры базы</h3>

            <div className="field">
              <label className="field-label">Название базы</label>
              <input className="field-input" defaultValue="ERP Производство v4.2" />
              <div className="field-help">Только для отображения внутри Agenter — не влияет на 1С</div>
            </div>

            <div className="field-row">
              <div className="field">
                <label className="field-label">Тип конфигурации</label>
                <div className="field-input" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}>
                  <span>1С:ERP Управление предприятием 2</span>
                  <Icon name="chevron-down" size={12} className="ic-sm" style={{ color: "var(--text-3)" }} />
                </div>
              </div>
              <div className="field">
                <label className="field-label">Версия платформы</label>
                <div className="field-input" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}>
                  <span>8.3.24.1819</span>
                  <Icon name="chevron-down" size={12} className="ic-sm" style={{ color: "var(--text-3)" }} />
                </div>
              </div>
            </div>

            <div className="field">
              <label className="field-label">Подключение</label>
              <input className="field-input mono" defaultValue="Srvr=&quot;dc-srv-01&quot;;Ref=&quot;erp_prod&quot;;" />
              <div className="field-help">Серверная или файловая база. Ассистент использует ваши учётные данные 1С — мы не запрашиваем пароли.</div>
            </div>

            <div className="field-row">
              <div className="field">
                <label className="field-label">Режим работы</label>
                <div className="field-input" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span>Тестовая копия (рекомендуется)</span>
                  <span style={{
                    fontFamily: "var(--font-mono)", fontSize: 10,
                    background: "var(--success-soft)", color: "#047857",
                    padding: "2px 6px", borderRadius: 4,
                  }}>SAFE</span>
                </div>
              </div>
              <div className="field">
                <label className="field-label">Глубина индексации</label>
                <div className="field-input" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}>
                  <span>Полная (метаданные + BSL)</span>
                  <Icon name="chevron-down" size={12} className="ic-sm" style={{ color: "var(--text-3)" }} />
                </div>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 22, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
              <button className="btn">Назад</button>
              <div style={{ flex: 1 }}></div>
              <button className="btn ghost">Сохранить и закрыть</button>
              <button className="btn primary">
                Проверить и проиндексировать
                <Icon name="chevron-right" size={12} className="ic-sm" />
              </button>
            </div>
          </div>

          <div>
            <div className="assistant-status-card connected">
              <div className="host-icon" style={{ background: "#fff", borderColor: "rgba(16,185,129,0.3)" }}>
                <Icon name="terminal" size={14} className="ic" style={{ color: "#047857" }} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#065F46", display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--success)", boxShadow: "0 0 0 3px rgba(16,185,129,0.25)" }}></span>
                  Десктоп-ассистент подключён
                </div>
                <div style={{ fontSize: 11.5, color: "#047857", fontFamily: "var(--font-mono)", marginTop: 3, letterSpacing: "0.02em" }}>
                  WIN-DEV-04 · v1.4.2 · ping 12ms
                </div>
              </div>
            </div>

            <div className="connect-card">
              <h3 style={{ marginBottom: 4 }}>Что произойдёт дальше</h3>
              <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 14 }}>
                Локальная индексация без отправки кода в облако
              </div>
              <div className="connect-tips">
                <div className="tip">
                  <span className="tip-num">1</span>
                  <div>Ассистент откроет конфигуратор в фоне и выгрузит метаданные в локальную папку <code style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>~/.agenter/cache/</code></div>
                </div>
                <div className="tip">
                  <span className="tip-num">2</span>
                  <div>BSL-код, формы и роли разбираются на семантические блоки. Эмбеддинги шифруются перед отправкой в индекс.</div>
                </div>
                <div className="tip">
                  <span className="tip-num">3</span>
                  <div>В облако уходят только векторы. Исходники, имена реквизитов и тексты модулей остаются у вас.</div>
                </div>
                <div className="tip">
                  <span className="tip-num">4</span>
                  <div>По окончании вы получите уведомление и сможете сразу задавать задачи в чате.</div>
                </div>
              </div>

              <div className="terminal">
                <div><span className="prompt">›</span> agenter check --base erp_prod</div>
                <div className="out">  Проверка соединения с сервером 1С................<span className="ok">OK</span></div>
                <div className="out">  Доступ к конфигуратору ............................<span className="ok">OK</span></div>
                <div className="out">  Версия платформы 8.3.24.1819 ......................<span className="ok">OK</span></div>
                <div className="out">  Прогноз индексации ................................<span style={{color:"#FCD34D"}}>~14 мин</span></div>
                <div><span className="prompt">›</span> _</div>
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};

window.ConnectScreen = ConnectScreen;
