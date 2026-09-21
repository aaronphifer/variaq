/* VariaQ local web UI. All scientific values come from the VariaQ API;
   this layer only formats and presents them. */
"use strict";

const API = "/api/v1";

function el(id) { return document.getElementById(id); }

async function apiGet(path) {
  const res = await fetch(API + path, { headers: { Accept: "application/json" } });
  return handle(res);
}
async function apiPost(path, body) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  return handle(res);
}
async function handle(res) {
  let payload = null;
  try { payload = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    const detail = payload && payload.error ? payload.error
      : payload && payload.detail ? (typeof payload.detail === "string" ? { message: payload.detail } : payload.detail)
      : { type: "HttpError", message: "Request failed with status " + res.status };
    const err = new Error(detail.message || "request failed");
    err.type = detail.type || "HttpError";
    err.details = detail.details || null;
    throw err;
  }
  return payload;
}

function fmtNum(v, digits = 6) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toPrecision(digits).replace(/\.?0+$e/, "e");
}
function fmtTime(v) { return v === null || v === undefined ? "—" : String(v).replace("T", " ").slice(0, 19); }
function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KiB", "MiB", "GiB"];
  let v = n, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function shortId(id) { return String(id).length > 24 ? String(id).slice(0, 12) + "…" + String(id).slice(-6) : id; }

function statusPill(status) {
  const cls = status === "success" ? "status-success" : status === "failed" ? "status-failed" : "status-unavailable";
  return `<span class="${cls}">${esc(status)}</span>`;
}
function boolText(v) {
  if (v === null || v === undefined) return "—";
  return v ? "yes" : "no";
}

// Mark up only HTML assembled here from already-escaped values. API strings are
// text by default in kvFill, so callers cannot accidentally introduce markup.
function html(value) { return { variaqSafeHtml: String(value) }; }

function isQuantumResult(r, m) {
  return Boolean(
    m.qubit_count != null || m.optimized_expected_objective != null ||
    m.feasible_sample_count != null || m.qaoa_depth_p != null
  );
}

function setStatus(id, msg, isError) {
  const node = el(id);
  if (!node) return;
  node.textContent = msg;
  node.classList.toggle("error", Boolean(isError));
  node.hidden = !msg;
}

function kvFill(node, entries) {
  node.innerHTML = entries
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => {
      let rendered = "—";
      if (v && typeof v === "object" && Object.hasOwn(v, "variaqSafeHtml")) {
        rendered = v.variaqSafeHtml;
      } else if (v !== null) {
        rendered = esc(v);
      }
      return `<dt>${esc(k)}</dt><dd>${rendered}</dd>`;
    })
    .join("");
}

function tableRows(tableId, rowsHtml, emptyColspan, emptyText) {
  const tbody = el(tableId).querySelector("tbody");
  tbody.innerHTML = rowsHtml.length
    ? rowsHtml.join("")
    : `<tr><td colspan="${emptyColspan}" class="muted">${esc(emptyText)}</td></tr>`;
}

