"use strict";

/**
 * MetadataTree — компонент дерева метаданных 1С.
 *
 * Прогрессивно загружает структуру конфигурации (типы → объекты → группы → члены)
 * через SSE-эндпоинт GET /metadata/tree/stream.
 *
 * Использует SVG-иконки из /ui/assets/icons/dark/<icon>.svg (порт из MetadataViewer1C).
 */

const ICON_BASE_PATH = "assets/icons/dark";

// Используется в OpRow и для общих утилит
const fmtCount = (n) => {
  if (!n && n !== 0) return "";
  if (n >= 1000) return (n / 1000).toFixed(1).replace(".0", "") + "k";
  return String(n);
};

/**
 * Согласование числительного с существительным (1 тип / 2 типа / 5 типов).
 * forms — массив [одушевл.ед.ч, двойств.ч, множ.ч]:
 *   [0]: 1, 21, 31...   → одушевленная
 *   [1]: 2-4, 22-24...  → двойственная
 *   [2]: 5-20, 25-30... → множественная
 */
const pluralRu = (n, forms) => {
  const abs = Math.abs(n);
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  if (mod100 >= 11 && mod100 <= 14) return `${n} ${forms[2]}`;
  if (mod10 === 1) return `${n} ${forms[0]}`;
  if (mod10 >= 2 && mod10 <= 4) return `${n} ${forms[1]}`;
  return `${n} ${forms[2]}`;
};

const PLURAL_TYPES   = ["тип", "типа", "типов"];
const PLURAL_OBJECTS = ["объект", "объекта", "объектов"];

/** Иконка объекта 1С (SVG). icon — имя без расширения. */
const ObjectIcon = ({ icon, size = 14, fallback = "common" }) => {
  if (!icon) icon = fallback;
  const src = `${ICON_BASE_PATH}/${icon}.svg`;
  return (
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      style={{
        flexShrink: 0,
        opacity: 0.85,
        verticalAlign: "middle",
      }}
      onError={(e) => {
        // если иконки нет — пробуем common.svg
        if (e.target.dataset.fallbackUsed) return;
        e.target.dataset.fallbackUsed = "1";
        e.target.src = `${ICON_BASE_PATH}/common.svg`;
      }}
    />
  );
};

/**
 * TreeNode — рекурсивный узел дерева.
 *
 * props.node — { id, label, kind, icon, children?, object?, member? }
 * props.depth — текущая глубина (0 для корня)
 */
