// Ropam Neo - zakładka diagnostyki dla Home Assistant
const REFRESH_MS = 2000;

const KIND_COLORS = {
  TX: "var(--primary-color, #03a9f4)",
  RX: "var(--success-color, #43a047)",
  INFO: "var(--secondary-text-color, #888)",
  ERR: "var(--error-color, #db4437)",
};

function fmtTime(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const p = (n, l = 2) => String(n).padStart(l, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

function fmtDate(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

class RopamNeoPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._narrow = false;
    this._data = null;
    this._selected = null;
    this._paused = false;
    this._timer = null;
    this._built = false;
    this._last = {};
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first) this._refresh();
  }

  set narrow(v) {
    this._narrow = v;
    if (this._menu) this._menu.narrow = v;
  }

  set panel(_p) {}

  connectedCallback() {
    this._build();
    this._timer = setInterval(() => {
      if (!this._paused) this._refresh();
    }, REFRESH_MS);
    this._refresh();
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
  }

  _build() {
    if (this._built) return;
    this._built = true;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; height:100%; background:var(--primary-background-color); color:var(--primary-text-color); font-family:var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
        .toolbar { display:flex; align-items:center; height:56px; padding:0 12px; background:var(--app-header-background-color, var(--primary-color)); color:var(--app-header-text-color, #fff); gap:8px; }
        .toolbar h1 { font-size:20px; font-weight:400; margin:0; flex:1; }
        .content { padding:16px; max-width:1200px; margin:0 auto; box-sizing:border-box; }
        .card { background:var(--card-background-color, #fff); border-radius:var(--ha-card-border-radius, 12px); box-shadow:var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,.1)); padding:16px; margin-bottom:16px; }
        .card h2 { font-size:16px; margin:0 0 12px; font-weight:500; display:flex; align-items:center; gap:8px; }
        .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(220px,1fr)); gap:8px 16px; }
        .kv { font-size:14px; }
        .kv b { display:block; font-size:12px; font-weight:400; color:var(--secondary-text-color); }
        .dot { width:12px; height:12px; border-radius:50%; display:inline-block; }
        .ok { background:var(--success-color, #43a047); }
        .bad { background:var(--error-color, #db4437); }
        .buttons { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
        button { font:inherit; font-size:14px; border:none; border-radius:8px; padding:8px 14px; cursor:pointer; background:var(--primary-color); color:var(--text-primary-color, #fff); }
        button.sec { background:var(--secondary-background-color, #e0e0e0); color:var(--primary-text-color); }
        button:active { opacity:.8; }
        select { font:inherit; padding:6px; border-radius:6px; }
        pre { font-family:var(--code-font-family, monospace); font-size:12px; white-space:pre-wrap; word-break:break-all; margin:0; max-height:260px; overflow:auto; background:var(--secondary-background-color, #f5f5f5); padding:8px; border-radius:6px; user-select:text; }
        .log { max-height:520px; overflow:auto; font-family:var(--code-font-family, monospace); font-size:12px; background:var(--secondary-background-color, #f5f5f5); border-radius:6px; padding:6px 8px; user-select:text; }
        .log div { padding:1px 0; border-bottom:1px solid rgba(127,127,127,.12); word-break:break-all; }
        .log .t { color:var(--secondary-text-color); margin-right:6px; }
        .log .k { font-weight:600; margin-right:6px; display:inline-block; min-width:34px; }
        .toast { position:fixed; bottom:24px; left:50%; transform:translateX(-50%); background:#323232; color:#fff; padding:10px 18px; border-radius:8px; font-size:14px; opacity:0; transition:opacity .2s; pointer-events:none; z-index:10; }
        .toast.show { opacity:1; }
        .muted { color:var(--secondary-text-color); font-size:13px; }
        .chars { font-family:var(--code-font-family, monospace); letter-spacing:2px; }
      </style>
      <div class="toolbar"><span id="menu"></span><h1>Ropam Neo — diagnostyka</h1><span id="ver" class="muted" style="color:inherit;opacity:.8"></span></div>
      <div class="content">
        <div class="buttons">
          <select id="entry" style="display:none"></select>
          <button id="copyAll">Kopiuj wszystko</button>
          <button id="copyLog" class="sec">Kopiuj log</button>
          <button id="pause" class="sec">Wstrzymaj odświeżanie</button>
          <button id="clear" class="sec">Wyczyść log</button>
          <button id="reload" class="sec">Połącz ponownie</button>
        </div>
        <div id="empty" class="card" style="display:none">Brak skonfigurowanej centrali.</div>
        <div id="main">
          <div class="card"><h2><span id="dot" class="dot bad"></span><span id="connText">—</span></h2><div class="grid" id="info"></div></div>
          <div class="card"><h2>Ostatni błąd / komunikat</h2><pre id="errors">—</pre></div>
          <div class="card"><h2>Wejścia / wyjścia (znaki ze statusu)</h2><pre id="chars">—</pre></div>
          <div class="card"><h2>Surowy status</h2><pre id="raw">—</pre></div>
          <div class="card"><h2>Status sparsowany</h2><pre id="parsed">—</pre></div>
          <div class="card"><h2>Konfiguracja z centrali</h2><pre id="config">—</pre></div>
          <div class="card"><h2>Log ramek <span class="muted" id="logCount"></span></h2><div class="log" id="log"></div></div>
        </div>
      </div>
      <div class="toast" id="toast"></div>`;
    const $ = (id) => this.shadowRoot.getElementById(id);
    this.$ = $;
    try {
      const menu = document.createElement("ha-menu-button");
      menu.hass = this._hass;
      menu.narrow = this._narrow;
      $("menu").appendChild(menu);
      this._menu = menu;
    } catch (e) { /* brak elementu - pomijamy */ }
    $("copyAll").addEventListener("click", () => this._copy(this._allText(), "Skopiowano całą diagnostykę"));
    $("copyLog").addEventListener("click", () => this._copy(this._logText(), "Skopiowano log"));
    $("pause").addEventListener("click", () => {
      this._paused = !this._paused;
      $("pause").textContent = this._paused ? "Wznów odświeżanie" : "Wstrzymaj odświeżanie";
      if (!this._paused) this._refresh();
    });
    $("clear").addEventListener("click", async () => {
      const e = this._entry();
      if (!e) return;
      await this._hass.callWS({ type: "ropam_neo/clear_log", entry_id: e.entry_id });
      this._refresh();
    });
    $("reload").addEventListener("click", async () => {
      const e = this._entry();
      if (!e) return;
      await this._hass.callWS({ type: "ropam_neo/reload", entry_id: e.entry_id });
      this._toast("Przeładowuję integrację…");
    });
    $("entry").addEventListener("change", (ev) => {
      this._selected = ev.target.value;
      this._last = {};
      this._render();
    });
  }

  async _refresh() {
    if (!this._hass || !this._built) return;
    try {
      this._data = await this._hass.callWS({ type: "ropam_neo/diagnostics" });
    } catch (err) {
      this._data = { error: String(err && err.message ? err.message : err), entries: [] };
    }
    this._render();
  }

  _entry() {
    const list = (this._data && this._data.entries) || [];
    if (!list.length) return null;
    return list.find((e) => e.entry_id === this._selected) || list[0];
  }

  _set(id, text) {
    if (this._last[id] === text) return;
    this._last[id] = text;
    this.$(id).textContent = text;
  }

  _render() {
    const $ = this.$;
    const data = this._data || { entries: [] };
    $("ver").textContent = data.version ? `v${data.version}` : "";
    const list = data.entries || [];
    $("empty").style.display = list.length ? "none" : "block";
    $("main").style.display = list.length ? "block" : "none";
    const sel = $("entry");
    sel.style.display = list.length > 1 ? "inline-block" : "none";
    const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
    const opts = list.map((e) => `<option value="${esc(e.entry_id)}">${esc(e.title)}</option>`).join("");
    if (sel.innerHTML !== opts) sel.innerHTML = opts;
    const e = this._entry();
    if (!e) return;
    sel.value = e.entry_id;

    $("dot").className = "dot " + (e.connected ? "ok" : "bad");
    this._set("connText", e.connected ? "Połączono z centralą" : `Brak połączenia (stan wpisu: ${e.entry_state})`);
    const st = e.status || {};
    const login = e.login || {};
    const info = [
      ["Adres", `${e.host || "—"}:${e.port || "—"}`],
      ["ID centrali", e.device_id || "—"],
      ["Sprzęt / firmware", `${st.hardware || "—"} / ${st.firmware || "—"}`],
      ["Czas w centrali", st.module_time || "—"],
      ["Ostatnia ramka", fmtDate(e.last_frame)],
      ["Liczba połączeń", e.connects ?? "—"],
      ["Użytkownik", login.user_no != null ? `nr ${login.user_no}` : "—"],
      ["Uprawnienia", login.user_no != null ? `S1:${login.zone1 ? "tak" : "nie"} S2:${login.zone2 ? "tak" : "nie"} zdalnie:${login.remote ? "tak" : "nie"}` : "—"],
      ["Zasilanie AC", st.ac_ok == null ? "—" : st.ac_ok ? "OK" : "BRAK"],
      ["Napięcie", st.supply_voltage != null ? `${st.supply_voltage} V` : "—"],
      ["Tryb", st.device_mode || "—"],
      ["Błąd parsera", st.parse_error || "brak"],
    ];
    const infoHtml = info.map(([k, v]) => `<div class="kv"><b>${k}</b>${String(v).replace(/</g, "&lt;")}</div>`).join("");
    if (this._last.info !== infoHtml) {
      this._last.info = infoHtml;
      $("info").innerHTML = infoHtml;
    }
    this._set("errors", `Błąd: ${e.last_error || "brak"}\nKomunikat: ${e.last_message || "brak"}${data.error ? "\nWS: " + data.error : ""}`);
    const idx = Array.from({ length: 32 }, (_, i) => String((i + 1) % 10)).join("");
    this._set("chars", st.inputs || st.outputs
      ? `nr:      ${idx}\nwejścia: ${st.inputs || ""}\nwyjścia: ${st.outputs || ""}\nstrefy:  ${(st.zones || []).map((z, i) => `S${i + 1}=0x${(z.raw || 0).toString(16).padStart(2, "0")}${z.armed ? " uzbr" : ""}${z.night ? " noc" : ""}${z.alarm ? " ALARM" : ""}`).join("  ")}`
      : "—");
    this._set("raw", e.status_raw || "—");
    this._set("parsed", e.status ? JSON.stringify(e.status, null, 2) : "—");
    this._set("config", e.config ? JSON.stringify(e.config, null, 2) : "—");

    const log = e.log || [];
    $("logCount").textContent = `(${log.length})`;
    const key = log.length ? `${log.length}-${log[log.length - 1].ts}` : "0";
    if (this._last.log !== key) {
      this._last.log = key;
      const box = $("log");
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
      box.innerHTML = log
        .map((l) => `<div><span class="t">${fmtTime(l.ts)}</span><span class="k" style="color:${KIND_COLORS[l.kind] || "inherit"}">${l.kind}</span>${String(l.text).replace(/&/g, "&amp;").replace(/</g, "&lt;")}</div>`)
        .join("");
      if (atBottom) box.scrollTop = box.scrollHeight;
    }
  }

  _logText() {
    const e = this._entry();
    if (!e) return "";
    return (e.log || []).map((l) => `${fmtTime(l.ts)} ${l.kind.padEnd(4)} ${l.text}`).join("\n");
  }

  _allText() {
    const e = this._entry();
    if (!e) return "Brak danych";
    const copy = Object.assign({}, e);
    delete copy.log;
    return [
      `Ropam Neo diagnostyka v${(this._data && this._data.version) || "?"} — ${new Date().toLocaleString()}`,
      "",
      "=== STAN ===",
      JSON.stringify(copy, null, 2),
      "",
      "=== LOG ===",
      this._logText(),
    ].join("\n");
  }

  async _copy(text, okMsg) {
    let ok = false;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        ok = true;
      }
    } catch (e) { ok = false; }
    if (!ok) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      this.shadowRoot.appendChild(ta);
      ta.focus();
      ta.select();
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      ta.remove();
    }
    this._toast(ok ? okMsg : "Nie udało się skopiować - zaznacz tekst ręcznie");
  }

  _toast(msg) {
    const t = this.$("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
  }
}

if (!customElements.get("ropam-neo-panel")) {
  customElements.define("ropam-neo-panel", RopamNeoPanel);
}
