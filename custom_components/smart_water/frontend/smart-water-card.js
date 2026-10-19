// Smart Water dashboard card. Loaded as a module from /smart_water_static/.
const CARD_TYPE = "smart-water-card";

class SmartWaterCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("smart-water-card-editor");
  }

  static getStubConfig() {
    return { entity: "", show_history: true };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Set the watering schedule entity, for example sensor.garden_watering_schedule.");
    }
    this._config = config;
    if (this._hass) {
      this._render();
    }
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 6;
  }

  _render() {
    if (!this._hass || !this._config) {
      return;
    }
    const root = this._root();
    const card = document.createElement("ha-card");
    const body = document.createElement("div");
    body.className = "sw-body";
    const state = this._hass.states[this._config.entity];
    if (!state) {
      body.append(this._note("Waiting for the watering schedule sensor."));
      card.append(body);
      root.append(card);
      return;
    }
    const model = this._model(state);
    if (!model) {
      body.append(this._markdown(state.attributes.markdown || "No schedule yet."));
      card.append(body);
      root.append(card);
      return;
    }
    body.append(this._hub(model, state));
    model.zones.forEach((zone) => body.append(this._zone(zone)));
    card.append(body);
    root.append(card);
  }

  _root() {
    if (!this.shadowRoot) {
      const root = this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = `
        :host { display: block; }
        ha-card { padding: 0; overflow: hidden; }
        .sw-body { padding: 12px; display: flex; flex-direction: column; gap: 12px; }
        .sw-hub, .sw-zone {
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 12px;
          padding: 12px;
          background: var(--card-background-color, transparent);
        }
        .sw-row { display: flex; justify-content: space-between; gap: 8px; align-items: center; flex-wrap: wrap; }
        .sw-title { font-weight: 600; font-size: 1.05rem; }
        .sw-muted { color: var(--secondary-text-color, #727272); font-size: 0.85rem; }
        .sw-stats { display: flex; gap: 12px; flex-wrap: wrap; font-size: 0.9rem; }
        .sw-bar { position: relative; height: 10px; border-radius: 999px; background: var(--divider-color, #e0e0e0); margin: 8px 0 4px; overflow: hidden; }
        .sw-fill { height: 100%; background: var(--primary-color, #03a9f4); border-radius: 999px; }
        .sw-tick { position: absolute; top: -2px; width: 2px; height: 14px; background: var(--primary-text-color, #212121); opacity: 0.45; }
        .sw-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
        button {
          border: 0; border-radius: 999px; padding: 6px 12px; cursor: pointer;
          background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff);
          font: inherit;
        }
        button.sw-quiet { background: var(--secondary-background-color, #f0f0f0); color: var(--primary-text-color, #212121); }
        .sw-alert { color: var(--error-color, #db4437); font-size: 0.9rem; }
        .sw-md { white-space: pre-wrap; font-size: 0.85rem; overflow-x: auto; }
        svg { width: 100%; height: 36px; display: block; margin-top: 6px; }
        @media (max-width: 500px) {
          .sw-actions button { flex: 1 1 auto; }
        }
      `;
      root.append(style);
    }
    const root = this.shadowRoot;
    [...root.children].forEach((child) => {
      if (child.tagName !== "STYLE") {
        child.remove();
      }
    });
    return root;
  }

  _model(schedule) {
    const hass = this._hass;
    const registry = hass.entities && hass.entities[this._config.entity];
    const devices = hass.devices;
    if (!registry || !registry.device_id || !devices) {
      return null;
    }
    const hubId = registry.device_id;
    const hubEntities = this._onDevice(hubId);
    const auto = this._byKey(hubEntities, "master_auto");
    const nowEntity = this._byKey(hubEntities, "watering_now");
    const use = this._byKey(hubEntities, "water_use");
    const saved = this._byKey(hubEntities, "water_saved");
    const zones = Object.values(devices)
      .filter((device) => device && device.via_device_id === hubId)
      .map((device) => this._zoneModel(device))
      .filter((zone) => zone);
    if (!zones.length) {
      return null;
    }
    const useState = use ? hass.states[use.entity_id] : null;
    const savedState = saved ? hass.states[saved.entity_id] : null;
    return {
      name: (devices[hubId] && (devices[hubId].name_by_user || devices[hubId].name)) || "Smart Water",
      auto: auto && auto.entity_id,
      automatic: auto ? hass.states[auto.entity_id] && hass.states[auto.entity_id].state === "on" : false,
      watering: nowEntity && hass.states[nowEntity.entity_id] ? hass.states[nowEntity.entity_id].state : "Idle",
      week: useState && useState.attributes ? useState.attributes.week_gal : schedule.attributes.week_gal,
      saved: savedState ? savedState.state : schedule.attributes.saved_gal,
      alerts: schedule.attributes.alerts || [],
      zones,
    };
  }

  _zoneModel(device) {
    const entities = this._onDevice(device.id);
    const deficit = this._byKey(entities, "deficit");
    const plan = this._byKey(entities, "zone_plan");
    const last = this._byKey(entities, "last_run");
    if (!deficit) {
      return null;
    }
    const hass = this._hass;
    const bucket = hass.states[deficit.entity_id];
    const planState = plan ? hass.states[plan.entity_id] : null;
    const lastState = last ? hass.states[last.entity_id] : null;
    const attrs = (bucket && bucket.attributes) || {};
    const planAttrs = (planState && planState.attributes) || {};
    const name = device.name_by_user || device.name || deficit.name || "Zone";
    return {
      name,
      full: Number(attrs.full_pct ?? this._full(attrs)),
      rawTick: this._rawTick(attrs),
      history: this._config.show_history === false ? [] : attrs.history || [],
      next: planAttrs.next_run || null,
      minutes: planAttrs.runtime_min,
      reason: planAttrs.reason || (planState && planState.state) || "",
      scheduled: planState && planState.state === "scheduled",
      last: lastState && lastState.attributes ? lastState.attributes : null,
      source: attrs.precip_source,
      rate: attrs.precipitation_rate_in_hr,
      preset: attrs.preset_precip_in_hr,
    };
  }

  _onDevice(deviceId) {
    return Object.values(this._hass.entities || {}).filter((entry) => entry.device_id === deviceId);
  }

  _byKey(entries, key) {
    return entries.find((entry) => entry.translation_key === key);
  }

  _full(attrs) {
    const taw = Number(attrs.taw_mm);
    const deficit = Number(attrs.deficit_mm ?? attrs.native_value);
    if (!taw) {
      return 100;
    }
    return Math.max(0, Math.min(100, (1 - deficit / taw) * 100));
  }

  _rawTick(attrs) {
    const taw = Number(attrs.taw_mm);
    const raw = Number(attrs.raw_mm);
    if (!taw || !raw) {
      return null;
    }
    return Math.max(0, Math.min(100, (1 - raw / taw) * 100));
  }

  _hub(model, schedule) {
    const box = document.createElement("div");
    box.className = "sw-hub";
    const row = document.createElement("div");
    row.className = "sw-row";
    const title = document.createElement("div");
    title.className = "sw-title";
    title.textContent = model.name;
    const toggle = document.createElement("button");
    toggle.textContent = model.automatic ? "Automatic on" : "Automatic off";
    toggle.className = model.automatic ? "" : "sw-quiet";
    toggle.addEventListener("click", () => {
      if (!model.auto) {
        return;
      }
      this._hass.callService("switch", model.automatic ? "turn_off" : "turn_on", {
        entity_id: model.auto,
      });
    });
    row.append(title, toggle);
    const stats = document.createElement("div");
    stats.className = "sw-stats";
    stats.append(
      this._stat("Now", model.watering || "Idle"),
      this._stat("This week", this._gal(model.week)),
      this._stat("Saved", this._gal(model.saved)),
    );
    box.append(row, stats);
    (model.alerts || []).forEach((alert) => {
      const line = document.createElement("div");
      line.className = "sw-alert";
      line.textContent = String(alert);
      box.append(line);
    });
    if (schedule.attributes && schedule.attributes.window) {
      const windowLine = document.createElement("div");
      windowLine.className = "sw-muted";
      windowLine.textContent = String(schedule.attributes.window);
      box.append(windowLine);
    }
    if (schedule.state) {
      const summary = document.createElement("div");
      summary.className = "sw-muted";
      summary.textContent = schedule.state;
      box.append(summary);
    }
    return box;
  }

  _zone(zone) {
    const box = document.createElement("div");
    box.className = "sw-zone";
    const row = document.createElement("div");
    row.className = "sw-row";
    const title = document.createElement("div");
    title.className = "sw-title";
    title.textContent = zone.name;
    const pct = document.createElement("div");
    pct.className = "sw-muted";
    pct.textContent = `Soil water ${Math.round(zone.full)}%`;
    row.append(title, pct);
    const bar = document.createElement("div");
    bar.className = "sw-bar";
    const fill = document.createElement("div");
    fill.className = "sw-fill";
    fill.style.width = `${Math.max(0, Math.min(100, zone.full))}%`;
    bar.append(fill);
    if (zone.rawTick != null) {
      const tick = document.createElement("div");
      tick.className = "sw-tick";
      tick.style.left = `${zone.rawTick}%`;
      tick.title = "Watering point";
      bar.append(tick);
    }
    const detail = document.createElement("div");
    detail.className = "sw-muted";
    const next = zone.scheduled
      ? `Next ${this._when(zone.next)} · ${zone.minutes} min`
      : zone.reason || "Not scheduled";
    const last = zone.last && zone.last.at
      ? `Last ${this._when(zone.last.at)} · ${zone.last.minutes} min`
      : "No run yet";
    detail.textContent = `${next}. ${last}.`;
    box.append(row, bar, detail);
    if (zone.source === "measured" && zone.rate != null) {
      const measured = document.createElement("div");
      measured.className = "sw-muted";
      const preset = zone.preset == null ? "" : ` (preset ${zone.preset} in/hr)`;
      measured.textContent = `Measured ${zone.rate} in/hr${preset}`;
      box.append(measured);
    }
    if (this._config.show_history !== false) {
      box.append(this._spark(zone.history));
    }
    const actions = document.createElement("div");
    actions.className = "sw-actions";
    actions.append(
      this._button("Run now", () => this._call("run_now", { zone: zone.name })),
      this._button("Skip", () => this._call("skip_zone", { zone: zone.name }), true),
      this._button("Pause 3 days", () => this._call("pause_zone", { zone: zone.name, days: 3 }), true),
    );
    box.append(actions);
    return box;
  }

  _spark(history) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 100 36");
    svg.setAttribute("preserveAspectRatio", "none");
    const points = (history || []).slice(-7);
    if (points.length < 2) {
      return svg;
    }
    const step = 100 / (points.length - 1);
    const coords = points.map((point, index) => {
      const y = 34 - (Number(point.full_pct) / 100) * 32;
      return `${(index * step).toFixed(1)},${y.toFixed(1)}`;
    });
    const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    poly.setAttribute("fill", "none");
    poly.setAttribute("stroke", "var(--primary-color, #03a9f4)");
    poly.setAttribute("stroke-width", "2");
    poly.setAttribute("points", coords.join(" "));
    svg.append(poly);
    return svg;
  }

  _button(label, action, quiet) {
    const button = document.createElement("button");
    button.textContent = label;
    if (quiet) {
      button.className = "sw-quiet";
    }
    button.addEventListener("click", action);
    return button;
  }

  _call(service, data) {
    this._hass.callService("smart_water", service, data);
  }

  _stat(label, value) {
    const span = document.createElement("span");
    span.textContent = `${label}: ${value}`;
    return span;
  }

  _gal(value) {
    if (value == null || value === "unknown" || value === "unavailable" || value === "") {
      return "—";
    }
    const number = Number(value);
    if (Number.isNaN(number)) {
      return "—";
    }
    return `${Math.round(number)} gal`;
  }

  _when(value) {
    if (!value) {
      return "—";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    return date.toLocaleString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  _note(text) {
    const div = document.createElement("div");
    div.className = "sw-muted";
    div.textContent = text;
    return div;
  }

  _markdown(text) {
    const pre = document.createElement("pre");
    pre.className = "sw-md";
    pre.textContent = text;
    return pre;
  }
}

class SmartWaterCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { show_history: true, ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) {
      return;
    }
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    const root = this.shadowRoot;
    root.replaceChildren();
    const wrap = document.createElement("div");
    wrap.style.display = "flex";
    wrap.style.flexDirection = "column";
    wrap.style.gap = "12px";
    wrap.style.padding = "8px 0";
    const label = document.createElement("label");
    label.textContent = "Watering schedule";
    const select = document.createElement("select");
    Object.values(this._hass.states)
      .filter((state) => state.entity_id.includes("watering_schedule"))
      .forEach((state) => {
        const option = document.createElement("option");
        option.value = state.entity_id;
        option.textContent = state.attributes.friendly_name || state.entity_id;
        if (state.entity_id === this._config.entity) {
          option.selected = true;
        }
        select.append(option);
      });
    if (this._config.entity && !select.value) {
      const option = document.createElement("option");
      option.value = this._config.entity;
      option.textContent = this._config.entity;
      option.selected = true;
      select.append(option);
    }
    select.addEventListener("change", () => {
      this._dispatch({ ...this._config, entity: select.value });
    });
    const history = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = this._config.show_history !== false;
    checkbox.addEventListener("change", () => {
      this._dispatch({ ...this._config, entity: select.value || this._config.entity, show_history: checkbox.checked });
    });
    history.append(checkbox, document.createTextNode(" Show 7-day soil chart"));
    wrap.append(label, select, history);
    root.append(wrap);
  }

  _dispatch(config) {
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }
}

customElements.define(CARD_TYPE, SmartWaterCard);
customElements.define("smart-water-card-editor", SmartWaterCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TYPE,
  name: "Smart Water",
  description: "Soil level, next run, and watering controls for each zone.",
  preview: true,
});