const TreeNode = ({ node, depth = 0, autoOpen = false }) => {
  const [open, setOpen] = React.useState(autoOpen);
  const hasChildren = node.children && node.children.length > 0;

  // Корень не рендерим как обычный узел — показываем сразу детей
  if (node.kind === "root") {
    return (
      <div className="mt-root">
        {(node.children || []).map((c) => (
          <TreeNode key={c.id} node={c} depth={0} />
        ))}
      </div>
    );
  }

  const handleClick = () => {
    if (hasChildren) setOpen((o) => !o);
  };

  // Цвет по виду узла
  const kindColor = {
    type: "var(--text-1)",
    group: "var(--text-2)",
    object: "var(--text-1)",
    member: "var(--text-2)",
  }[node.kind] || "var(--text-2)";

  const fontWeight = node.kind === "type" ? 600 : node.kind === "object" ? 500 : 400;

  return (
    <div className="mt-node">
      <div
        className="mt-row"
        onClick={handleClick}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "2px 4px",
          paddingLeft: depth * 12 + 4,
          cursor: hasChildren ? "pointer" : "default",
          fontSize: 12,
          color: kindColor,
          fontWeight,
          lineHeight: 1.4,
          userSelect: "none",
          borderRadius: 3,
          transition: "background 0.1s",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(0,0,0,0.04)")}
        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        title={node.object?.source_path || node.label}
      >
        {/* Стрелка для раскрытия */}
        <span style={{
          width: 10,
          color: "var(--text-3)",
          fontSize: 9,
          display: "inline-block",
          transform: open ? "rotate(90deg)" : "rotate(0deg)",
          transition: "transform 0.15s",
        }}>
          {hasChildren ? "▶" : ""}
        </span>

        {/* Иконка */}
        {node.icon && <ObjectIcon icon={node.icon} size={14} />}

        {/* Label */}
        <span style={{
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          flex: 1,
          minWidth: 0,
        }}>
          {node.label}
        </span>
      </div>

      {/* Дети */}
      {open && hasChildren && (
        <div className="mt-children">
          {node.children.map((c) => (
            <TreeNode key={c.id} node={c} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
};

/**
 * MetadataTree — главный компонент.
 *
 * Состояния:
 *   idle        — ничего не делаем, готов к запуску
 *   loading     — идёт SSE-стрим (прогрессивная загрузка)
 *   ready       — дерево загружено
 *   error       — ошибка
 *
 * При первой загрузке вызывает /metadata/tree/stream — типы появляются
 * один за другим. При повторном открытии (кэш) полное дерево приходит
 * мгновенно.
 */
const MetadataTree = ({ config, autoLoad = false }) => {
  const [state, setState] = React.useState("idle");      // idle | loading | ready | error
  const [types, setTypes] = React.useState([]);          // массив type-нод (slim)
  const [error, setError] = React.useState(null);
  const [progress, setProgress] = React.useState({ types: 0, objects: 0 });
  const [filter, setFilter] = React.useState("");
  const esRef = React.useRef(null);

  const schemeRoot = config?.scheme_path || null;
  const hasRoot = Boolean(schemeRoot);

  const startStream = React.useCallback(() => {
    if (state === "loading") return;
    setState("loading");
    setError(null);
    setTypes([]);
    setProgress({ types: 0, objects: 0 });

    const es = AgenterAPI.streamMetadataTree(
      {
        onStart: (data) => {
          console.log("[metadata-tree] start", data);
        },
        onType: (typeNode) => {
          setTypes((prev) => {
            const nextTypes = [...prev, typeNode].sort((a, b) =>
              a.label.localeCompare(b.label, "ru")
            );
            const totalObjects = nextTypes.reduce(
              (sum, t) => sum + ((t.children || []).length), 0
            );
            setProgress({ types: nextTypes.length, objects: totalObjects });
            return nextTypes;
          });
        },
        onDone: (data) => {
          console.log("[metadata-tree] done", data);
          setState("ready");
        },
        onError: (data) => {
          console.error("[metadata-tree] error", data);
          setError(data.message || "Ошибка загрузки");
          setState("error");
        },
      },
      schemeRoot
    );
    esRef.current = es;
  }, [schemeRoot, state]);

  const stopStream = React.useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (state === "loading") setState("idle");
  }, [state]);

  React.useEffect(() => {
    if (autoLoad && hasRoot && state === "idle") {
      startStream();
    }
    return () => {
      if (esRef.current) esRef.current.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLoad, hasRoot]);

  // Фильтрация
  const filteredTypes = React.useMemo(() => {
    if (!filter) return types;
    const f = filter.toLowerCase();
    return types
      .map((t) => {
        const filteredChildren = (t.children || []).filter((obj) =>
          (obj.label || "").toLowerCase().includes(f)
        );
        if (filteredChildren.length === 0 && !t.label.toLowerCase().includes(f)) {
          return null;
        }
        return { ...t, children: filteredChildren.length ? filteredChildren : t.children };
      })
      .filter(Boolean);
  }, [types, filter]);

  if (!hasRoot) {
    return (
      <div style={{ padding: "12px 8px", fontSize: 12, color: "var(--text-4)", textAlign: "center", lineHeight: 1.6 }}>
        Не задан scheme_path в Настройках
      </div>
    );
  }

  if (state === "idle") {
    return (
      <div style={{ padding: "12px 8px", textAlign: "center" }}>
        <button
          onClick={startStream}
          className="btn btn-secondary"
          style={{
            fontSize: 12,
            padding: "6px 12px",
            borderRadius: 6,
            cursor: "pointer",
          }}
        >
          <Icon name="tree" size={12} className="ic-sm" style={{ marginRight: 4 }} />
          Загрузить метаданные
        </button>
        <div style={{ fontSize: 11, color: "var(--text-4)", marginTop: 8 }}>
          ~45 сек на первую загрузку
        </div>
      </div>
    );
  }

  return (
    <div className="metadata-tree-wrap" style={{
      display: "flex",
      flexDirection: "column",
      gap: 6,
      flex: 1,
      minHeight: 0,
      height: "100%",
    }}>
      {/* Прогресс / статус */}
      <div style={{
        fontSize: 11,
        color: state === "loading" ? "var(--accent)" : "var(--text-3)",
        padding: "0 4px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <span>
          {state === "loading" && (
            <>
              <span style={{
                display: "inline-block",
                width: 6, height: 6,
                borderRadius: "50%",
                background: "var(--accent)",
                marginRight: 6,
                animation: "pulse 1.2s ease-in-out infinite",
              }}></span>
              Загружаю · {pluralRu(progress.types, PLURAL_TYPES)} · {pluralRu(progress.objects, PLURAL_OBJECTS)}
            </>
          )}
          {state === "ready" && (
            <>{pluralRu(progress.types, PLURAL_TYPES)} · {pluralRu(progress.objects, PLURAL_OBJECTS)}</>
          )}
          {state === "error" && (
            <span style={{ color: "var(--danger, #ef4444)" }}>Ошибка: {error}</span>
          )}
        </span>
        {state === "loading" && (
          <button
            onClick={stopStream}
            style={{
              fontSize: 10, padding: "2px 6px",
              background: "transparent", border: "1px solid var(--border)",
              borderRadius: 4, cursor: "pointer", color: "var(--text-3)",
            }}
          >Стоп</button>
        )}
        {state === "ready" && (
          <button
            onClick={() => {
              AgenterAPI.invalidateMetadata(schemeRoot).then(() => startStream());
            }}
            style={{
              fontSize: 10, padding: "2px 6px",
              background: "transparent", border: "1px solid var(--border)",
              borderRadius: 4, cursor: "pointer", color: "var(--text-3)",
            }}
            title="Сбросить кэш и перезагрузить"
          >↻</button>
        )}
      </div>

      {/* Фильтр */}
      {types.length > 0 && (
        <input
          type="text"
          placeholder="Фильтр по имени…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{
            fontSize: 11,
            padding: "4px 8px",
            border: "1px solid var(--border)",
            borderRadius: 4,
            background: "var(--bg-2, white)",
            color: "var(--text-1)",
            outline: "none",
          }}
        />
      )}

      {/* Дерево — растягивается на всю доступную высоту parent-flex */}
      <div className="mt-scroll" style={{
        flex: 1,
        minHeight: 0,
        overflowY: "auto",
        overflowX: "hidden",
        borderRadius: 4,
        background: "var(--bg-2, rgba(0,0,0,0.02))",
        padding: "4px 0 8px",  // нижний padding чтобы последний элемент не прилипал
      }}>
        {filteredTypes.length === 0 && state === "ready" && filter && (
          <div style={{ padding: "8px", fontSize: 11, color: "var(--text-4)", textAlign: "center" }}>
            Ничего не найдено по «{filter}»
          </div>
        )}
        {filteredTypes.map((t) => (
          <TreeNode key={t.id} node={t} depth={0} />
        ))}
      </div>
    </div>
  );
};

// Экспортируем в глобал, чтобы chat-screen.jsx мог использовать
window.MetadataTree = MetadataTree;
