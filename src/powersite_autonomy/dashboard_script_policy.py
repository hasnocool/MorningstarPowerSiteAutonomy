from __future__ import annotations

DASHBOARD_SCRIPT_POLICY = r"""function renderDecisions() {
  renderAlternatives();
  renderPolicy();
  renderShadowActions();
  renderAutopilotScore();
}

function renderAlternatives() {
  const plan = latestPlan();
  if (!plan?.alternatives?.length) {
    byId("alternativeTable").innerHTML = empty("No shadow alternatives have been persisted yet.");
    return;
  }
  const rows = plan.alternatives.map(item => `
    <tr class="${item.name === plan.selected_mode ? "selected" : ""}">
      <td>${escapeHtml(label(item.name))}</td>
      <td>${percent(item.reserve_breach_probability, 1)}</td>
      <td>${number(item.minimum_soc_p10_percent, 0)}%</td>
      <td>${energy(item.scheduled_load_wh)}</td>
      <td>${energy(item.deferred_load_wh)}</td>
      <td>${number(item.objective_score, 1)}</td>
    </tr>`).join("");
  byId("alternativeTable").innerHTML = `
    <table>
      <thead><tr>
        <th>Mode</th><th>Risk</th><th>Min SOC</th><th>Scheduled</th><th>Deferred</th><th>Score</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderPolicy() {
  const policy = state.data.policy?.policy || latestPlan()?.policy;
  if (!policy) {
    byId("policyCard").innerHTML = empty("No site policy is configured.");
    return;
  }
  byId("policyCard").innerHTML = `
    <div class="kv-grid">
      ${kv("Policy version", policy.policy_version || "—")}
      ${kv("Minimum reserve", `${number(policy.minimum_reserve_percent, 0)}%`)}
      ${kv("Emergency reserve", `${number(policy.emergency_reserve_percent, 0)}%`)}
      ${kv("Morning SOC target", `${number(policy.target_morning_soc_percent, 0)}%`)}
      ${kv("Risk target", percent(policy.target_reserve_breach_probability, 1))}
      ${kv("Hardware execution", "Disabled")}
    </div>`;
}

function renderShadowActions() {
  const raw = state.data.shadowActions;
  const actions = Array.isArray(raw) ? raw : [];
  if (!actions.length) {
    byId("shadowActions").innerHTML = empty("No shadow actions have been recorded yet.");
    return;
  }
  byId("shadowActions").innerHTML = actions.slice(0, 8).map(item => {
    const action = item.action || item;
    const status = item.status || "recorded";
    return `
      <div class="action-item">
        <div class="action-top">
          <span class="action-title">${escapeHtml(label(action.kind || action.operation))}</span>
          <span class="pill"><span class="dot"></span>${escapeHtml(label(status))}</span>
        </div>
        <div class="small muted">${escapeHtml(action.reason || "Recorded shadow proposal")}</div>
      </div>`;
  }).join("");
}

function renderAutopilotScore() {
  const s = state.data.autopilotScore;
  if (!s) {
    byId("autopilotScore").innerHTML = empty("No mature counterfactual evaluations yet.");
    return;
  }
  byId("autopilotScore").innerHTML = `
    <div class="kv-grid">
      ${kv("Evaluations", number(s.evaluation_count))}
      ${kv("Median decision regret", s.median_decision_regret_percent == null
        ? "—" : `${number(s.median_decision_regret_percent, 1)}%`)}
      ${kv("Shadow reserve breaches", number(s.shadow_reserve_breaches))}
      ${kv("Actual reserve breaches", number(s.actual_reserve_breaches))}
      ${kv("Potential surplus recovered", energy(s.potential_surplus_recovered_wh))}
      ${kv("Average feedback confidence", s.average_feedback_confidence == null
        ? "—" : percent(s.average_feedback_confidence, 0))}
    </div>`;
}

function renderPolicyLab() {
  const lab = state.data.policyLab;
  const reserve = state.data.policyReserve;
  const intelligence = lab?.intelligence;
  const score = lab?.scorecard;
  byId("policyMetrics").innerHTML = [
    metricCard(
      "Autonomy intelligence",
      intelligence ? `${number(intelligence.overall, 0)} / 100` : "—",
      intelligence?.biggest_opportunity
        ? `Opportunity: ${label(intelligence.biggest_opportunity)}`
        : "Awaiting mature policy evidence",
      intelligence?.overall >= 80 ? "good" : intelligence?.overall >= 60 ? "warn" : "",
    ),
    metricCard(
      "Effective reserve",
      reserve ? `${number(reserve.effective_reserve_percent, 0)}%` : "—",
      reserve ? `${label(reserve.regime)} regime` : "Dynamic reserve unavailable",
      reserve && reserve.effective_reserve_percent > reserve.base_reserve_percent ? "warn" : "good",
    ),
    metricCard(
      "Replay evidence",
      score ? number(score.replay_count) : "—",
      "Mature point-in-time policy replays",
    ),
    metricCard(
      "Candidates evaluated",
      score ? number(score.candidates_evaluated) : "—",
      `${number(score?.promotions ?? 0)} promotions`,
    ),
    metricCard(
      "Latest improvement",
      score ? percent(score.latest_improvement_fraction, 1) : "—",
      score
        ? `Paired confidence ${percent(score.latest_paired_confidence, 0)}`
        : "No tournament yet",
      score?.latest_improvement_fraction > 0 ? "good" : "",
    ),
    metricCard(
      "Pareto policies",
      score ? number(score.pareto_policies) : "—",
      "Non-dominated policy choices",
    ),
  ].join("");
  renderPolicyChampion();
  renderDynamicReserve();
  renderPolicyFrontier();
  renderPolicyRegret();
  renderDecisionSensitivity();
  renderPolicyTournament();
}

function renderPolicyChampion() {
  const champion = state.data.policyLab?.champion;
  if (!champion) {
    byId("policyChampion").innerHTML = empty(
      "Policy Lab has not produced a champion snapshot yet.",
    );
    return;
  }
  const policy = champion.policy || {};
  byId("policyChampion").innerHTML = `
    <div class="kv-grid">
      ${kv("Objective", label(champion.objective))}
      ${kv("Origin", label(champion.origin))}
      ${kv("Policy status", label(champion.status))}
      ${kv("Regime scope", champion.regime ? label(champion.regime) : "Global")}
      ${kv("Minimum reserve", `${number(policy.minimum_reserve_percent, 0)}%`)}
      ${kv("Morning SOC target", `${number(policy.target_morning_soc_percent, 0)}%`)}
    </div>`;
}

function renderDynamicReserve() {
  const value = state.data.policyReserve;
  if (!value) {
    byId("dynamicReserve").innerHTML = empty("Dynamic reserve is not available yet.");
    return;
  }
  const targets = value.horizon_targets || [];
  const targetHtml = targets.length ? targets.map(item => `
    <div class="learning-item">
      <div class="action-top">
        <span class="action-title">${number(item.horizon_hours)}h horizon</span>
        <span class="small muted">${number(item.target_reserve_percent, 0)}% target</span>
      </div>
      <div class="progress">
        <span style="width:${clamp(item.pressure * 100, 0, 100)}%"></span>
      </div>
    </div>`).join("") : empty("No reserve-pressure horizons were produced.");
  byId("dynamicReserve").innerHTML = `
    <div class="kv-grid">
      ${kv("Base reserve", `${number(value.base_reserve_percent, 0)}%`)}
      ${kv("Effective reserve", `${number(value.effective_reserve_percent, 0)}%`)}
      ${kv("Current regime", label(value.regime))}
      ${kv(
        "Allowed range",
        `${number(value.lower_bound_percent, 0)}–${number(value.upper_bound_percent, 0)}%`,
      )}
    </div>
    <div class="section-spacer"></div>
    <div class="learning-list">${targetHtml}</div>`;
}

function renderPolicyFrontier() {
  const points = state.data.policyLab?.frontier?.points || [];
  if (!points.length) {
    byId("policyFrontier").innerHTML = empty("No mature Pareto frontier yet.");
    return;
  }
  const rows = points.slice(0, 10).map(item => `
    <tr>
      <td>${escapeHtml(label(item.objective))}</td>
      <td>${number(item.mean_score, 1)}</td>
      <td>${number(item.actual_safety_incidents)}</td>
      <td>${energy(item.auxiliary_energy_wh)}</td>
      <td>${energy(item.deferred_load_wh)}</td>
    </tr>`).join("");
  byId("policyFrontier").innerHTML = `
    <table>
      <thead><tr>
        <th>Objective</th><th>Score</th><th>Safety</th><th>Aux</th><th>Deferred</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderPolicyRegret() {
  const regret = state.data.policyLab?.regret;
  if (!regret || !regret.evaluation_count) {
    byId("policyRegret").innerHTML = empty("Not enough mature evaluations to decompose regret.");
    return;
  }
  const parts = [
    ["Weather model", regret.weather_model],
    ["PV model", regret.pv_model],
    ["Load model", regret.load_model],
    ["Battery model", regret.battery_model],
    ["Policy selection", regret.policy_selection],
    ["Optimizer", regret.optimizer_approximation],
    ["Irreducible uncertainty", regret.irreducible_uncertainty],
  ];
  const max = Math.max(0.0001, ...parts.map(([, value]) => Number(value) || 0));
  byId("policyRegret").innerHTML = parts.map(([name, value]) => `
    <div class="learning-item">
      <div class="action-top">
        <span class="action-title">${escapeHtml(name)}</span>
        <span class="small muted">${number(value, 1)}</span>
      </div>
      <div class="progress">
        <span style="width:${clamp((Number(value) / max) * 100, 0, 100)}%"></span>
      </div>
    </div>`).join("");
}

function renderDecisionSensitivity() {
  const signals = state.data.policyLab?.decision_sensitivity?.signals || [];
  if (!signals.length) {
    byId("decisionSensitivity").innerHTML = empty("No decision-sensitivity ranking yet.");
    return;
  }
  const sorted = [...signals].sort((a, b) => b.priority_score - a.priority_score);
  const max = Math.max(0.0001, ...sorted.map(item => Number(item.priority_score) || 0));
  byId("decisionSensitivity").innerHTML = sorted.map(item => `
    <div class="learning-item">
      <div class="action-top">
        <span class="action-title">${escapeHtml(label(item.source))}</span>
        <span class="small muted">priority ${number(item.priority_score, 2)}</span>
      </div>
      <div class="small muted" style="margin-bottom:.42rem">
        Error ${number(item.mean_normalized_error, 2)} · regret
        ${number(item.mean_regret_percent, 1)}%
      </div>
      <div class="progress">
        <span style="width:${clamp((item.priority_score / max) * 100, 0, 100)}%"></span>
      </div>
    </div>`).join("");
}

function renderPolicyTournament() {
  const t = state.data.policyLab?.tournament;
  if (!t) {
    byId("policyTournament").innerHTML = empty("No completed policy tournament yet.");
    return;
  }
  byId("policyTournament").innerHTML = `
    <div class="kv-grid">
      ${kv("Promoted", t.promoted ? "Yes" : "No")}
      ${kv("Safety gate", t.safety_gate_passed ? "Passed" : "Not passed")}
      ${kv("Improvement", percent(t.improvement_fraction, 1))}
      ${kv("Paired confidence", percent(t.paired_confidence, 0))}
      ${kv("Champion before", t.champion_before || "—")}
      ${kv("Champion after", t.champion_after || "—")}
    </div>
    <div class="section-spacer"></div>
    <div class="small muted">
      ${escapeHtml(t.reason || "No tournament explanation recorded.")}
    </div>`;
}

"""
