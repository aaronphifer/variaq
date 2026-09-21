/* Campaign pages, analysis visualization, reports, capabilities.
   Chart data comes only from VariaQ AnalysisResult JSON (no JS-side metrics). */
"use strict";

(function () {
const { apiGet, apiPost, esc, html, fmtNum, fmtTime, fmtBytes, shortId, statusPill, boolText, setStatus, kvFill, tableRows } = window.VARIAQ;

const CHART_COLORS = ["#14548c", "#1b6b3a", "#8c5a00", "#9c1f1f", "#5b3f8c", "#0f6e73", "#745c00", "#333"];

function groupKeyLabel(key) {
  return Object.entries(key).map(([k, v]) => `${k}=${v}`).join(", ") || "(all runs)";
}

function renderAnalysisInto(container, analysis) {
  const parts = [];
  if (analysis.warnings && analysis.warnings.length) {
    parts.push(`<div class="notice warn">${analysis.warnings.map(esc).join("<br>")}</div>`);
  }
  for (const group of analysis.groups || []) {
    const q = group.quality, f = group.feasibility, t = group.timing, r = group.resource;
    parts.push(`<h3>${esc(groupKeyLabel(group.group_key))}</h3>`);
    parts.push(`<div class="table-wrap"><table class="data-table"><thead><tr>
      <th>Runs</th><th>Best objective</th><th>Mean objective</th><th>Mean gap %</th>
      <th>Optimum rate</th><th>Feasible runs</th><th>Mean feasible rate</th>
      <th>Wall mean s</th><th>Binary vars</th><th>Qubits</th></tr></thead><tbody>`);
    parts.push(`<tr><td>${group.count}</td><td>${fmtNum(q.best_objective)}</td>
      <td>${fmtNum(q.mean_objective)}</td><td>${fmtNum(q.mean_gap_percent, 4)}</td>
      <td>${fmtNum(q.success_at_optimum_rate, 3)}</td>
      <td>${f.feasible_runs}/${f.count}</td><td>${fmtNum(f.mean_feasible_rate, 3)}</td>
      <td>${fmtNum(t.total_wall_time_seconds.mean, 4)}</td>
      <td>${r.binary_variables ?? "—"}</td><td>${r.qubits ?? "—"}</td></tr>`);
    parts.push(`</tbody></table></div>`);
  }
  for (const comp of analysis.comparisons || []) {
    if (!comp.pairs.length) continue;
    parts.push(`<h3>Comparison: ${esc(comp.comparison_type)}</h3>`);
    parts.push(`<div class="table-wrap"><table class="data-table"><thead><tr><th>Problem</th><th>Solver</th><th>Objective</th><th>Gap %</th></tr></thead><tbody>`);
    for (const pair of comp.pairs) {
      for (const key of Object.keys(pair)) {
        if (key === "problem_id" || key.endsWith("_run_ids") || typeof pair[key] !== "object" || pair[key] === null) continue;
        const cell = pair[key];
        parts.push(`<tr><td><code>${esc(shortId(pair.problem_id))}</code></td><td>${esc(key)}</td>
          <td>${fmtNum(cell.objective)}</td><td>${fmtNum(cell.gap_percent, 4)}</td></tr>`);
      }
    }
    parts.push(`</tbody></table></div>`);
    if (comp.warnings && comp.warnings.length) {
      parts.push(`<p class="muted">${comp.warnings.map(esc).join("<br>")}</p>`);
    }
  }
  container.innerHTML = parts.join("") || `<p class="muted">No analysis groups.</p>`;
}

function scalingSeries(points, pickValue) {
  const series = new Map();
  const table = new Map();
  for (const point of points || []) {
    const key = groupKeyLabel(Object.fromEntries(
      Object.entries(point.group_key).filter(([k]) => k !== "problem_size")
    ));
    const y = pickValue(point);
    if (y === null || y === undefined) continue;
    if (!series.has(key)) { series.set(key, []); table.set(key, []); }
    series.get(key).push({ x: point.x_value, y });
    table.get(key).push([point.x_value, y]);
  }
  for (const pts of series.values()) pts.sort((a, b) => a.x - b.x);
  return { series, table };
}

function drawScalingChart(canvasId, tableId, points, yLabel, pickValue) {
  const canvas = el(canvasId);
  if (!canvas) return;
  const { series, table } = scalingSeries(points, pickValue);
  // Accessible data table regardless of canvas rendering.
  const tbl = el(tableId);
  if (tbl) {
    const rows = [];
    for (const [key, vals] of table) {
      for (const [x, y] of vals) rows.push(`<tr><td>${esc(key)}</td><td>${x}</td><td>${fmtNum(y, 5)}</td></tr>`);
    }
    tbl.innerHTML = rows.length
      ? `<caption class="sr-only">${esc(yLabel)} by group</caption><thead><tr><th>Group</th><th>x</th><th>${esc(yLabel)}</th></tr></thead><tbody>${rows.join("")}</tbody>`
      : "";
  }
  if (!series.size || typeof Chart === "undefined") return;
  const datasets = [...series.entries()].map(([label, data], i) => ({
    label, data, borderColor: CHART_COLORS[i % CHART_COLORS.length],
    backgroundColor: CHART_COLORS[i % CHART_COLORS.length], showLine: true, tension: 0.15,
  }));
  new Chart(canvas, {
    type: "scatter",
    data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { type: "linear", title: { display: true, text: "problem size" } },
        y: { title: { display: true, text: yLabel } },
      },
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } },
    },
  });
}

