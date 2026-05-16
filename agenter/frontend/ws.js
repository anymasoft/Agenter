"use strict";

const AgenterWS = (() => {
  const WS_URL = "ws://localhost:8080/ws/events";
  let ws = null;
  let reconnectDelay = 3000;
  const listeners = {};

  function on(eventType, fn) {
    listeners[eventType] = fn;
  }

  function _emit(type, data) {
    if (listeners[type]) {
      try { listeners[type](data); } catch (e) { console.error("[AgenterWS] handler error:", e); }
    }
  }

  function connect() {
    if (ws && ws.readyState <= WebSocket.OPEN) return;

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log("[AgenterWS] Connected");
      reconnectDelay = 3000;
      _emit("connected", {});
    };

    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      _emit(msg.type, msg);
    };

    ws.onclose = () => {
      console.log(`[AgenterWS] Closed, retry in ${reconnectDelay}ms`);
      _emit("disconnected", {});
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.5, 30000);
    };

    ws.onerror = () => ws.close();
  }

  return { connect, on };
})();

window.AgenterWS = AgenterWS;
