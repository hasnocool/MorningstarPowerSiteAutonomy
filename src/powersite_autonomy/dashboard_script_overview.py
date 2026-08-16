from __future__ import annotations


DASHBOARD_SCRIPT_OVERVIEW = r"""function renderStatus() {
  const health = state.data.health;
  const forecast = state.data.forecast;
  const plan = latestPlan();
  const upstream = health?.morningstar_api === "reachable";
  const risk = forecast?.reserve_breach_probability;
  const riskClass = riskTone(risk);
  const status = [
    `<span class="pill ${upstream ? "good" : "bad"}">` +
      `<span class="dot"></span>${upstream ? "Telemetry connected" : "Telemetry unavailable"}` +
      `</span>`,
    `<span class="pill ${riskClass}"><span class="dot"></span>` +
      `Reserve risk ${percent(risk, 1)}</span>`,
    `<span class="pill ${confidenceTone(forecast?.confidence)}">` +
      `<span class="dot"></span>Forecast ${escapeHtml(forecast?.confidence || "unknown")}</span>`,
    `<span class="pill"><span class="dot"></span>` +
      `Updated ${escapeHtml(timeAgo(forecast?.generated_at || plan?.generated_at))}</span>`,
  ];
  byId("statusRow").innerHTML = status.join("");
  const summary = summaryText(forecast, plan);
  byId("summaryLine").textContent = summary;
}

function summaryText(forecast, plan) {
  if (!forecast) return "Forecast data is unavailable; check Diagnostics for the failing source.";
  const risk = Number(forecast.reserve_breach_probability || 0);
  if (risk >= 0.1) {
    return "Reserve risk is elevated. Review proposed actions and the low-end SOC trajectory.";
  }
  if (forecast.minimum_soc_p10_percent < (plan?.policy?.minimum_reserve_percent ?? 25)) {
    return "The conservative SOC path approaches reserve; keep discretionary demand flexible.";
  }
  if (forecast.safe_discretionary_energy_wh > 250) {
    return "The site is forecast to stay above reserve with usable discretionary energy available.";
  }
  return "The site is presently within its planning guardrails; keep watching forecast confidence.";
}

function renderOverviewMetrics() {
  const f = state.data.forecast;
  const twin = state.data.twin;
  const battery = twin?.battery;
  const policy = state.data.policy?.policy;
  const currentSoc = battery?.soc_percent;
  const reserve = policy?.minimum_reserve_percent;
  const risk = f?.reserve_breach_probability;
  byId("metricGrid").innerHTML = [
    metricCard(
      "Battery now",
      currentSoc === undefined ? "—" : `${number(currentSoc, 0)}%`,
      battery?.soc_confidence ? `${label(battery.soc_confidence)} confidence` : "No SOC evidence",
      currentSoc >= (reserve ?? 25) ? "good" : "warn",
    ),
    metricCard(
      "Lowest expected SOC",
      f ? `${number(f.minimum_soc_p10_percent, 0)}%` : "—",
      `P10 floor · reserve ${reserve === undefined ? "—" : `${number(reserve, 0)}%`}`,
      f && f.minimum_soc_p10_percent >= (reserve ?? 25) ? "good" : "warn",
    ),
    metricCard(
      "Reserve risk",
      percent(risk, 1),
      f?.first_reserve_breach_at
        ? `First possible breach ${timeUntil(f.first_reserve_breach_at)}`
        : "No breach time predicted",
      riskTone(risk),
    ),
    metricCard(
      "72h solar",
      energy(f?.expected_solar_wh),
      `Expected load ${energy(f?.expected_load_wh)}`,
    ),
    metricCard(
      "Safe flexible energy",
      energy(f?.safe_discretionary_energy_wh),
      "Conservative discretionary budget",
      f?.safe_discretionary_energy_wh > 0 ? "good" : "warn",
    ),
    metricCard(
      "No-solar autonomy",
      f?.autonomy_hours_if_no_solar == null
        ? "—"
        : `${number(f.autonomy_hours_if_no_solar, 1)} h`,
      `Effective battery ${energy(f?.effective_battery_capacity_wh)}`,
    ),
  ].join("");
}

function svgGrid(width, height) {
  const lines = [];
  for (let i = 1; i < 5; i += 1) {
    const y = (height / 5) * i;
    lines.push(
      `<line x1="0" y1="${y}" x2="${width}" y2="${y}" ` +
      `stroke="#22303a" stroke-width="1"/>`,
    );
  }
  return lines.join("");
}

function linePoints(values, width, height, min, max) {
  if (!values.length) return "";
  const range = Math.max(0.0001, max - min);
  return values.map((value, index) => {
    const x = values.length === 1 ? 0 : (index / (values.length - 1)) * width;
    const y = height - ((Number(value) - min) / range) * height;
    return `${x.toFixed(1)},${clamp(y, 0, height).toFixed(1)}`;
  }).join(" ");
}

function bandPoints(low, high, width, height, min, max) {
  const upper = linePoints(high, width, height, min, max).split(" ");
  const lower = linePoints(low, width, height, min, max).split(" ").reverse();
  return [...upper, ...lower].join(" ");
}

function renderSocChart() {
  const points = state.data.forecast?.points || [];
  if (!points.length) {
    byId("socChart").innerHTML = empty("No forecast trajectory is available.");
    return;
  }
  const width = 820;
  const height = 205;
  const p10 = points.map(item => item.soc_p10_percent);
  const p50 = points.map(item => item.soc_p50_percent);
  const p90 = points.map(item => item.soc_p90_percent);
  const reserve = state.data.policy?.policy?.minimum_reserve_percent ?? 25;
  const reserveY = height - (clamp(reserve, 0, 100) / 100) * height;
  const band = bandPoints(p10, p90, width, height, 0, 100);
  const mid = linePoints(p50, width, height, 0, 100);
  byId("socChart").innerHTML = `
    <svg viewBox="0 0 ${width} 235" role="img" aria-label="72-hour battery SOC forecast">
      <g transform="translate(0 8)">
        ${svgGrid(width, height)}
        <line x1="0" y1="${reserveY}" x2="${width}" y2="${reserveY}"
          stroke="#f4c76b" stroke-dasharray="6 5" stroke-width="1.3" />
        <polygon points="${band}" fill="rgb(103 183 255 / 13%)" />
        <polyline points="${mid}" fill="none" stroke="#66d9a6" stroke-width="3"
          stroke-linejoin="round" stroke-linecap="round" />
        <text x="6" y="${Math.max(12, reserveY - 5)}" fill="#f4c76b" font-size="11">
          Reserve ${number(reserve, 0)}%
        </text>
      </g>
      <text x="0" y="232" fill="#718899" font-size="11">Now</text>
      <text x="${width - 38}" y="232" fill="#718899" font-size="11">72h</text>
    </svg>`;
}

function renderPowerChart() {
  const points = state.data.forecast?.points || [];
  if (!points.length) {
    byId("powerChart").innerHTML = empty("No hourly solar/load forecast is available.");
    return;
  }
  const width = 820;
  const height = 205;
  const solar = points.map(item => item.solar_p50_w);
  const load = points.map(item => item.load_p50_w);
  const max = Math.max(50, ...solar, ...load) * 1.08;
  const solarLine = linePoints(solar, width, height, 0, max);
  const loadLine = linePoints(load, width, height, 0, max);
  byId("powerChart").innerHTML = `
    <svg viewBox="0 0 ${width} 235" role="img" aria-label="Solar generation and load forecast">
      <g transform="translate(0 8)">
        ${svgGrid(width, height)}
        <polyline points="${solarLine}" fill="none" stroke="#66d9a6" stroke-width="2.5"
          stroke-linejoin="round" stroke-linecap="round" />
        <polyline points="${loadLine}" fill="none" stroke="#f4c76b" stroke-width="2.2"
          stroke-linejoin="round" stroke-linecap="round" />
      </g>
      <text x="0" y="232" fill="#718899" font-size="11">Now</text>
      <text x="${width - 38}" y="232" fill="#718899" font-size="11">72h</text>
    </svg>`;
}

function renderAttention() {
  const f = state.data.forecast;
  const items = [];
  const planActions = state.data.actions?.actions || [];
  const policy = state.data.policy?.policy;
  if (f && f.reserve_breach_probability >= 0.1) {
    items.push({
      title: "Reserve risk is elevated",
      priority: "high",
      reason: `Risk is ${percent(f.reserve_breach_probability, 1)} over the next 72 hours.`,
    });
  }
  if (f && f.minimum_soc_p10_percent < (policy?.minimum_reserve_percent ?? 25)) {
    items.push({
      title: "Conservative SOC falls below reserve",
      priority: "high",
      reason: `P10 minimum is ${number(f.minimum_soc_p10_percent, 0)}%.`,
    });
  }
  planActions.forEach(action => {
    items.push({
      title: label(action.kind),
      priority: action.priority || "medium",
      reason: action.reason || "Review the current decision-support recommendation.",
    });
  });
  if (state.errors.forecast) {
    items.unshift({
      title: "Forecast unavailable",
      priority: "high",
      reason: state.errors.forecast,
    });
  }
  if (!items.length) {
    items.push({
      title: "No urgent attention items",
      priority: "low",
      reason: "Current forecasts and read-only recommendations are within normal guardrails.",
    });
  }
  byId("attentionList").innerHTML = items.slice(0, 5).map(item => `
    <div class="attention-item">
      <div class="attention-top">
        <div class="attention-title">${escapeHtml(item.title)}</div>
        <span class="priority ${escapeHtml(item.priority)}">${escapeHtml(item.priority)}</span>
      </div>
      <div class="small muted">${escapeHtml(item.reason)}</div>
    </div>`).join("");
}

function renderPosture() {
  const plan = latestPlan();
  if (!plan) {
    byId("postureCard").innerHTML = empty(
      "No persisted shadow plan yet. Use Decisions → Run fresh shadow cycle.",
    );
    return;
  }
  const policy = plan.policy || {};
  const dynamic = state.data.policyReserve;
  byId("postureCard").innerHTML = `
    <div class="kv-grid">
      ${kv("Selected mode", label(plan.selected_mode))}
      ${kv("Plan age", timeAgo(plan.generated_at))}
      ${kv("Base reserve", `${number(policy.minimum_reserve_percent, 0)}%`)}
      ${kv(
        "Effective reserve",
        dynamic ? `${number(dynamic.effective_reserve_percent, 0)}%` : "Not calculated",
      )}
      ${kv("Scheduled flexible load", energy(plan.scheduled_load_wh))}
      ${kv("Deferred load", energy(plan.deferred_load_wh))}
    </div>`;
}

function renderLearningHealth() {
  const adaptive = state.data.adaptive;
  const score = state.data.adaptiveScore;
  if (!adaptive && !score) {
    byId("learningHealth").innerHTML = empty("Adaptive World has not produced a snapshot yet.");
    return;
  }
  const champion = adaptive?.champion_model || score?.champion_model || "baseline";
  const calibrated = score?.uncertainty_metrics_calibrated ?? 0;
  const changes = score?.change_points_detected ?? 0;
  const battery = score?.battery_health_percent;
  byId("learningHealth").innerHTML = `
    <div class="kv-grid">
      ${kv("Champion model", champion)}
      ${kv("Weather models ranked", number(score?.weather_models_ranked ?? 0))}
      ${kv("Calibrated uncertainty metrics", number(calibrated))}
      ${kv("High-confidence changes", number(changes))}
      ${kv(
        "Battery health estimate",
        battery == null ? "Not enough evidence" : `${number(battery, 1)}%`,
      )}
      ${kv("Adaptive snapshot", timeAgo(adaptive?.generated_at))}
    </div>`;
}

function renderForecast() {
  const f = state.data.forecast;
  byId("forecastMetrics").innerHTML = [
    metricCard("Expected solar", energy(f?.expected_solar_wh), "Next 72 hours"),
    metricCard("Expected load", energy(f?.expected_load_wh), "Next 72 hours"),
    metricCard("Expected surplus", energy(f?.expected_surplus_wh), "Before flexible use"),
    metricCard(
      "Reserve breach risk",
      percent(f?.reserve_breach_probability, 1),
      "Monte Carlo estimate",
      riskTone(f?.reserve_breach_probability),
    ),
    metricCard(
      "Unmet-load risk",
      percent(f?.unmet_load_probability, 1),
      "Probability of modeled shortfall",
      riskTone(f?.unmet_load_probability),
    ),
    metricCard(
      "Forecast confidence",
      label(f?.confidence),
      `Model ${f?.model_version || "—"}`,
      confidenceTone(f?.confidence),
    ),
  ].join("");
  renderPowerChart();
  renderBatteryDetails();
  renderForecastConfidence();
}

function renderBatteryDetails() {
  const b = state.data.twin?.battery;
  if (!b) {
    byId("batteryDetails").innerHTML = empty("Digital-twin battery data is unavailable.");
    return;
  }
  byId("batteryDetails").innerHTML = `
    <div class="kv-grid">
      ${kv("Chemistry", label(b.chemistry))}
      ${kv("Current SOC", `${number(b.soc_percent, 1)}%`)}
      ${kv("Nominal capacity", energy(b.nominal_capacity_wh))}
      ${kv("Effective capacity", energy(b.effective_capacity_wh))}
      ${kv("Estimated health", `${number(b.estimated_health_percent, 1)}%`)}
      ${kv("SOC confidence", label(b.soc_confidence))}
      ${kv("Temperature", b.temperature_c == null ? "Unknown" : `${number(b.temperature_c, 1)} °C`)}
      ${kv(
        "Internal resistance",
        b.estimated_internal_resistance_ohm == null
          ? "Not estimated"
          : `${number(b.estimated_internal_resistance_ohm, 4)} Ω`,
      )}
    </div>`;
}

function renderForecastConfidence() {
  const f = state.data.forecast;
  if (!f) {
    byId("forecastConfidence").innerHTML = empty("Forecast confidence is unavailable.");
    return;
  }
  const quality = Object.entries(f.input_quality || {});
  const rows = quality.length ? quality.map(([name, value]) => `
    <div class="learning-item">
      <div class="action-top">
        <span class="action-title">${escapeHtml(label(name))}</span>
        <span class="pill ${confidenceTone(value)}"><span class="dot"></span>` +
          `${escapeHtml(label(value))}</span>
      </div>
    </div>`).join("") : empty("No input-quality breakdown was recorded.");
  byId("forecastConfidence").innerHTML = rows;
}

"""
