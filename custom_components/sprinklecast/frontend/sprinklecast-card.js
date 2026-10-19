// Sprinklecast dashboard card. Loaded as a module from /sprinklecast_static/.
const CARD_TYPE = "sprinklecast-card";
const COLORS = [
  "#3FA34D",
  "#0E7FB8",
  "#E07A5F",
  "#7B6CC7",
  "#E3A008",
  "#2A9D8F",
  "#C44569",
  "#4C6EF5",
];

class SmartWaterCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("sprinklecast-card-editor");
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
    if (model) {
      body.append(this._hub(model, state));
    }
    body.append(this._scheduleBody(state));
    if (model) {
      model.zones.forEach((zone) => body.append(this._zone(zone)));
    }
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
        .sw-days { display: flex; flex-direction: column; gap: 8px; }
        .sw-strip {
          display: flex; gap: 4px; overflow-x: auto; padding: 2px 2px 8px;
          scrollbar-width: thin;
        }
        .sw-chip {
          flex: 1 0 48px; border: 0; background: transparent; color: inherit;
          display: flex; flex-direction: column; align-items: center; gap: 2px;
          padding: 4px 0; border-radius: 12px; min-width: 44px;
        }
        .sw-chip-name { font-size: 0.72rem; color: var(--secondary-text-color, #727272); text-transform: capitalize; }
        .sw-chip-num {
          width: 36px; height: 36px; border-radius: 999px;
          display: grid; place-items: center; font-weight: 650;
        }
        .sw-chip.sw-water .sw-chip-num { box-shadow: inset 0 0 0 2px var(--primary-color, #0E7FB8); }
        .sw-chip.sw-on { background: transparent; }
        .sw-chip.sw-on .sw-chip-num {
          background: var(--primary-color, #0E7FB8); color: var(--text-primary-color, #fff);
          box-shadow: none;
        }
        .sw-dot { width: 5px; height: 5px; border-radius: 999px; background: var(--primary-color, #0E7FB8); }
        .sw-chip.sw-on .sw-dot { background: var(--primary-color, #0E7FB8); }
        .sw-run {
          display: grid; grid-template-columns: 28px 1fr; gap: 8px; align-items: center;
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e8e8e8);
          border-left-width: 5px; border-radius: 12px; padding: 10px 12px;
        }
        .sw-when { font-weight: 650; font-size: 1rem; line-height: 1.2; }
        .sw-zone-line { margin-top: 2px; font-size: 0.95rem; }
        .sw-burst { color: var(--secondary-text-color, #727272); font-size: 0.82rem; margin-top: 2px; }
        ha-icon, .sw-glyph { width: 22px; height: 22px; }
        svg { width: 100%; height: 36px; display: block; margin-top: 6px; }
        @media (max-width: 500px) {
          .sw-body { padding: 8px; }
          .sw-chip { flex-basis: 40px; min-width: 40px; }
          .sw-when { font-size: 0.95rem; }
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
    const nextEntity = this._byKey(hubEntities, "schedule");
    const nextState = nextEntity ? hass.states[nextEntity.entity_id] : null;
    return {
      name: (devices[hubId] && (devices[hubId].name_by_user || devices[hubId].name)) || "Sprinklecast",
      auto: auto && auto.entity_id,
      automatic: auto ? hass.states[auto.entity_id] && hass.states[auto.entity_id].state === "on" : false,
      watering: nowEntity && hass.states[nowEntity.entity_id] ? hass.states[nowEntity.entity_id].state : "Idle",
      next: nextState ? nextState.state : null,
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
      id: device.id,
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
    const stateText = this._stateText(schedule);
    if (stateText) {
      box.append(this._note(stateText));
    }
    return box;
  }

  _stateText(schedule) {
    const text = schedule && schedule.state ? String(schedule.state) : "";
    if (!text || text === "unknown" || text === "unavailable") {
      return "";
    }
    return text;
  }

  _scheduleBody(state) {
    const wrap = document.createElement("div");
    wrap.className = "sw-days";
    const days = (state.attributes && state.attributes.days) || [];
    if (!days.length) {
      wrap.append(this._markdown((state.attributes && state.attributes.markdown) || "No schedule yet."));
      return wrap;
    }
    if (this._dayIndex == null || this._dayIndex >= days.length) {
      this._dayIndex = 0;
    }
    wrap.append(this._strip(days));
    this._appendDay(wrap, days[this._dayIndex]);
    return wrap;
  }

  _strip(days) {
    const strip = document.createElement("div");
    strip.className = "sw-strip";
    days.forEach((day, index) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "sw-chip sw-water" + (index === this._dayIndex ? " sw-on" : "");
      const name = document.createElement("div");
      name.className = "sw-chip-name";
      name.textContent = this._weekday(day);
      const num = document.createElement("div");
      num.className = "sw-chip-num";
      num.textContent = this._monthDay(day);
      const dot = document.createElement("div");
      dot.className = "sw-dot";
      chip.append(name, num, dot);
      chip.addEventListener("click", () => {
        this._dayIndex = index;
        this._render();
      });
      strip.append(chip);
    });
    return strip;
  }

  _appendDay(wrap, day) {
    if (day.finish_at || day.start_at) {
      const heading = document.createElement("div");
      heading.className = "sw-muted";
      const start = day.start_at ? this._exact(day.start_at) : "";
      const finish = day.finish_at ? this._clock(day.finish_at) : "";
      heading.textContent = finish ? `${start} – ${finish}` : start;
      wrap.append(heading);
    }
    const rows = [];
    (day.zones || []).forEach((zone) => {
      if (zone.scheduled === false) {
        return;
      }
      (zone.bursts || []).forEach((burst) => {
        rows.push({ zone, burst });
      });
    });
    rows.sort((left, right) => String(left.burst.start_at || left.burst.start).localeCompare(
      String(right.burst.start_at || right.burst.start),
    ));
    if (!rows.length) {
      wrap.append(this._note("Nothing scheduled this morning."));
      return;
    }
    rows.forEach(({ zone, burst }) => wrap.append(this._run(zone, burst)));
  }

  _run(zone, burst) {
    const row = document.createElement("div");
    row.className = "sw-run";
    row.style.borderLeftColor = this._color(zone.zone_id || zone.name);
    row.append(this._weather(zone));
    const text = document.createElement("div");
    const when = document.createElement("div");
    when.className = "sw-when";
    when.textContent = this._span(burst);
    const line = document.createElement("div");
    line.className = "sw-zone-line";
    line.textContent = zone.name || "Zone";
    const meta = document.createElement("div");
    meta.className = "sw-burst";
    meta.textContent = this._meta(zone, burst);
    text.append(when, line, meta);
    row.append(text);
    return row;
  }

  _meta(zone, burst) {
    const parts = [`${this._minutes(burst.minutes)} min`];
    const inches = burst.inches != null ? burst.inches : zone.inches;
    if (inches != null && inches !== "") {
      parts.push(`${Number(inches).toFixed(2)} in`);
    }
    if (zone.gallons != null && zone.gallons !== "") {
      parts.push(`${Math.round(Number(zone.gallons))} gal`);
    }
    const soak = Number(burst.soak_min || zone.soak_min || 0);
    if (soak) {
      parts.push(`soak ${soak} min`);
    }
    const cycle = burst.cycle && burst.of ? `cycle ${burst.cycle} of ${burst.of}` : "";
    if (cycle) {
      parts.push(cycle);
    }
    return parts.join(" · ");
  }

  _span(burst) {
    const start = burst.start_at ? this._ampm(burst.start_at) : String(burst.start || "");
    const end = burst.end_at ? this._ampm(burst.end_at) : String(burst.end || "");
    if (start && end) {
      return `${start} - ${end}`;
    }
    return start || end;
  }

  _weather(zone) {
    const reason = String(zone.reason || "").toLowerCase();
    let icon = "mdi:weather-partly-cloudy";
    if (reason.includes("rain")) {
      icon = "mdi:weather-rainy";
    } else if (reason.includes("wind")) {
      icon = "mdi:weather-windy";
    } else if (reason.includes("freeze") || reason.includes("°f")) {
      icon = "mdi:snowflake";
    } else if (reason.includes("moisture")) {
      icon = "mdi:water-percent";
    }
    const holder = document.createElement("div");
    if (customElements.get("ha-icon")) {
      const graphic = document.createElement("ha-icon");
      graphic.icon = icon;
      holder.append(graphic);
      return holder;
    }
    holder.className = "sw-glyph";
    holder.textContent = reason.includes("rain") ? "🌧" : "⛅";
    return holder;
  }

  _color(key) {
    const text = String(key || "");
    let hash = 0;
    for (let index = 0; index < text.length; index += 1) {
      hash = (hash * 33 + text.charCodeAt(index)) >>> 0;
    }
    return COLORS[hash % COLORS.length];
  }

  _weekday(day) {
    const value = day.start_at || (day.date ? `${day.date}T12:00:00` : "");
    return this._part(value, "weekday") || String(day.date || "");
  }

  _monthDay(day) {
    const value = day.start_at || (day.date ? `${day.date}T12:00:00` : "");
    return this._part(value, "day") || "";
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
    const when = zone.next ? this._exact(zone.next) : "";
    let next = zone.reason || "Not scheduled";
    if (when && zone.scheduled) {
      next = `Next ${when} · ${zone.minutes} min`;
    } else if (when) {
      next = `Next ${when}`;
    }
    const last = zone.last && zone.last.at
      ? `Last ${this._exact(zone.last.at)} · ${zone.last.minutes} min`
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
    this._hass.callService("sprinklecast", service, data);
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

  _parts(value, timeOnly) {
    if (!value) {
      return null;
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return null;
    }
    const timeZone = this._hass && this._hass.config && this._hass.config.time_zone;
    const options = {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    };
    if (!timeOnly) {
      options.weekday = "short";
      options.month = "short";
      options.day = "numeric";
    }
    let parts;
    try {
      parts = new Intl.DateTimeFormat("en-US", {
        ...options,
        timeZone: timeZone || undefined,
      }).formatToParts(date);
    } catch (_err) {
      parts = new Intl.DateTimeFormat("en-US", options).formatToParts(date);
    }
    return parts;
  }

  _part(value, type) {
    const parts = this._parts(value, false);
    if (!parts) {
      return "";
    }
    const found = parts.find((item) => item.type === type);
    return found ? found.value : "";
  }

  _exact(value) {
    const parts = this._parts(value, false);
    if (!parts) {
      return value ? String(value) : "—";
    }
    const part = (type) => {
      const found = parts.find((item) => item.type === type);
      return found ? found.value : "";
    };
    return `${part("weekday")} ${part("month")} ${part("day")}, ${part("hour")}:${part("minute")} ${part("dayPeriod")}`;
  }

  _clock(value) {
    return this._ampm(value);
  }

  _ampm(value) {
    const parts = this._parts(value, true);
    if (!parts) {
      return value ? String(value) : "";
    }
    const part = (type) => {
      const found = parts.find((item) => item.type === type);
      return found ? found.value : "";
    };
    const period = part("dayPeriod").toLowerCase().replace(/\s/g, "");
    return `${part("hour")}:${part("minute")} ${period}`;
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

if (!customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, SmartWaterCard);
}
if (!customElements.get("smart-water-card")) {
  customElements.define("smart-water-card", SmartWaterCard);
}
if (!customElements.get("sprinklecast-card-editor")) {
  customElements.define("sprinklecast-card-editor", SmartWaterCardEditor);
}
if (!customElements.get("smart-water-card-editor")) {
  customElements.define("smart-water-card-editor", SmartWaterCardEditor);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TYPE,
  name: "Sprinklecast",
  description: "Upcoming watering days and each zone run, with soil level and controls.",
  preview: true,
});
window.customCards.push({
  type: "smart-water-card",
  name: "Sprinklecast",
  description: "Upcoming watering days and each zone run, with soil level and controls.",
  preview: false,
});
