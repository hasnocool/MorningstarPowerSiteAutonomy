from __future__ import annotations

DASHBOARD_SCRIPT_RUNTIME = r"""function renderLearning() {
  renderWorldModel();
  renderWeatherSkill();
  renderAdaptiveBattery();
  renderChangeEvidence();
}

function renderWorldModel() {
  const a = state.data.adaptive;
  const s = state.data.adaptiveScore;
  if (!a && !s) {
    byId("worldModel").innerHTML = empty("No Adaptive World snapshot exists yet.");
    return;
  }
  byId("worldModel").innerHTML = `
    <div class="kv-grid">
      ${kv("Champion", a?.champion_model || s?.champion_model || "baseline")}
      ${kv("Snapshot age", timeAgo(a?.generated_at))}
      ${kv("Seasonal cells", number(s?.seasonal_cells ?? 0))}
      ${kv("Load events discovered", number(s?.discovered_load_events ?? 0))}
      ${kv("Model promotions", number(s?.model_promotions ?? 0))}
      ${kv("Weather runs evaluated", number(s?.evaluated_weather_runs ?? 0))}
    </div>`;
}

function renderWeatherSkill() {
  const skill = state.data.weatherSkill;
  const items = skill?.skills || [];
  if (!items.length) {
    byId("weatherSkill").innerHTML = empty("Not enough retained weather outcomes to rank models.");
    return;
  }
  const sorted = [...items].sort((a, b) => Number(b.weight || 0) - Number(a.weight || 0));
  byId("weatherSkill").innerHTML = sorted.slice(0, 8).map(item => `
    <div class="learning-item">
      <div class="action-top">
        <span class="action-title">${escapeHtml(item.model)}</span>
        <span class="small muted">${escapeHtml(item.horizon_bucket)}</span>
      </div>
      <div class="small muted" style="margin-bottom:.42rem">
        Weight ${percent(item.weight, 0)} · MAE ${watts(item.pv_mae_w)} ·
        n=${number(item.sample_count)}
      </div>
      <div class="progress">
        <span style="width:${clamp((item.weight || 0) * 100, 0, 100)}%"></span>
      </div>
    </div>`).join("");
}

function renderAdaptiveBattery() {
  const b = state.data.adaptive?.battery;
  if (!b) {
    byId("adaptiveBattery").innerHTML = empty("Battery degradation evidence is not available yet.");
    return;
  }
  byId("adaptiveBattery").innerHTML = `
    <div class="kv-grid">
      ${kv("Health estimate", b.estimated_health_percent == null
        ? "Not enough evidence" : `${number(b.estimated_health_percent, 1)}%`)}
      ${kv("Observed throughput", energy(b.throughput_wh))}
      ${kv("Equivalent full cycles", number(b.equivalent_full_cycles, 1))}
      ${kv("Usable capacity", b.estimated_usable_capacity_wh == null
        ? "Not estimated" : energy(b.estimated_usable_capacity_wh))}
      ${kv("30d capacity change", b.capacity_change_percent_30d == null
        ? "Not enough evidence" : `${number(b.capacity_change_percent_30d, 1)}%`)}
      ${kv("Evidence samples", number(b.sample_count))}
    </div>`;
}

function renderChangeEvidence() {
  const changes = state.data.adaptive?.change_points || [];
  if (!changes.length) {
    byId("changeEvidence").innerHTML = empty("No recent high-value change evidence.");
    return;
  }
  const sorted = [...changes].sort((a, b) => Number(b.probability) - Number(a.probability));
  byId("changeEvidence").innerHTML = sorted.slice(0, 8).map(item => `
    <div class="learning-item">
      <div class="action-top">
        <span class="action-title">${escapeHtml(label(item.parameter))}</span>
        <span class="pill ${item.probability >= .95 ? "warn" : ""}">
          <span class="dot"></span>${percent(item.probability, 0)}
        </span>
      </div>
      <div class="small muted">
        ${escapeHtml(label(item.direction))} · standardized shift
        ${number(item.standardized_shift, 2)}
      </div>
    </div>`).join("");
}

function renderDiagnostics() {
  const h = state.data.health;
  if (!h) {
    byId("healthDetails").innerHTML = empty(state.errors.health || "Health endpoint unavailable.");
  } else {
    byId("healthDetails").innerHTML = `
      <div class="kv-grid">
        ${kv("Service", h.status || "unknown")}
        ${kv("Version", h.version || "—")}
        ${kv("Morningstar API", label(h.morningstar_api))}
        ${kv("Sentinel", h.sentinel_configured ? "Configured" : "Not configured")}
        ${kv("Shadow Autopilot", h.shadow_autopilot ? "Enabled" : "Disabled")}
        ${kv("Adaptive World", h.adaptive_world ? "Enabled" : "Disabled")}
      </div>`;
  }
  const freshness = [
    ["Forecast", state.data.forecast?.generated_at, state.errors.forecast],
    ["Shadow plan", latestPlan()?.generated_at, state.errors.plans],
    ["Adaptive world", state.data.adaptive?.generated_at, state.errors.adaptive],
    ["Adaptive scorecard", state.data.adaptiveScore?.generated_at, state.errors.adaptiveScore],
  ];
  byId("freshnessDetails").innerHTML = `<div class="learning-list">` +
    freshness.map(([name, stamp, error]) => `
      <div class="learning-item">
        <div class="action-top"><span class="action-title">${escapeHtml(name)}</span>
          <span class="small ${error ? "bad-text" : "muted"}">
            ${escapeHtml(error || timeAgo(stamp))}
          </span>
        </div>
      </div>`).join("") + `</div>`;
  renderRawInspector();
}

function renderRawInspector() {
  const select = byId("rawSelect");
  const keys = Object.keys(state.data);
  const current = select.value;
  select.innerHTML = keys.map(key => {
    return `<option value="${escapeHtml(key)}">${escapeHtml(label(key))}</option>`;
  }).join("");
  if (keys.includes(current)) select.value = current;
  const selected = select.value || keys[0];
  byId("rawOutput").textContent = selected
    ? JSON.stringify(state.data[selected], null, 2)
    : "No successful API responses to inspect.";
}

function setLoading(loading) {
  byId("refreshButton").disabled = loading;
  byId("refreshButton").textContent = loading ? "Loading…" : "Refresh ↻";
}

function showToast(message) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 3200);
}

async function runShadowCycle() {
  if (!state.site) return;
  const button = byId("runShadowButton");
  button.disabled = true;
  button.textContent = "Running…";
  try {
    const site = encodeURIComponent(state.site);
    await fetchJson(`/v1/sites/${site}/autopilot/tick`, { method: "POST" });
  } catch (error) {
    showToast(`Shadow cycle failed: ${error.message}`);
    button.disabled = false;
    button.textContent = "Run fresh shadow cycle";
    return;
  }
  showToast("Fresh shadow cycle completed. No hardware commands were executed.");
  await loadDashboard();
  button.disabled = false;
  button.textContent = "Run fresh shadow cycle";
}

function bindNavigation() {
  document.querySelectorAll(".nav-button").forEach(button => {
    button.addEventListener("click", () => {
      const view = button.dataset.view;
      document.querySelectorAll(".nav-button").forEach(item => item.classList.remove("active"));
      document.querySelectorAll(".view").forEach(item => item.classList.remove("active"));
      button.classList.add("active");
      byId(`view-${view}`).classList.add("active");
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
}

function bindEvents() {
  byId("siteSelect").addEventListener("change", async event => {
    state.site = event.target.value;
    localStorage.setItem("powersite-dashboard-site", state.site);
    await loadDashboard();
  });
  byId("refreshButton").addEventListener("click", loadDashboard);
  byId("runShadowButton").addEventListener("click", runShadowCycle);
  byId("rawSelect").addEventListener("change", renderRawInspector);
  byId("copyRawButton").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(byId("rawOutput").textContent);
      showToast("JSON copied to clipboard.");
    } catch (_) {
      showToast("Clipboard access is not available in this browser context.");
    }
  });
}

async function init() {
  bindNavigation();
  bindEvents();
  await loadSites();
  byId("siteSelect").value = state.site;
  await loadDashboard();
  state.refreshTimer = window.setInterval(() => {
    if (!document.hidden) loadDashboard();
  }, 60000);
}

init();"""
