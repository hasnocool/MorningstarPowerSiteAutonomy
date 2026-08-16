from __future__ import annotations

DASHBOARD_SCRIPT_CORE = r"""const state = {
  site: null,
  sites: [],
  data: {},
  errors: {},
  refreshTimer: null,
};

const endpoints = {
  health: () => "/health",
  forecast: site => `/v1/sites/${site}/forecast?hours=72`,
  twin: site => `/v1/sites/${site}/digital-twin`,
  actions: site => `/v1/sites/${site}/action-plan?hours=72`,
  policy: site => `/v1/sites/${site}/autopilot/policy`,
  plans: site => `/v1/sites/${site}/autopilot/plans?limit=1`,
  shadowActions: site => `/v1/sites/${site}/autopilot/actions?limit=20`,
  autopilotScore: site => `/v1/sites/${site}/autopilot/scorecard?limit=200`,
  adaptive: site => `/v1/sites/${site}/adaptive/snapshot`,
  adaptiveScore: site => `/v1/sites/${site}/adaptive/scorecard`,
  weatherSkill: site => `/v1/sites/${site}/adaptive/weather/skill`,
  policyLab: site => `/v1/sites/${site}/adaptive/policy-lab/snapshot`,
  policyReserve: site => `/v1/sites/${site}/adaptive/policy-lab/dynamic-reserve`,
};

function byId(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number(value) || 0));
}

function number(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function watts(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (Math.abs(n) >= 1000) return `${number(n / 1000, 2)} kW`;
  return `${number(n, 0)} W`;
}

function energy(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (Math.abs(n) >= 1000) return `${number(n / 1000, 2)} kWh`;
  return `${number(n, 0)} Wh`;
}

function percent(value, digits = 0) {
  if (value === null || value === undefined) return "—";
  return `${number(Number(value) * (Number(value) <= 1 ? 100 : 1), digits)}%`;
}

function timeAgo(value) {
  if (!value) return "unknown";
  const t = new Date(value).getTime();
  if (!Number.isFinite(t)) return "unknown";
  const seconds = Math.max(0, (Date.now() - t) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}


function timeUntil(value) {
  if (!value) return "unknown";
  const t = new Date(value).getTime();
  if (!Number.isFinite(t)) return "unknown";
  const seconds = (t - Date.now()) / 1000;
  if (seconds <= 0) return "now or earlier";
  if (seconds < 3600) return `in ${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `in ${Math.round(seconds / 3600)} h`;
  return `in ${Math.round(seconds / 86400)} d`;
}

function label(value) {
  return String(value ?? "unknown")
    .replaceAll("_", " ")
    .replace(/\\b\\w/g, c => c.toUpperCase());
}

function empty(message) {
  return `<div class="empty">${escapeHtml(message)}</div>`;
}

function kv(labelText, valueText) {
  return `<div class="kv"><div class="kv-label">${escapeHtml(labelText)}</div>` +
    `<div class="kv-value">${escapeHtml(valueText)}</div></div>`;
}

function metricCard(title, value, detail, tone = "") {
  const toneClass = tone ? `${tone}-text` : "";
  return `<article class="card metric">` +
    `<div class="metric-label">${escapeHtml(title)}</div>` +
    `<div class="metric-value ${toneClass}">${escapeHtml(value)}</div>` +
    `<div class="metric-detail">${escapeHtml(detail)}</div>` +
    `</article>`;
}

function riskTone(risk) {
  const value = Number(risk);
  if (!Number.isFinite(value)) return "";
  if (value < 0.02) return "good";
  if (value < 0.10) return "warn";
  return "bad";
}

function confidenceTone(value) {
  if (value === "high") return "good";
  if (value === "medium") return "warn";
  return "bad";
}

async function fetchJson(url, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  const response = await fetch(url, { ...options, headers });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload?.detail || `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }
  return payload;
}

async function loadSites() {
  try {
    const sites = await fetchJson("/v1/sites");
    state.sites = Array.isArray(sites) ? sites : [];
  } catch (error) {
    state.sites = [];
    showToast(`Could not load sites: ${error.message}`);
  }
  const select = byId("siteSelect");
  const configured = state.sites.filter(item => item.autonomy_configured !== false);
  const options = configured.length ? configured : state.sites;
  if (!options.length) {
    select.innerHTML = `<option value="sys_default">sys_default</option>`;
    state.site = "sys_default";
    return;
  }
  select.innerHTML = options.map(item => {
    const uid = item.site_uid || item.uid || item.id;
    const name = item.name ? `${item.name} · ${uid}` : uid;
    return `<option value="${escapeHtml(uid)}">${escapeHtml(name)}</option>`;
  }).join("");
  const saved = localStorage.getItem("powersite-dashboard-site");
  const selected = options.some(item => (item.site_uid || item.uid || item.id) === saved)
    ? saved
    : (options[0].site_uid || options[0].uid || options[0].id);
  select.value = selected;
  state.site = selected;
}

async function loadDashboard() {
  if (!state.site) return;
  setLoading(true);
  const site = encodeURIComponent(state.site);
  const entries = Object.entries(endpoints);
  const results = await Promise.allSettled(entries.map(([, build]) => fetchJson(build(site))));
  state.data = {};
  state.errors = {};
  entries.forEach(([key], index) => {
    const result = results[index];
    if (result.status === "fulfilled") state.data[key] = result.value;
    else state.errors[key] = result.reason?.message || "Unavailable";
  });
  renderAll();
  setLoading(false);
}

function latestPlan() {
  const plans = state.data.plans;
  return Array.isArray(plans) && plans.length ? plans[0] : null;
}

function currentSiteLabel() {
  const match = state.sites.find(item => {
    const uid = item.site_uid || item.uid || item.id;
    return uid === state.site;
  });
  return match?.name || state.site || "Power site";
}

function renderAll() {
  byId("siteTitle").textContent = currentSiteLabel();
  renderStatus();
  renderOverviewMetrics();
  renderSocChart();
  renderAttention();
  renderPosture();
  renderLearningHealth();
  renderForecast();
  renderDecisions();
  renderPolicyLab();
  renderLearning();
  renderDiagnostics();
}

"""
