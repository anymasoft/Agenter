"use strict";

/**
 * desktop-connect.js
 * Перехватывает Alt+F4 → скрывает окно в трей вместо закрытия.
 * Вся логика статуса, логов и кнопок теперь в React-компонентах (desktop-screens.jsx).
 */

function interceptClose() {
  window.addEventListener("keydown", (e) => {
    if (e.altKey && e.key === "F4") {
      e.preventDefault();
      try { window.pywebview.api.hide_window(); } catch (_) {}
    }
  });
}

if (window.pywebview) {
  interceptClose();
} else {
  window.addEventListener("pywebviewready", interceptClose);
}