/* -- dashboard -------------------------------------------------------------- */
async function initDashboard() {
  try {
    const data = await apiGet("/overview");
    el("dashboard-status").hidden = true;
    el("dashboard").hidden = false;
    const v = document.querySelector("#app-version");
    if (v) v.textContent = `VariaQ ${data.variaq_version} · database ${data.database_name}`;
    el("stat-problems").textContent = data.counts.problems;
    el("stat-runs").textContent = data.counts.runs;
    el("stat-campaigns").textContent = data.counts.campaigns;
    el("stat-reports").textContent = data.counts.reports;
    if (data.counts.runs === 0 && data.counts.campaigns === 0) el("empty-hint").hidden = false;

    tableRows("recent-runs-table", data.recent_runs.map(r => `<tr>
      <td><a href="/runs/${esc(r.run_id)}" title="${esc(r.run_id)}">${esc(shortId(r.run_id))}</a></td>
      <td>${esc(r.solver_name)}</td><td>${statusPill(r.status)}</td>
      <td>${fmtNum(r.objective)}</td><td>${fmtNum(r.wall_time_seconds, 4)}</td></tr>`), 5, "No runs yet.");

    el("recent-campaigns-list").innerHTML = data.recent_campaigns.length
      ? data.recent_campaigns.map(c => `<li><a href="/campaigns/${esc(c.campaign_id)}"><code>${esc(shortId(c.campaign_id))}</code></a> ${esc(c.name)} <span class="muted">(${esc(c.family)})</span></li>`).join("")
      : `<li class="muted">No campaigns yet.</li>`;

    const solvers = Object.entries(data.solver_availability);
    tableRows("solver-state-table", solvers.map(([name, s]) =>
      `<tr><td>${esc(name)}</td><td>${boolText(s.installed)}</td><td>${boolText(s.available)}</td></tr>`), 3, "No solvers.");
    const c = data.cudaq || {};
    const targets = c.targets || {};
    kvFill(el("backend-facts"), [
      ["CUDA-Q installed", boolText(Boolean(c.installed))],
      ["qpp-cpu available", boolText(Boolean(targets.qpp_cpu && targets.qpp_cpu.available))],
      ["NVIDIA target available", boolText(Boolean(targets.nvidia && targets.nvidia.available))],
      ["GPU count", targets.nvidia && targets.nvidia.gpu_count != null ? targets.nvidia.gpu_count : "—"],
    ]);
    el("qpu-state").textContent = `Physical QPU: ${data.physical_qpu.reason || "not supported"}`;
  } catch (err) {
    setStatus("dashboard-status", `${err.type}: ${err.message}`, true);
  }
}

/* -- problems --------------------------------------------------------------- */
async function initProblems() {
  const form = el("problem-filters");
  async function load() {
    const params = new URLSearchParams();
    const family = form.family.value, search = form.search.value.trim();
    if (family) params.set("family", family);
    if (search) params.set("search", search);
    try {
      const data = await apiGet("/problems?" + params);
      el("problems-status").hidden = true;
      el("problems-wrap").hidden = false;
      tableRows("problems-table", data.problems.map(p => `<tr>
        <td><a href="/problems/${esc(p.problem_id)}" title="${esc(p.problem_id)}"><code>${esc(shortId(p.problem_id))}</code></a></td>
        <td>${esc(p.problem_type)}</td><td>${esc(sizeText(p))}</td><td>${esc(p.sense || "—")}</td>
        <td>${p.run_count}</td><td>${fmtTime(p.created_at)}</td></tr>`), 6, "No problems match.");
      el("problems-count").textContent = `${data.total} problem(s)`;
    } catch (err) {
      setStatus("problems-status", `${err.type}: ${err.message}`, true);
    }
  }
  form.addEventListener("submit", e => { e.preventDefault(); load(); });
  load();
}
function sizeText(p) {
  const s = p.size || {};
  const parts = Object.entries(s).map(([k, v]) => `${k}=${v}`);
  return parts.join(" ") || "—";
}

/* -- problem detail --------------------------------------------------------- */
async function initProblemDetail() {
  const id = document.querySelector("[data-problem-id]")?.dataset.problemId
    || decodeURIComponent(location.pathname.split("/").pop());
  try {
    const data = await apiGet("/problems/" + encodeURIComponent(id));
    el("problem-status").hidden = true;
    el("problem-detail").hidden = false;
    const def = data.definition;
    const meta = data.metadata;
    kvFill(el("problem-kv"), [
      ["Family", data.family],
      ["Sense", data.sense || "—"],
      ["Size", sizeText(meta)],
      ["Exact objective", fmtNum(data.exact_objective)],
      ["Variable count", def.dimensions ? JSON.stringify(def.dimensions) : (def.nodes || "—")],
      ["Created", fmtTime(meta.created_at)],
    ]);
    el("problem-definition").textContent = JSON.stringify(def, null, 2);
    const runs = data.runs.runs;
    tableRows("problem-runs-table", runs.map(r => `<tr>
      <td><a href="/runs/${esc(r.run_id)}">${esc(shortId(r.run_id))}</a></td>
      <td>${esc(r.solver_name)}</td><td>${statusPill(r.status)}</td>
      <td>${fmtNum(r.objective)}</td><td>${boolText(r.feasible)}</td>
      <td>${fmtNum(r.wall_time_seconds, 4)}</td></tr>`), 6, "No runs on this problem.");
    el("problem-campaigns-list").innerHTML = data.campaigns.length
      ? data.campaigns.map(c => `<li><a href="/campaigns/${esc(c.campaign_id)}"><code>${esc(shortId(c.campaign_id))}</code></a> ${esc(c.name)}</li>`).join("")
      : `<li class="muted">Not part of any campaign.</li>`;
  } catch (err) {
    setStatus("problem-status", `${err.type}: ${err.message}`, true);
  }
}