/* -- campaigns list ----------------------------------------------------------- */
async function initCampaigns() {
  pollActiveTask("active-task-region");
  try {
    const data = await apiGet("/campaigns");
    el("campaigns-status").hidden = true;
    el("campaigns-wrap").hidden = false;
    tableRows("campaigns-table", data.campaigns.map(c => {
      const counts = Object.entries(c.status_counts || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "—";
      return `<tr>
        <td><a href="/campaigns/${esc(c.campaign_id)}" title="${esc(c.campaign_id)}"><code>${esc(shortId(c.campaign_id))}</code></a></td>
        <td class="wrap-anywhere">${esc(c.name)}</td><td>${esc(c.family)}</td><td>${fmtTime(c.created_at)}</td>
        <td>${c.requested_runs}</td><td>${c.completed_runs}</td><td>${esc(counts)}</td></tr>`;
    }), 7, "No campaigns yet. Create one from “New campaign”.");
  } catch (err) {
    setStatus("campaigns-status", `${err.type}: ${err.message}`, true);
  }
}

async function pollActiveTask(regionId) {
  const region = el(regionId);
  if (!region) return;
  async function refresh() {
    let payload;
    try { payload = await apiGet("/campaigns/tasks/current"); } catch { return; }
    const task = payload.task;
    if (!task || (task.status !== "starting" && task.status !== "running")) {
      region.hidden = true;
      return;
    }
    region.hidden = false;
    const total = task.planned_runs;
    const pct = total ? Math.min(100, (task.completed_runs / total) * 100) : 0;
    region.innerHTML = `<div class="task-card" role="status">
      <strong>Campaign ${esc(task.status)}</strong> —
      ${task.completed_runs}${total ? " / " + total : ""} runs recorded
      <div class="progress" aria-hidden="true"><div style="width:${pct}%"></div></div>
      <span class="muted">task ${esc(task.task_id)}</span></div>`;
    setTimeout(refresh, 2000);
  }
  refresh();
}

/* -- campaign detail ---------------------------------------------------------- */
async function initCampaignDetail() {
  const id = decodeURIComponent(location.pathname.split("/").pop());
  const runState = { offset: 0, limit: 25 };
  try {
    const data = await apiGet("/campaigns/" + encodeURIComponent(id));
    el("campaign-status").hidden = true;
    el("campaign-detail").hidden = false;
    const d = data.definition;
    kvFill(el("campaign-def-kv"), [
      ["Name", d.name],
      ["Family", d.family],
      ["Problem sizes", d.problem_sizes.join(", ")],
      ["Problem seeds", d.problem_seeds.join(", ")],
      ["Solvers", d.solvers.join(", ")],
      ["Repeats", d.repeats],
      ["Generator parameters", Object.keys(d.generator_parameters || {}).length
        ? html(`<code>${esc(JSON.stringify(d.generator_parameters))}</code>`) : "—"],
      ["Created", fmtTime(d.created_at)],
    ]);
    kvFill(el("campaign-exec-kv"), [
      ["Requested runs", data.requested_runs],
      ["Completed runs", data.completed_runs],
      ["Status counts", Object.entries(data.status_counts || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"],
      ["Solver breakdown", Object.entries(data.solver_breakdown || {}).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"],
    ]);
    loadCampaignRuns(id, runState);
    el("campaign-runs-prev").addEventListener("click", () => {
      runState.offset = Math.max(0, runState.offset - runState.limit); loadCampaignRuns(id, runState);
    });
    el("campaign-runs-next").addEventListener("click", () => {
      runState.offset += runState.limit; loadCampaignRuns(id, runState);
    });

    await runAnalysis(id);
    el("analysis-controls").addEventListener("submit", async e => { e.preventDefault(); await runAnalysis(id); });

    await loadCampaignReports(id);
    el("report-form").addEventListener("submit", async e => {
      e.preventDefault();
      await generateCampaignReport(id, e.target);
    });
  } catch (err) {
    setStatus("campaign-status", `${err.type}: ${err.message}`, true);
  }
}

async function loadCampaignRuns(campaignId, state) {
  try {
    const data = await apiGet(`/runs?campaign_id=${encodeURIComponent(campaignId)}&limit=${state.limit}&offset=${state.offset}`);
    tableRows("campaign-runs-table", data.runs.map(r => `<tr>
      <td><a href="/runs/${esc(r.run_id)}"><code>${esc(shortId(r.run_id))}</code></a></td>
      <td>${esc(r.solver_name)}</td>
      <td><a href="/problems/${esc(r.problem_id)}"><code>${esc(shortId(r.problem_id))}</code></a></td>
      <td>${statusPill(r.status)}</td><td>${fmtTime(r.created_at)}</td></tr>`), 5, "No member runs.");
    const from = data.total === 0 ? 0 : data.offset + 1;
    const to = Math.min(data.offset + data.limit, data.total);
    el("campaign-runs-page-info").textContent = `${from}–${to} of ${data.total}`;
    el("campaign-runs-prev").disabled = data.offset === 0;
    el("campaign-runs-next").disabled = data.offset + data.limit >= data.total;
  } catch (err) {
    setStatus("campaign-status", `${err.type}: ${err.message}`, true);
  }
}

async function runAnalysis(campaignId) {
  const form = el("analysis-controls");
  const groupBy = form.group_by.value.split(",").filter(Boolean);
  const comparisons = form.compare_cvq.checked ? ["classical_vs_quantum"] : [];
  try {
    const analysis = await apiPost(`/analysis/campaigns/${encodeURIComponent(campaignId)}`, {
      group_by: groupBy,
      scaling_x: form.scaling_x.value,
      include_failed: form.include_failed.checked,
      comparisons,
    });
    el("analysis-provenance").textContent =
      `${analysis.source_run_ids.length} source runs · campaign ${campaignId} · group by ${groupBy.join(", ") || "none"}`;
    renderAnalysisInto(el("analysis-body"), analysis);
    const pts = analysis.scaling_points;
    drawScalingChart("chart-gap", "chart-gap-table", pts, "mean gap %",
      p => p.quality.mean_gap_percent);
    drawScalingChart("chart-time", "chart-time-table", pts, "mean wall s",
      p => p.timing.total_wall_time_seconds.mean);
    drawScalingChart("chart-feasible", "chart-feasible-table", pts, "mean feasible rate",
      p => p.feasibility.mean_feasible_rate);
    drawScalingChart("chart-qubits", "chart-qubits-table", pts, "qubits",
      p => p.resource.qubits);
  } catch (err) {
    el("analysis-body").innerHTML = `<p class="notice error">${esc(err.type)}: ${esc(err.message)}</p>`;
  }
}

async function loadCampaignReports(campaignId) {
  try {
    const data = await apiGet("/reports");
    const mine = data.reports.filter(r => r.campaign_id === campaignId);
    el("campaign-reports-list").innerHTML = mine.length
      ? mine.map(r => `<li><a href="/reports/${esc(r.report_id)}"><code>${esc(shortId(r.report_id))}</code></a>
          <span class="muted">${fmtTime(r.generated_at)} · ${r.source_run_count} source runs · ${esc(r.formats.join(", "))}</span></li>`).join("")
      : `<li class="muted">No reports for this campaign yet.</li>`;
  } catch (err) {
    el("campaign-reports-list").innerHTML = `<li class="notice error">${esc(err.message)}</li>`;
  }
}

async function generateCampaignReport(campaignId, form) {
  const formats = [];
  if (form.fmt_json.checked) formats.push("json");
  if (form.fmt_csv.checked) formats.push("csv");
  if (form.fmt_md.checked) formats.push("markdown");
  setStatus("report-gen-status", "Generating…");
  try {
    const result = await apiPost(`/reports/campaigns/${encodeURIComponent(campaignId)}`, {
      formats: formats.length ? formats : null,
      plots: form.fmt_plots.checked,
      overwrite: form.overwrite.checked,
    });
    const warn = (result.warnings || []).length ? ` (${result.warnings.join("; ")})` : "";
    setStatus("report-gen-status", `Report ${result.report_id} written.${warn}`);
    await loadCampaignReports(campaignId);
  } catch (err) {
    setStatus("report-gen-status", `${err.type}: ${err.message}`, true);
  }
}

/* -- campaign new / plan / run ------------------------------------------------ */
const FAMILY_PARAMS = {
  "maxcut": [{ name: "edge_probability", label: "Edge probability", value: "0.4" }],
  "assignment": [
    { name: "resource_count", label: "Resource count (blank = size)", value: "" },
    { name: "prohibited_probability", label: "Prohibited probability", value: "0" },
  ],
  "subset-selection": [
    { name: "budget", label: "Budget (blank = none)", value: "" },
    { name: "min_cardinality", label: "Min cardinality (blank = none)", value: "" },
    { name: "max_cardinality", label: "Max cardinality (blank = none)", value: "" },
  ],
  "graph-partition": [
    { name: "edge_probability", label: "Edge probability", value: "0.4" },
    { name: "partition_count", label: "Partition count", value: "2" },
  ],
};

async function initCampaignNew() {
  const form = el("campaign-form");
  let lastPlan = null;

  // Solver picker from live capabilities (no hardcoded matrix).
  try {
    const caps = await apiGet("/capabilities");
    el("solver-picker").innerHTML = caps.solvers.map(s =>
      `<label class="check"><input type="checkbox" name="solver" value="${esc(s.name)}"
        ${s.available ? "" : "disabled"} ${["exact", "heuristic"].includes(s.name) ? "checked" : ""}>
        ${esc(s.name)}${s.available ? "" : ` <span class="muted">(${esc(s.reason || "unavailable")})</span>`}</label>`
    ).join("");
  } catch (err) {
    el("solver-picker").innerHTML = `<span class="notice error">${esc(err.message)}</span>`;
  }

  const familySelect = el("campaign-family");
  function renderFamilyParams() {
    const fields = FAMILY_PARAMS[familySelect.value] || [];
    el("family-param-fields").innerHTML = fields.map(f =>
      `<label>${esc(f.label)} <input type="text" data-gen-param="${esc(f.name)}" value="${esc(f.value)}"></label>`
    ).join("") || `<p class="muted">No additional parameters for this family.</p>`;
  }
  familySelect.addEventListener("change", renderFamilyParams);
  renderFamilyParams();

  function gatherDefinition() {
    const sizes = form.problem_sizes.value.split(",").map(s => parseInt(s.trim(), 10)).filter(n => !Number.isNaN(n));
    const seeds = form.problem_seeds.value.split(",").map(s => parseInt(s.trim(), 10)).filter(n => !Number.isNaN(n));
    const solvers = [...form.querySelectorAll('input[name="solver"]:checked')].map(c => c.value);
    const genParams = {};
    for (const input of form.querySelectorAll("[data-gen-param]")) {
      const raw = input.value.trim();
      if (raw === "") continue;
      const num = Number(raw);
      genParams[input.dataset.genParam] = Number.isNaN(num) ? raw : num;
    }
    return {
      name: form.name.value.trim(),
      family: familySelect.value,
      problem_sizes: sizes,
      problem_seeds: seeds,
      solvers,
      repeats: parseInt(form.repeats.value, 10) || 1,
      base_seed: parseInt(form.base_seed.value, 10) || 0,
      generator_parameters: genParams,
      notes: form.notes.value,
      tags: [],
    };
  }

  form.addEventListener("submit", async e => {
    e.preventDefault();
    try {
      const definition = gatherDefinition();
      const plan = await apiPost("/campaigns/plan", { definition });
      lastPlan = { definition, plan };
      renderPlan(plan);
      el("plan-section").hidden = false;
      el("plan-section").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      el("plan-section").hidden = false;
      el("plan-body").innerHTML = `<p class="notice error">${esc(err.type)}: ${esc(err.message)}</p>`;
    }
  });

  function renderPlan(plan) {
    const rows = (plan.solver_breakdown || []).map(s => `<tr>
      <td>${esc(s.solver)}</td><td>${s.requested_runs}</td>
      <td>${boolText(s.supported)}</td><td>${boolText(s.installed)}</td><td>${boolText(s.available)}</td></tr>`).join("");
    const unavailable = (plan.unavailable || []).map(u =>
      `<li>${esc(u.solver)}: ${esc(u.reason)} <span class="muted">(${u.requested_runs} runs)</span></li>`).join("");
    const warnings = (plan.warnings || []).map(w => `<li>${esc(w)}</li>`).join("");
    el("plan-body").innerHTML = `
      <p><strong>${plan.problem_instance_count}</strong> problem instances ·
         <strong>${plan.requested_runs}</strong> requested runs ·
         default maximum ${plan.default_max_runs}</p>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>Solver</th><th>Runs</th><th>Supported</th><th>Installed</th><th>Available</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      ${unavailable ? `<h3>Unavailable combinations</h3><ul>${unavailable}</ul>` : ""}
      ${warnings ? `<h3>Warnings</h3><ul class="notice warn">${warnings}</ul>` : ""}`;
    const over = plan.exceeds_default_max;
    el("plan-override").hidden = !over;
    if (over) {
      el("plan-override-text").textContent =
        `This campaign requests ${plan.requested_runs} runs, which exceeds the default maximum of ${plan.default_max_runs}. VariaQ's own max-run guard still applies.`;
      el("override-max-runs").checked = false;
      el("run-campaign-btn").disabled = true;
      el("override-max-runs").addEventListener("change", ev => {
        el("run-campaign-btn").disabled = !ev.target.checked;
      });
    } else {
      el("run-campaign-btn").disabled = false;
    }
  }

  el("run-form").addEventListener("submit", async e => {
    e.preventDefault();
    if (!lastPlan) return;
    const btn = el("run-campaign-btn");
    btn.disabled = true;
    setStatus("run-status", "Starting…");
    try {
      const over = lastPlan.plan.exceeds_default_max;
      const result = await apiPost("/campaigns/run", {
        definition: lastPlan.definition,
        override_max_runs: over && el("override-max-runs").checked,
      });
      setStatus("run-status", `Task ${result.task.task_id} ${result.task.status}.`);
      pollTaskUntilDone(result.task.task_id);
    } catch (err) {
      setStatus("run-status", `${err.type}: ${err.message}`, true);
      btn.disabled = false;
    }
  });

  async function pollTaskUntilDone(taskId) {
    try {
      const payload = await apiGet("/campaigns/tasks/" + encodeURIComponent(taskId));
      const task = payload.task;
      const total = task.planned_runs;
      if (task.status === "completed" || task.status === "failed") {
        if (task.status === "completed") {
          const cid = task.campaign_id;
          setStatus("run-status", `Completed: ${task.completed_runs} runs recorded.`);
          el("plan-body").insertAdjacentHTML("beforeend",
            `<p><a class="button" href="/campaigns/${esc(cid)}">Open campaign ${esc(shortId(cid))}</a></p>`);
        } else {
          setStatus("run-status", `Failed: ${task.error ? esc(task.error.message) : "unknown error"}`, true);
        }
        return;
      }
      setStatus("run-status", `Running… ${task.completed_runs}${total ? " / " + total : ""} runs`);
      setTimeout(() => pollTaskUntilDone(taskId), 1500);
    } catch {
      setStatus("run-status", "Lost contact with campaign task (server restarted?). The campaign runs already recorded remain in the database.", true);
    }
  }
}

/* -- reports ------------------------------------------------------------------ */
async function initReports() {
  try {
    const data = await apiGet("/reports");
    el("reports-status").hidden = true;
    if (!data.reports.length) { el("reports-empty").hidden = false; return; }
    el("reports-wrap").hidden = false;
    tableRows("reports-table", data.reports.map(r => `<tr>
      <td><a href="/reports/${esc(r.report_id)}"><code>${esc(shortId(r.report_id))}</code></a></td>
      <td>${r.campaign_id ? `<a href="/campaigns/${esc(r.campaign_id)}"><code>${esc(shortId(r.campaign_id))}</code></a>` : "—"}</td>
      <td>${fmtTime(r.generated_at)}</td><td>${esc(r.formats.join(", "))}</td>
      <td>${r.source_run_count}</td>
      <td>${r.warnings && r.warnings.length ? `<span title="${esc(r.warnings.join("; "))}">${r.warnings.length}</span>` : "0"}</td></tr>`),
      6, "No reports.");
  } catch (err) {
    setStatus("reports-status", `${err.type}: ${err.message}`, true);
  }
}

async function initReportDetail() {
  const id = decodeURIComponent(location.pathname.split("/").pop());
  try {
    const data = await apiGet("/reports/" + encodeURIComponent(id));
    const report = data.report;
    el("report-status").hidden = true;
    el("report-detail").hidden = false;
    kvFill(el("report-kv"), [
      ["Campaign", report.campaign_id
        ? html(`<a href="/campaigns/${esc(report.campaign_id)}"><code>${esc(report.campaign_id)}</code></a>`) : "—"],
      ["Generated", fmtTime(report.generated_at)],
      ["VariaQ version", report.variaq_version],
      ["Report format version", report.report_format_version],
    ]);
    el("report-provenance").textContent =
      `${(report.source_run_ids || []).length} source runs · first runs: ${(report.source_run_ids || []).slice(0, 3).map(s => shortId(s)).join(", ") || "none"}`;
    tableRows("report-files-table", (data.files || []).map(f => `<tr>
      <td><code>${esc(f.name)}</code></td><td>${esc(f.format)}</td><td>${fmtBytes(f.size)}</td>
      <td><a href="/api/v1/reports/${esc(report.report_id)}/files/${encodeURIComponent(f.name)}" download>Download</a></td></tr>`),
      4, "No files for this report.");
  } catch (err) {
    setStatus("report-status", `${err.type}: ${err.message}`, true);
  }
}

/* -- capabilities ------------------------------------------------------------- */
async function initCapabilities() {
  try {
    const data = await apiGet("/capabilities");
    el("capabilities-status").hidden = true;
    el("capabilities").hidden = false;
    kvFill(el("cap-variaq"), [
      ["VariaQ version", data.variaq.version],
      ["Output schema version", data.variaq.output_schema_version],
      ["Python", data.variaq.python_version.split(" ")[0]],
      ["Implementation", data.variaq.python_implementation],
    ]);
    tableRows("cap-solvers-table", data.solvers.map(s => `<tr>
      <td>${esc(s.name)}</td><td>${boolText(s.supported)}</td><td>${boolText(s.installed)}</td>
      <td>${boolText(s.available)}</td>
      <td class="wrap-anywhere">${esc((s.supported_families || []).join(", ") || "—")}</td></tr>`),
      5, "No solvers.");
    const cudaq = (data.frameworks || []).find(f => f.name === "cudaq") || {};
    const qiskit = (data.frameworks || []).find(f => f.name === "qiskit") || {};
    const targets = cudaq.targets || {};
    kvFill(el("cap-frameworks"), [
      ["Qiskit", qiskit.version || "not installed"],
      ["CUDA-Q", cudaq.version || "not installed"],
      ["qpp-cpu available", boolText(Boolean(targets.qpp_cpu && targets.qpp_cpu.available))],
      ["NVIDIA target available", boolText(Boolean(targets.nvidia && targets.nvidia.available))],
      ["GPU count", targets.nvidia && targets.nvidia.gpu_count != null ? String(targets.nvidia.gpu_count) : "—"],
    ]);
    el("cap-qpu").textContent = data.physical_qpu.reason || "Physical QPU execution is not supported.";
    if (data.warnings && data.warnings.length) {
      el("cap-warnings-panel").hidden = false;
      el("cap-warnings").innerHTML = data.warnings.map(w => `<li>${esc(w.message)}</li>`).join("");
    }
  } catch (err) {
    setStatus("capabilities-status", `${err.type}: ${err.message}`, true);
  }
}

Object.assign(window, {});
const PAGE2 = {
  campaigns: initCampaigns,
  campaign_detail: initCampaignDetail,
  campaign_new: initCampaignNew,
  reports: initReports,
  report_detail: initReportDetail,
  capabilities: initCapabilities,
};
const page2 = window.VARIAQ_PAGE;
if (page2 && PAGE2[page2]) document.addEventListener("DOMContentLoaded", PAGE2[page2]);
})();
