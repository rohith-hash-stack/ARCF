"use strict";

const state = {
  repositoryRoot: null,
};

const el = (id) => document.getElementById(id);

function showError(message) {
  const banner = el("error-banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
}

function clearError() {
  el("error-banner").classList.add("hidden");
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : response.statusText;
    throw new Error(detail);
  }
  return body;
}

// --- Repository panel -------------------------------------------------

el("repo-source").addEventListener("change", (event) => {
  const isClone = event.target.value === "clone";
  el("local-fields").classList.toggle("hidden", isClone);
  el("clone-fields").classList.toggle("hidden", !isClone);
});

el("load-repo-btn").addEventListener("click", async () => {
  clearError();
  const source = el("repo-source").value;
  const payload = { source };
  if (source === "local") {
    payload.path = el("repo-path").value.trim();
  } else {
    payload.url = el("repo-url").value.trim();
    const ref = el("repo-ref").value.trim();
    if (ref) payload.ref = ref;
  }

  el("repo-status").textContent = "Loading repository...";
  el("load-repo-btn").disabled = true;
  try {
    const info = await api("/api/repository/load", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.repositoryRoot = info.root;
    el("repo-status").textContent = "Loaded.";
    renderRepoMeta(info);
    el("run-btn").disabled = false;
  } catch (err) {
    el("repo-status").textContent = "";
    showError(err.message);
  } finally {
    el("load-repo-btn").disabled = false;
  }
});

function renderRepoMeta(info) {
  const meta = el("repo-meta");
  const languages = info.languages
    .slice(0, 5)
    .map((l) => `${l.language} ${l.percentage}%`)
    .join(", ") || "none detected";
  const frameworks = info.frameworks.length ? info.frameworks.join(", ") : "none detected";
  meta.innerHTML = `
    <div><strong>${info.root}</strong></div>
    <div>Git repo: ${info.is_git_repo ? "yes" : "no"}${info.current_branch ? ` (${info.current_branch})` : ""}</div>
    <div>Files: ${info.file_count}</div>
    <div>Languages: ${languages}</div>
    <div>Frameworks: ${frameworks}</div>
  `;
  meta.classList.remove("hidden");
}

// --- Task panel ---------------------------------------------------------

el("example-tasks").addEventListener("click", (event) => {
  const task = event.target.getAttribute("data-task");
  if (task) el("task-input").value = task;
});

// --- Local SLM availability ---------------------------------------------

(async function checkLocalSlmStatus() {
  try {
    const status = await api("/api/local-slm/status");
    if (!status.available) {
      const warning = el("local-slm-warning");
      warning.textContent = `ARCF (Local SLM) unavailable: ${status.reason}`;
      warning.classList.remove("hidden");
    }
  } catch (err) {
    // Non-fatal: the warning is a convenience, not a gate.
  }
})();

// --- Run panel ------------------------------------------------------------

el("run-btn").addEventListener("click", async () => {
  clearError();
  const task = el("task-input").value.trim();
  if (!task) {
    showError("Enter a task before running the benchmark.");
    return;
  }
  if (!state.repositoryRoot) {
    showError("Load a repository first.");
    return;
  }

  const modeChoice = document.querySelector('input[name="mode"]:checked').value;
  const modes =
    modeChoice === "both"
      ? ["direct", "arcf"]
      : modeChoice === "all"
        ? ["direct", "arcf", "arcf_local"]
        : [modeChoice];
  const model = el("model-input").value.trim() || undefined;

  el("run-btn").disabled = true;
  el("run-status").textContent = "Running benchmark... this can take a while (real LLM calls).";
  el("results").classList.add("hidden");

  try {
    const result = await api("/api/benchmark/run", {
      method: "POST",
      body: JSON.stringify({
        repository_root: state.repositoryRoot,
        task,
        model,
        modes,
      }),
    });
    el("run-status").textContent = "Done.";
    renderResults(result);
  } catch (err) {
    el("run-status").textContent = "";
    showError(err.message);
  } finally {
    el("run-btn").disabled = false;
  }
});

// --- Results rendering ----------------------------------------------------

function fmtMoney(v) {
  return `$${v.toFixed(4)}`;
}

function fmtMs(v) {
  return v < 1000 ? `${v.toFixed(0)} ms` : `${(v / 1000).toFixed(2)} s`;
}

function runCard(label, cls, run) {
  if (!run) {
    return `<div class="run-card ${cls}"><h3>${label}</h3><p>Not run.</p></div>`;
  }
  const t = run.token_metrics;
  const l = run.latency_metrics;
  const c = run.cost_metrics;
  const ctx = run.context_metrics;

  let overheadRow = "";
  if (cls === "arcf" || cls === "arcf_local") {
    overheadRow = `
      <tr><td>Pipeline overhead (SLM-1)</td><td>${fmtMs(l.pipeline_overhead_ms)}</td></tr>
      <tr><td>Deterministic latency</td><td>${fmtMs(l.deterministic_ms)}</td></tr>
      <tr><td>Overhead cost</td><td>${fmtMoney(c.pipeline_overhead_cost_usd)}</td></tr>
    `;
  }

  let stageRows = "";
  if (l.stages) {
    const s = l.stages;
    stageRows = `
      <div class="metric-section">
        <table class="metric-table">
          <tr><td>Intent extraction (SLM-1)</td><td>${fmtMs(s.intent_extraction_ms)}</td></tr>
          <tr><td>Workspace scan</td><td>${fmtMs(s.workspace_scan_ms)}</td></tr>
          <tr><td>Code intelligence / context resolution</td><td>${fmtMs(s.code_intelligence_ms)}</td></tr>
          <tr><td>Context packaging</td><td>${fmtMs(s.context_packaging_ms)}</td></tr>
          <tr><td>Final LLM call</td><td>${fmtMs(s.final_llm_ms)}</td></tr>
        </table>
      </div>
    `;
  }

  const q = run.quality_metrics;

  return `
    <div class="run-card ${cls}">
      <h3>${label}</h3>
      <table class="metric-table">
        <tr><td>Input tokens</td><td>${t.input_tokens.toLocaleString()}</td></tr>
        <tr><td>Output tokens</td><td>${t.output_tokens.toLocaleString()}</td></tr>
        <tr><td>Total tokens</td><td>${t.total_tokens.toLocaleString()}</td></tr>
      </table>
      <div class="metric-section">
        <table class="metric-table">
          <tr><td>Total latency</td><td>${fmtMs(l.total_ms)}</td></tr>
          <tr><td>LLM latency</td><td>${fmtMs(l.llm_ms)}</td></tr>
          ${overheadRow}
        </table>
      </div>
      ${stageRows}
      <div class="metric-section">
        <table class="metric-table">
          <tr><td>Estimated cost</td><td>${fmtMoney(c.estimated_cost_usd)}</td></tr>
          <tr><td>Actual cost</td><td>${fmtMoney(c.actual_cost_usd)}</td></tr>
        </table>
      </div>
      <div class="metric-section">
        <table class="metric-table">
          <tr><td>Repository files</td><td>${ctx.repository_files.toLocaleString()}</td></tr>
          <tr><td>Candidate files</td><td>${ctx.candidate_files.toLocaleString()}</td></tr>
          <tr><td>Files sent to LLM</td><td>${ctx.files_sent_to_llm.toLocaleString()}</td></tr>
        </table>
      </div>
      <div class="metric-section">
        <table class="metric-table">
          <tr><td>Answer length</td><td>${q.answer_length.toLocaleString()} chars</td></tr>
          <tr><td>Modified files</td><td>${q.modified_files.length}</td></tr>
        </table>
      </div>
      <div class="output-preview">${escapeHtml(run.generated_output).slice(0, 4000)}</div>
    </div>
  `;
}

function summaryItem(label, value, cls) {
  return `<div class="summary-item"><div class="value ${cls || ""}">${value}</div><div class="label">${label}</div></div>`;
}

function pctClass(v) {
  if (v === null || v === undefined) return "";
  return v > 0 ? "good" : v < 0 ? "bad" : "";
}

function renderResults(result) {
  el("comparison").innerHTML =
    runCard("Direct LLM", "direct", result.direct) +
    runCard("ARCF (Remote SLM)", "arcf", result.arcf) +
    runCard("ARCF (Local SLM)", "arcf_local", result.arcf_local);

  const summary = el("summary");
  let summaryHtml = "";

  if (result.direct && result.arcf) {
    const tr = result.token_reduction_pct;
    const lr = result.latency_reduction_pct;
    const cr = result.cost_reduction_pct;
    summaryHtml += `
      <h3>Direct vs ARCF Remote</h3>
      <div class="summary-grid">
        ${summaryItem("Token reduction", tr === null ? "n/a" : `${tr}%`, pctClass(tr))}
        ${summaryItem("Latency reduction", lr === null ? "n/a" : `${lr}%`, pctClass(lr))}
        ${summaryItem("Cost reduction", cr === null ? "n/a" : `${cr}%`, pctClass(cr))}
        ${summaryItem("CER", result.context_efficiency_ratio === null ? "n/a" : `${(result.context_efficiency_ratio * 100).toFixed(1)}%`)}
        ${summaryItem("PCR", result.prompt_compression_ratio === null ? "n/a" : `${result.prompt_compression_ratio}x`)}
      </div>
    `;
  }

  if (result.direct && result.arcf_local) {
    const tr = result.local_token_reduction_pct;
    const lr = result.local_latency_reduction_pct;
    const cr = result.local_cost_reduction_pct;
    summaryHtml += `
      <h3>Direct vs ARCF Local</h3>
      <div class="summary-grid">
        ${summaryItem("Token reduction", tr === null ? "n/a" : `${tr}%`, pctClass(tr))}
        ${summaryItem("Latency reduction", lr === null ? "n/a" : `${lr}%`, pctClass(lr))}
        ${summaryItem("Cost reduction", cr === null ? "n/a" : `${cr}%`, pctClass(cr))}
        ${summaryItem("CER", result.local_context_efficiency_ratio === null ? "n/a" : `${(result.local_context_efficiency_ratio * 100).toFixed(1)}%`)}
        ${summaryItem("PCR", result.local_prompt_compression_ratio === null ? "n/a" : `${result.local_prompt_compression_ratio}x`)}
      </div>
    `;
  }

  if (result.arcf && result.arcf_local) {
    const lvr = result.local_vs_remote_latency_reduction_pct;
    summaryHtml += `
      <h3>Local vs Remote SLM-1 (the hypothesis)</h3>
      <div class="summary-grid">
        ${summaryItem("Latency reduction", lvr === null ? "n/a" : `${lvr}%`, pctClass(lvr))}
      </div>
    `;
  }

  if (summaryHtml) {
    summary.innerHTML = summaryHtml;
    summary.classList.remove("hidden");
  } else {
    summary.classList.add("hidden");
  }

  el("results").classList.remove("hidden");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