/* -- runs ------------------------------------------------------------------- */
async function initRuns() {
  const form = el("run-filters");
  const state = { offset: 0, limit: 50 };
  async function load() {
    const params = new URLSearchParams();
    for (const key of ["family", "solver", "backend", "status", "campaign_id"]) {
      const v = form[key].value.trim();
      if (v) params.set(key, v);
    }
    params.set("limit", state.limit);
    params.set("offset", state.offset);
    setStatus("runs-status", "Loading…");
    try {
      const data = await apiGet("/runs?" + params);
      el("runs-status").hidden = true;
      el("runs-wrap").hidden = false;
      tableRows("runs-table", data.runs.map(r => `<tr>
        <td><a href="/runs/${esc(r.run_id)}" title="${esc(r.run_id)}"><code>${esc(shortId(r.run_id))}</code></a></td>
        <td>${fmtTime(r.created_at)}</td><td>${esc(r.problem_type)}</td>
        <td><a href="/problems/${esc(r.problem_id)}"><code>${esc(shortId(r.problem_id))}</code></a></td>
        <td>${esc(r.solver_name)}</td><td>${esc(r.backend_name)}</td>
        <td>${statusPill(r.status)}</td><td>${fmtNum(r.objective)}</td>
        <td>${boolText(r.feasible)}</td><td>${fmtNum(r.wall_time_seconds, 4)}</td></tr>`),
        10, "No runs match the filters.");
      const from = data.total === 0 ? 0 : data.offset + 1;
      const to = Math.min(data.offset + data.limit, data.total);
      el("runs-page-info").textContent = `${from}–${to} of ${data.total}`;
      el("runs-prev").disabled = data.offset === 0;
      el("runs-next").disabled = data.offset + data.limit >= data.total;
    } catch (err) {
      setStatus("runs-status", `${err.type}: ${err.message}`, true);
    }
  }
  form.addEventListener("submit", e => { e.preventDefault(); state.offset = 0; load(); });
  el("runs-prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); load(); });
  el("runs-next").addEventListener("click", () => { state.offset += state.limit; load(); });
  load();
}

/* -- run detail ------------------------------------------------------------- */
async function initRunDetail() {
  const id = decodeURIComponent(location.pathname.split("/").pop());
  try {
    const run = await apiGet("/runs/" + encodeURIComponent(id));
    el("run-status").hidden = true;
    el("run-detail").hidden = false;
    const r = run.result, m = r.backend.metrics || {};
    const messages = el("run-messages");
    const warnings = (r.warnings || []).slice(0, 10);
    const errors = (r.errors || []).slice(0, 10);
    if (warnings.length || errors.length) {
      messages.hidden = false;
      messages.innerHTML = [
        warnings.length ? `<div class="notice warn"><strong>Warnings</strong><ul>${warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul></div>` : "",
        errors.length ? `<div class="notice error" role="alert"><strong>Run errors</strong><ul>${errors.map(error => `<li>${esc(error)}</li>`).join("")}</ul></div>` : "",
      ].join("");
    }
    kvFill(el("run-result-kv"), [
      ["Status", r.status],
      ["Solver", `${r.solver_name} ${r.solver_version}`],
      ["Problem family", r.problem_type],
      ["Objective (decoded solution)", fmtNum(r.objective)],
      ["Feasible", boolText(r.feasible)],
      ["Best known objective", fmtNum(r.best_known_objective)],
      ["Best known source", r.best_known_source || "—"],
      ["Optimality gap %", fmtNum(r.optimality_gap_percent, 4)],
      ["Approximation ratio", fmtNum(r.approximation_ratio, 4)],
      ["Wall time s", fmtNum(r.wall_time_seconds, 5)],
      ["Solver time s", fmtNum(r.solver_time_seconds, 5)],
    ]);
    el("run-solution").textContent = r.solution === null ? "no solution" : JSON.stringify(r.solution);

    if (isQuantumResult(r, m)) {
      el("run-quantum-panel").hidden = false;
      kvFill(el("run-quantum-kv"), [
        ["Expectation (optimized candidate)", fmtNum(m.optimized_expected_objective)],
        ["BQM energy, best decoded sample (lowered)", fmtNum(m.best_solution_energy)],
        ["Best infeasible BQM energy", fmtNum(m.best_infeasible_energy)],
        ["Feasible samples", m.feasible_sample_count ?? "—"],
        ["Infeasible samples", m.infeasible_sample_count ?? "—"],
        ["Binary variables", m.binary_variable_count ?? "—"],
        ["Qubits", m.qubit_count ?? "—"],
        ["QAOA depth p", m.qaoa_depth_p ?? "—"],
        ["Shots", m.shots ?? "—"],
        ["Optimizer", m.optimizer ? `${m.optimizer} (${m.optimizer_trials ?? "?"} trials)` : "—"],
        ["Unique sampled states", m.sampled_unique_states ?? "—"],
        ["Circuit depth (logical)", m.circuit_depth ?? "—"],
        ["Gate count (logical)", m.logical_gate_count ?? "—"],
      ]);
    }

    const timingEntries = [
      ["Backend initialization s", fmtNum(m.backend_initialization_seconds, 5)],
      ["Expectation evaluation s", fmtNum(m.expectation_evaluation_seconds, 5)],
      ["Parameter search s", fmtNum(m.parameter_search_seconds, 5)],
      ["Final sampling s", fmtNum(m.final_sampling_seconds, 5)],
      ["Warmup s", fmtNum(m.warmup_seconds, 5)],
    ].filter(([, v]) => v !== "—");
    kvFill(el("run-backend-kv"), [
      ["Framework", m.framework || r.backend.backend_type],
      ["Backend", r.backend.name],
      ["Backend type", r.backend.backend_type],
      ["Provider", r.backend.provider],
      ["Local", boolText(r.backend.is_local)],
      ["Precision", m.floating_point_precision || "—"],
      ["Versions", Object.entries(r.backend.versions || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "—"],
      ...timingEntries,
    ]);
    const campaigns = run.campaigns || [];
    kvFill(el("run-prov-kv"), [
      ["Problem", html(`<a href="/problems/${esc(run.problem.problem_id)}"><code>${esc(run.problem.problem_id)}</code></a>`)],
      ["Problem family / sense", `${run.problem.family} / ${run.problem.sense}`],
      ["Campaigns", campaigns.length
        ? html(campaigns.map(c => `<a href="/campaigns/${esc(c.campaign_id)}"><code>${esc(shortId(c.campaign_id))}</code></a> ${esc(c.name)}`).join(", "))
        : "—"],
      ["Rerun of", run.rerun_of ? html(`<a href="/runs/${esc(run.rerun_of)}"><code>${esc(run.rerun_of)}</code></a>`) : "—"],
      ["Seed", run.solver_config.seed],
      ["VariaQ version", (run.environment.packages && run.environment.packages.variaq) || "—"],
      ["Created", fmtTime(run.created_at)],
    ]);
  } catch (err) {
    setStatus("run-status", `${err.type}: ${err.message}`, true);
  }
}

window.VARIAQ = { apiGet, apiPost, esc, html, fmtNum, fmtTime, fmtBytes, shortId, statusPill, boolText, setStatus, kvFill, tableRows };

const PAGES = {
  dashboard: initDashboard,
  problems: initProblems,
  problem_detail: initProblemDetail,
  runs: initRuns,
  run_detail: initRunDetail,
};
const page = window.VARIAQ_PAGE;
if (page && PAGES[page]) document.addEventListener("DOMContentLoaded", PAGES[page]);
