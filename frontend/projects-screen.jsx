/* Projects list screen */

const ProjectsSidebar = () => (
  <aside className="sidebar">
    <div className="brand">
      <div className="brand-mark"></div>
      <div className="brand-name">Agenter</div>
      <div className="brand-version">v0.9.4</div>
    </div>
    <div className="side-section">
      <div className="side-section-header">
        <div className="side-label">Навигация</div>
      </div>
      {[
        { name: "Все базы", icon: "database", active: true, count: 7 },
        { name: "Активные сессии", icon: "spark", count: 2 },
        { name: "История задач", icon: "history", count: 184 },
        { name: "Шаблоны и пресеты", icon: "folder", count: 12 },
        { name: "Команда", icon: "user", count: 4 },
      ].map((n, i) => (
        <div key={i} className={`base-card ${n.active ? "active" : ""}`}>
          <div className="base-icon" style={{ background: n.active ? "var(--surface)" : "transparent", border: "1px solid var(--border)" }}>
            <Icon name={n.icon} size={13} className="ic-sm" style={{ color: "var(--text-2)" }} />
          </div>
          <div className="base-meta">
            <div className="base-name" style={{ fontSize: 13 }}>{n.name}</div>
          </div>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--text-4)" }}>{n.count}</span>
        </div>
      ))}
    </div>

    <div className="divider"></div>

    <div className="side-section" style={{ flex: 1 }}>
      <div className="side-section-header">
        <div className="side-label">Закреплённые</div>
      </div>
      {[
        { icon: "ERP", name: "ERP Производство v4.2", status: "green" },
        { icon: "ЗУП", name: "ЗУП КОРП v3.1", status: "green" },
      ].map((b, i) => (
        <div key={i} className="base-card">
          <div className="base-icon">{b.icon}</div>
          <div className="base-meta">
            <div className="base-name">{b.name}</div>
            <div className="base-sub"><span className={`dot ${b.status}`}></span><span>Готов</span></div>
          </div>
        </div>
      ))}
    </div>

    <div className="sidebar-footer">
      <div className="avatar">ДК</div>
      <div className="user-meta">
        <div className="user-name">Дмитрий К.</div>
        <div className="user-org">Франчайзи · Северо-Запад</div>
      </div>
    </div>
  </aside>
);

const ProjectCard = ({ p }) => (
  <div className="project-card">
    <div className="project-head">
      <div className="project-icon">{p.icon}</div>
      <div className="project-meta">
        <div className="project-name">{p.name}</div>
        <div className="project-version">{p.version}</div>
      </div>
      <button className="icon-btn" style={{ width: 26, height: 26 }}><Icon name="more" size={13} className="ic-sm" /></button>
    </div>
    <div className="project-stats">
      <div>
        <div className="pstat-label">Задач</div>
        <div className="pstat-value">{p.tasks}</div>
      </div>
      <div>
        <div className="pstat-label">Объекты</div>
        <div className="pstat-value">{p.objects}</div>
      </div>
      <div>
        <div className="pstat-label">Размер</div>
        <div className="pstat-value">{p.size}</div>
      </div>
    </div>
    <div className="project-foot">
      <span className={`status-pill ${p.statusColor}`}>
        <span className={`dot ${p.statusColor}`}></span>
        {p.statusText}
      </span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--text-4)" }}>{p.updated}</span>
    </div>
  </div>
);

const ProjectsScreen = () => {
  const projects = [
    { icon: "ERP", name: "ERP Производство v4.2", version: "1С:ERP 2 · сервер · 8.3.24", tasks: "47", objects: "1 284", size: "4.8 ГБ", statusColor: "green", statusText: "Индекс актуален", updated: "47 мин назад" },
    { icon: "ЗУП", name: "ЗУП КОРП v3.1", version: "1С:ЗУП КОРП · сервер · 8.3.22", tasks: "23", objects: "892", size: "2.1 ГБ", statusColor: "green", statusText: "Индекс актуален", updated: "3 ч назад" },
    { icon: "УТ", name: "Управление торговлей 11.5", version: "1С:УТ · файловая · 8.3.24", tasks: "8", objects: "—", size: "—", statusColor: "amber", statusText: "Индексация · 62%", updated: "идёт сейчас" },
    { icon: "БП", name: "Бухгалтерия 3.0 — Клиент А", version: "1С:БП КОРП · сервер · 8.3.21", tasks: "0", objects: "—", size: "—", statusColor: "gray", statusText: "Не подключено", updated: "2 дня назад" },
    { icon: "РО", name: "Розница 2.3 — сеть Север", version: "1С:Розница · файловая · 8.3.20", tasks: "12", objects: "612", size: "1.4 ГБ", statusColor: "green", statusText: "Индекс актуален", updated: "вчера" },
    { icon: "КА", name: "Комплексная автоматизация 2.5", version: "1С:КА 2 · сервер · 8.3.23", tasks: "31", objects: "1 042", size: "3.6 ГБ", statusColor: "green", statusText: "Индекс актуален", updated: "12 ч назад" },
    { icon: "ДО", name: "Документооборот 3.0", version: "1С:ДО КОРП · сервер · 8.3.24", tasks: "5", objects: "478", size: "0.9 ГБ", statusColor: "amber", statusText: "Требуется переиндексация", updated: "5 дней назад" },
  ];

  return (
    <div className="projects" data-screen-label="03 Projects list">
      <ProjectsSidebar />
      <main className="projects-main">
        <div className="projects-head">
          <div>
            <h1 className="projects-title">Мои базы</h1>
            <div className="projects-sub">7 баз · 126 задач за месяц · 4 активных сессии</div>
          </div>
          <div className="projects-toolbar">
            <div className="search">
              <Icon name="search" size={14} className="ic" style={{ color: "var(--text-3)" }} />
              <input placeholder="Поиск по базам, задачам, объектам…" />
              <span className="kbd">⌘K</span>
            </div>
            <button className="btn"><Icon name="filter" size={13} className="ic" /> Фильтры</button>
            <button className="btn"><Icon name="sort" size={13} className="ic" /> По активности</button>
            <button className="btn primary"><Icon name="plus" size={13} className="ic" /> Подключить базу</button>
          </div>
        </div>

        <div className="tabs">
          <div className="tab active">Все <span className="pill">7</span></div>
          <div className="tab">Готовые <span className="pill">5</span></div>
          <div className="tab">Индексация <span className="pill">1</span></div>
          <div className="tab">Не подключены <span className="pill">1</span></div>
          <div className="tab">Архив</div>
        </div>

        <div className="project-grid">
          {projects.map((p, i) => <ProjectCard key={i} p={p} />)}
          <div className="project-card add">
            <Icon name="plus" size={20} className="ic-lg" style={{ marginBottom: 10 }} />
            <div style={{ fontFamily: "var(--font-display)", fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Подключить новую базу</div>
            <div style={{ fontSize: 12, lineHeight: 1.5, maxWidth: 220 }}>Через десктоп-ассистент. Конфигурация остаётся на вашей машине.</div>
          </div>
        </div>
      </main>
    </div>
  );
};

window.ProjectsScreen = ProjectsScreen;
