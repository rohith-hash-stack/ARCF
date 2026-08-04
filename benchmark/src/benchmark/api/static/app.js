"use strict";

const state = {
  repositoryRoot: null,
  lastResult: null,
  historyEntries: [],
  selectedHistoryIds: [],
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
  let response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (networkErr) {
    // fetch() itself throws (TypeError) for a connection-level failure —
    // server not running, wrong port, CORS, etc. — distinct from the
    // server responding with an HTTP error, which is handled below.
    throw new Error(
      `Could not reach the ARCF Benchmark API at ${path}. Is the server running ` +
      `(\`uvicorn benchmark.api.app:app\`)? (${networkErr.message})`
    );
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : response.statusText;
    throw new Error(detail);
  }
  return body;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
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
    <div><strong>${escapeHtml(info.root)}</strong></div>
    <div>Git repo: ${info.is_git_repo ? "yes" : "no"}${info.current_branch ? ` (${escapeHtml(info.current_branch)})` : ""}</div>
    <div>Files: ${info.file_count}</div>
    <div>Languages: ${escapeHtml(languages)}</div>
    <div>Frameworks: ${escapeHtml(frameworks)}</div>
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

// --- Provider dropdown ---------------------------------------------------

(async function loadProviders() {
  try {
    const providers = await api("/api/providers");
    const select = el("provider-select");
    for (const p of providers) {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = `${p.name}${p.available ? "" : " (unavailable)"}`;
      select.appendChild(opt);
    }
  } catch (err) {
    // Non-fatal: providers are optional (--model still works unresolved).
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
  const provider = el("provider-select").value || undefined;

  el("run-btn").disabled = true;
  el("run-status").textContent = "Running benchmark... this can take a while (real LLM calls).";
  el("results").classList.add("hidden");
  el("charts-section").classList.add("hidden");
  el("diff-section").classList.add("hidden");

  try {
    const result = await api("/api/benchmark/run", {
      method: "POST",
      body: JSON.stringify({
        repository_root: state.repositoryRoot,
        task,
        model,
        provider,
        modes,
      }),
    });
    el("run-status").textContent = "Done.";
    state.lastResult = result;
    renderResults(result);
    renderCharts(result);
    renderDiffViewer(result);
  } catch (err) {
    el("run-status").textContent = "";
    showError(err.message);
  } finally {
    el("run-btn").disabled = false;
    refreshHistory();
  }
});

// --- Formatting helpers -----------------------------------------------------

function fmtMoney(v) {
  return `$${v.toFixed(4)}`;
}

function fmtMs(v) {
  return v < 1000 ? `${v.toFixed(0)} ms` : `${(v / 1000).toFixed(2)} s`;
}

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch (err) {
    return iso;
  }
}

let detailIdCounter = 0;
function nextDetailId() {
  detailIdCounter += 1;
  return `detail-${detailIdCounter}`;
}

function detailBlock(title, bodyHtml) {
  const id = nextDetailId();
  return `
    <button type="button" class="detail-toggle" data-target="${id}">▸ ${escapeHtml(title)}</button>
    <div class="detail-block hidden" id="${id}">${bodyHtml}</div>
  `;
}

function listOrNone(items) {
  if (!items || items.length === 0) return "<p>(none)</p>";
  return `<ul>${items.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`;
}

// --- Side-by-Side Comparison rendering --------------------------------------

function statusPill(status) {
  const cls = status || "unknown";
  return `<span class="status-pill ${cls}">${escapeHtml(status || "unknown")}</span>`;
}

function runCard(label, cls, run) {
  if (!run) {
    return `
      <div class="run-card ${cls}">
        <h3>${label}</h3>
        <p>Not run, or failed — check Execution History below for the failure record.</p>
      </div>
    `;
  }
  const t = run.token_metrics;
  const l = run.latency_metrics;
  const c = run.cost_metrics;
  const ctx = run.context_metrics;
  const q = run.quality_metrics;

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

  let contractDetail = "";
  if (run.contract) {
    const intent = run.contract.intent || {};
    contractDetail = detailBlock(
      "Execution contract",
      `
        <div><strong>Intent:</strong> ${escapeHtml(intent.intent)}</div>
        <div><strong>Domain:</strong> ${escapeHtml(intent.domain)} / <strong>Task:</strong> ${escapeHtml(intent.task)}</div>
        <div><strong>Entities:</strong> ${escapeHtml((intent.entities || []).join(", ") || "(none)")}</div>
        <div><strong>Success criteria:</strong></div>
        ${listOrNone(run.contract.success_criteria)}
      `
    );
  }

  let symbolsDetail = "";
  if (run.context_resolution) {
    const symbols = (run.context_resolution.entry_points || []).map(
      (s) => `${s.qualified_name} (${s.kind})`
    );
    symbolsDetail = detailBlock("Selected symbols", listOrNone(symbols));
  }

  let dependencyDetail = "";
  if (run.context_resolution) {
    const edges = (run.context_resolution.dependency_chain || []).map(
      (e) => `${e.from_file} → ${e.to_file}`
    );
    dependencyDetail = detailBlock(
      `Dependency graph summary (${edges.length} edge${edges.length === 1 ? "" : "s"})`,
      listOrNone(edges)
    );
  }

  let contextPackageDetail = "";
  if (run.context_package) {
    const cp = run.context_package;
    contextPackageDetail = detailBlock(
      "Context package",
      `
        <div>Budget used: ${cp.budget_used_tokens.toLocaleString()} tokens</div>
        <div>Prompt compression ratio: ${cp.prompt_compression_ratio}x</div>
        <div>Excluded files: ${cp.excluded_file_count}</div>
        <div><strong>Understanding notes:</strong></div>
        ${listOrNone(cp.understanding_notes)}
      `
    );
  }

  const referencedFilesDetail = detailBlock(
    `Files referenced (${(run.referenced_files || []).length})`,
    listOrNone(run.referenced_files)
  );
  const modifiedFilesDetail = detailBlock(
    `Files modified (${(q.modified_files || []).length})`,
    listOrNone(q.modified_files)
  );
  const promptDetail = detailBlock(
    "Full prompt",
    `<div class="output-preview">${escapeHtml(run.prompt || "(prompt not captured on RunResult; see Execution History for the recorded prompt)")}</div>`
  );

  return `
    <div class="run-card ${cls}">
      <h3>${label} ${statusPill("success")}</h3>
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
          <tr><td>Files modified</td><td>${(q.modified_files || []).length}</td></tr>
          <tr><td>Lines changed</td><td>${q.lines_changed != null ? q.lines_changed.toLocaleString() : "n/a"}</td></tr>
        </table>
      </div>
      <div class="metric-section">
        ${promptDetail}
        ${referencedFilesDetail}
        ${modifiedFilesDetail}
        ${contractDetail}
        ${symbolsDetail}
        ${dependencyDetail}
        ${contextPackageDetail}
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

  document.querySelectorAll(".detail-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = el(btn.getAttribute("data-target"));
      const isHidden = target.classList.toggle("hidden");
      btn.textContent = btn.textContent.replace(/^./, isHidden ? "▸" : "▾");
    });
  });

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

// --- Metrics Visualization (inline SVG bar charts, no dependencies) --------

function svgBarChart(bars, opts) {
  const width = 240;
  const barHeight = 22;
  const gap = 10;
  const labelWidth = 90;
  const height = bars.length * (barHeight + gap) + gap;
  const maxValue = Math.max(...bars.map((b) => Math.abs(b.value)), opts && opts.max ? opts.max : 0, 1e-9);
  const trackWidth = width - labelWidth - 10;

  const rows = bars
    .map((b, i) => {
      const y = gap + i * (barHeight + gap);
      const w = Math.max((Math.abs(b.value) / maxValue) * trackWidth, 1);
      const display = b.display != null ? b.display : String(b.value);
      return `
        <text x="0" y="${y + barHeight / 2 + 4}" class="chart-bar-label">${escapeHtml(b.label)}</text>
        <rect x="${labelWidth}" y="${y}" width="${trackWidth}" height="${barHeight}" fill="var(--panel-border)" rx="3"></rect>
        <rect x="${labelWidth}" y="${y}" width="${w}" height="${barHeight}" fill="${b.color || "var(--accent)"}" rx="3"></rect>
        <text x="${labelWidth + trackWidth + 6}" y="${y + barHeight / 2 + 4}" class="chart-value-label">${escapeHtml(display)}</text>
      `;
    })
    .join("");

  return `<svg viewBox="0 0 ${width + 40} ${height}" xmlns="http://www.w3.org/2000/svg">${rows}</svg>`;
}

function chartCard(title, innerSvg, caption) {
  return `
    <div class="chart-card">
      <h4>${escapeHtml(title)}</h4>
      ${innerSvg}
      ${caption ? `<div class="status-line" style="margin-top:6px">${escapeHtml(caption)}</div>` : ""}
    </div>
  `;
}

function renderCharts(result) {
  const cards = [];

  if (result.direct && result.arcf) {
    cards.push(
      chartCard(
        "Total tokens: Direct vs ARCF",
        svgBarChart([
          { label: "Direct", value: result.direct.token_metrics.total_tokens, color: "var(--direct-color)", display: result.direct.token_metrics.total_tokens.toLocaleString() },
          { label: "ARCF", value: result.arcf.token_metrics.total_tokens, color: "var(--arcf-color)", display: result.arcf.token_metrics.total_tokens.toLocaleString() },
        ])
      )
    );
    cards.push(
      chartCard(
        "Total latency: Direct vs ARCF",
        svgBarChart([
          { label: "Direct", value: result.direct.latency_metrics.total_ms, color: "var(--direct-color)", display: fmtMs(result.direct.latency_metrics.total_ms) },
          { label: "ARCF", value: result.arcf.latency_metrics.total_ms, color: "var(--arcf-color)", display: fmtMs(result.arcf.latency_metrics.total_ms) },
        ])
      )
    );
    cards.push(
      chartCard(
        "Actual cost: Direct vs ARCF",
        svgBarChart([
          { label: "Direct", value: result.direct.cost_metrics.actual_cost_usd, color: "var(--direct-color)", display: fmtMoney(result.direct.cost_metrics.actual_cost_usd) },
          { label: "ARCF", value: result.arcf.cost_metrics.actual_cost_usd, color: "var(--arcf-color)", display: fmtMoney(result.arcf.cost_metrics.actual_cost_usd) },
        ])
      )
    );

    const cer = result.context_efficiency_ratio;
    cards.push(
      chartCard(
        "Context Efficiency Ratio (CER)",
        svgBarChart([{ label: "CER", value: cer === null ? 0 : cer * 100, max: 100, display: cer === null ? "n/a" : `${(cer * 100).toFixed(1)}%` }]),
        "arcf.files_sent_to_llm / direct.files_sent_to_llm — lower is more selective."
      )
    );

    const pcr = result.prompt_compression_ratio;
    cards.push(
      chartCard(
        "Prompt Compression Ratio (PCR)",
        svgBarChart([{ label: "PCR", value: pcr === null ? 0 : pcr, max: Math.max(pcr || 1, 4), display: pcr === null ? "n/a" : `${pcr}x` }]),
        "direct.input_tokens / arcf.input_tokens — higher means ARCF's prompt is smaller."
      )
    );
  }

  el("charts-grid").innerHTML = cards.join("") || "<p>Run Direct + ARCF together to see comparison charts.</p>";
  el("charts-section").classList.remove("hidden");
}

// --- Diff Viewer -----------------------------------------------------------

function isUnifiedDiff(text) {
  return /^(diff --git |--- |\+\+\+ )/m.test(text);
}

function renderDiffLines(text) {
  const lines = text.split("\n");
  return lines
    .map((line) => {
      let cls = "";
      if (/^diff --git |^index |^--- |^\+\+\+ /.test(line)) cls = "file-header";
      else if (/^@@/.test(line)) cls = "hunk";
      else if (/^\+/.test(line)) cls = "add";
      else if (/^-/.test(line)) cls = "del";
      return `<div class="diff-line ${cls}">${escapeHtml(line) || "&nbsp;"}</div>`;
    })
    .join("");
}

function isFileBlockFormat(text) {
  return /^### \S+/m.test(text);
}

function renderFileBlocks(text) {
  const re = /^### (\S+)\r?\n```[^\n]*\r?\n([\s\S]*?)\r?\n```/gm;
  let match;
  let html = "";
  let found = false;
  while ((match = re.exec(text)) !== null) {
    found = true;
    html += `<div class="diff-line file-header">${escapeHtml(match[1])}</div>`;
    html += match[2]
      .split("\n")
      .map((line) => `<div class="diff-line">${escapeHtml(line) || "&nbsp;"}</div>`)
      .join("");
  }
  return found ? html : null;
}

function diffContentFor(run) {
  if (!run || !run.generated_output) {
    return '<div class="diff-empty">No output.</div>';
  }
  const text = run.generated_output;
  if (isUnifiedDiff(text)) {
    return renderDiffLines(text);
  }
  const blocks = isFileBlockFormat(text) ? renderFileBlocks(text) : null;
  if (blocks) {
    return blocks;
  }
  return `<div class="diff-line">${escapeHtml(text)
    .split("\n")
    .join('</div><div class="diff-line">')}</div>`;
}

function renderDiffViewer(result) {
  const tabs = [
    { key: "direct", label: "Direct LLM", run: result.direct },
    { key: "arcf", label: "ARCF (Remote)", run: result.arcf },
    { key: "arcf_local", label: "ARCF (Local)", run: result.arcf_local },
  ].filter((t) => t.run);

  if (tabs.length === 0) {
    el("diff-section").classList.add("hidden");
    return;
  }

  el("diff-tabs").innerHTML = tabs
    .map((t, i) => `<button type="button" class="diff-tab${i === 0 ? " active" : ""}" data-key="${t.key}">${escapeHtml(t.label)}</button>`)
    .join("");

  const showTab = (key) => {
    const tab = tabs.find((t) => t.key === key) || tabs[0];
    el("diff-view").innerHTML = diffContentFor(tab.run);
    document.querySelectorAll(".diff-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-key") === tab.key);
    });
  };

  document.querySelectorAll(".diff-tab").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.getAttribute("data-key")));
  });

  showTab(tabs[0].key);
  el("diff-section").classList.remove("hidden");
}

// --- Execution History -------------------------------------------------

async function refreshHistory() {
  const search = el("history-search").value.trim();
  const mode = el("history-mode-filter").value;
  const params = new URLSearchParams({ limit: "50" });
  if (search) params.set("search", search);
  if (mode) params.set("mode", mode);

  try {
    const entries = await api(`/api/executions?${params.toString()}`);
    state.historyEntries = entries;
    state.selectedHistoryIds = [];
    renderHistoryTable(entries);
    renderHistorySummary(entries);
  } catch (err) {
    el("history-table-body").innerHTML = "";
    el("history-summary").textContent = `Failed to load history: ${err.message}`;
  }
}

function renderHistorySummary(entries) {
  const summary = el("history-summary");
  if (entries.length === 0) {
    summary.innerHTML = "<span>No executions recorded yet.</span>";
    return;
  }

  const withTestResult = entries.filter((e) => e.test_result === "passed" || e.test_result === "failed");
  const successRate = withTestResult.length
    ? `${((withTestResult.filter((e) => e.test_result === "passed").length / withTestResult.length) * 100).toFixed(0)}%`
    : "n/a (no build/test results recorded yet)";

  const arcfEntries = entries.filter((e) => e.mode === "arcf" && (e.selected_files || []).length);
  let groundingLabel = "n/a";
  if (arcfEntries.length) {
    const scores = arcfEntries.map((e) => {
      const selected = new Set(e.selected_files);
      const changed = e.files_changed || [];
      const overlap = changed.filter((f) => selected.has(f)).length;
      return selected.size ? overlap / selected.size : 0;
    });
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    groundingLabel = `${(avg * 100).toFixed(0)}% (heuristic)`;
  }

  const executionErrors = entries.filter((e) => e.execution_status !== "success").length;

  summary.innerHTML = `
    <span><strong>${entries.length}</strong> execution(s)</span>
    <span><strong>${entries.length - executionErrors}</strong> succeeded, <strong>${executionErrors}</strong> failed</span>
    <span>Task success rate: <strong>${successRate}</strong></span>
    <span>Repository grounding score: <strong>${groundingLabel}</strong></span>
  `;
}

function renderHistoryTable(entries) {
  const body = el("history-table-body");
  if (entries.length === 0) {
    body.innerHTML = `<tr><td colspan="11" class="history-empty">No executions match the current filter.</td></tr>`;
    return;
  }

  body.innerHTML = entries
    .map(
      (e) => `
      <tr data-id="${e.request_id}">
        <td><input type="checkbox" class="history-select" data-id="${e.request_id}" /></td>
        <td>${escapeHtml(fmtDate(e.created_at))}</td>
        <td>${escapeHtml(e.mode)}</td>
        <td>${escapeHtml(e.model)}</td>
        <td>${escapeHtml(e.provider || "—")}</td>
        <td>${statusPill(e.execution_status)}</td>
        <td>${e.total_tokens.toLocaleString()}</td>
        <td>${fmtMs(e.latency_ms)}</td>
        <td>${fmtMoney(e.estimated_cost_usd)}</td>
        <td>${(e.files_changed || []).length}</td>
        <td>${e.lines_changed != null ? e.lines_changed : "n/a"}</td>
      </tr>
    `
    )
    .join("");

  document.querySelectorAll(".history-select").forEach((cb) => {
    cb.addEventListener("change", onHistorySelectionChange);
  });
}

function onHistorySelectionChange() {
  const checked = Array.from(document.querySelectorAll(".history-select:checked")).map((cb) =>
    cb.getAttribute("data-id")
  );
  if (checked.length > 2) {
    // Keep only the two most recently checked.
    const toUncheck = checked.slice(0, checked.length - 2);
    toUncheck.forEach((id) => {
      const cb = document.querySelector(`.history-select[data-id="${id}"]`);
      if (cb) cb.checked = false;
    });
  }
  state.selectedHistoryIds = Array.from(document.querySelectorAll(".history-select:checked")).map((cb) =>
    cb.getAttribute("data-id")
  );
  document.querySelectorAll(".history-table tbody tr").forEach((tr) => {
    tr.classList.toggle("selected", state.selectedHistoryIds.includes(tr.getAttribute("data-id")));
  });
  el("history-compare-btn").disabled = state.selectedHistoryIds.length !== 2;
}

el("history-compare-btn").addEventListener("click", () => {
  if (state.selectedHistoryIds.length !== 2) return;
  const [a, b] = state.selectedHistoryIds.map((id) =>
    state.historyEntries.find((e) => e.request_id === id)
  );
  renderHistoryCompare(a, b);
});

function ledgerEntryCard(entry) {
  // total_tokens/estimated_cost_usd cover the final generation call only;
  // for arcf/arcf_local, SLM-1's intent-extraction call (real spend) is
  // recorded separately in metadata rather than folded in — see
  // ledger.py::_metadata_for's own comment for why. Older entries
  // recorded before this existed won't have it, so this row is omitted
  // for those rather than showing a misleading $0.00.
  const overhead = entry.metadata || {};
  const hasOverhead =
    (entry.mode === "arcf" || entry.mode === "arcf_local") &&
    overhead.pipeline_overhead_cost_usd !== undefined;
  const overheadRows = hasOverhead
    ? `
        <tr><td>Final call tokens/cost only</td><td>above excludes SLM-1</td></tr>
        <tr><td>Pipeline overhead (SLM-1)</td><td>${fmtMs(overhead.pipeline_overhead_ms)}</td></tr>
        <tr><td>Overhead cost</td><td>${fmtMoney(overhead.pipeline_overhead_cost_usd)}</td></tr>
        <tr><td>True total cost</td><td>${fmtMoney(entry.estimated_cost_usd + overhead.pipeline_overhead_cost_usd)}</td></tr>
      `
    : "";
  return `
    <div class="run-card ${entry.mode}">
      <h3>${escapeHtml(entry.mode)} ${statusPill(entry.execution_status)}</h3>
      <table class="metric-table">
        <tr><td>Model</td><td>${escapeHtml(entry.model)}</td></tr>
        <tr><td>Provider</td><td>${escapeHtml(entry.provider || "—")}</td></tr>
        <tr><td>Recorded</td><td>${escapeHtml(fmtDate(entry.created_at))}</td></tr>
        <tr><td>Total tokens</td><td>${entry.total_tokens.toLocaleString()}</td></tr>
        <tr><td>Latency</td><td>${fmtMs(entry.latency_ms)}</td></tr>
        <tr><td>Cost</td><td>${fmtMoney(entry.estimated_cost_usd)}</td></tr>
        ${overheadRows}
        <tr><td>Files changed</td><td>${(entry.files_changed || []).length}</td></tr>
        <tr><td>Lines changed</td><td>${entry.lines_changed}</td></tr>
        <tr><td>Build result</td><td>${escapeHtml(entry.build_result || "not run")}</td></tr>
        <tr><td>Test result</td><td>${escapeHtml(entry.test_result || "not run")}</td></tr>
      </table>
      <div class="metric-section">
        ${detailBlock("Prompt", `<div class="output-preview">${escapeHtml(entry.prompt)}</div>`)}
        ${detailBlock(`Selected files (${(entry.selected_files || []).length})`, listOrNone(entry.selected_files))}
        ${detailBlock(`Selected symbols (${(entry.selected_symbols || []).length})`, listOrNone(entry.selected_symbols))}
      </div>
    </div>
  `;
}

function renderHistoryCompare(a, b) {
  const view = el("history-compare-view");
  view.innerHTML = `
    <h3>Comparing 2 executions</h3>
    <div class="comparison">${ledgerEntryCard(a)}${ledgerEntryCard(b)}</div>
    <h3 style="margin-top:16px">Artifact diff</h3>
    <div class="diff-view">${diffContentFor({ generated_output: unifiedTextDiff(a.artifact_content, b.artifact_content) })}</div>
  `;
  view.classList.remove("hidden");
  view.querySelectorAll(".detail-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = el(btn.getAttribute("data-target"));
      const isHidden = target.classList.toggle("hidden");
      btn.textContent = btn.textContent.replace(/^./, isHidden ? "▸" : "▾");
    });
  });
}

// Minimal line-level diff (LCS-free, just +/- of differing lines by index)
// — good enough for a side-by-side "what changed" view without pulling in a
// diff library; not meant to be a minimal-edit-distance diff.
function unifiedTextDiff(a, b) {
  const linesA = (a || "").split("\n");
  const linesB = (b || "").split("\n");
  const max = Math.max(linesA.length, linesB.length);
  const out = ["--- a", "+++ b"];
  for (let i = 0; i < max; i++) {
    const la = linesA[i];
    const lb = linesB[i];
    if (la === lb) {
      out.push(` ${la ?? ""}`);
    } else {
      if (la !== undefined) out.push(`-${la}`);
      if (lb !== undefined) out.push(`+${lb}`);
    }
  }
  return out.join("\n");
}

function downloadBlob(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

el("history-export-json-btn").addEventListener("click", () => {
  downloadBlob(
    `arcf-execution-history-${Date.now()}.json`,
    JSON.stringify(state.historyEntries, null, 2),
    "application/json"
  );
});

el("history-export-csv-btn").addEventListener("click", () => {
  const cols = [
    "request_id", "created_at", "mode", "model", "provider", "execution_status",
    "total_tokens", "latency_ms", "estimated_cost_usd", "files_changed", "lines_changed",
    "build_result", "test_result",
  ];
  const rows = state.historyEntries.map((e) =>
    cols
      .map((c) => {
        const v = c === "files_changed" ? (e[c] || []).length : e[c];
        const s = v == null ? "" : String(v);
        return `"${s.replace(/"/g, '""')}"`;
      })
      .join(",")
  );
  downloadBlob(
    `arcf-execution-history-${Date.now()}.csv`,
    [cols.join(","), ...rows].join("\n"),
    "text/csv"
  );
});

el("history-refresh-btn").addEventListener("click", refreshHistory);
el("history-mode-filter").addEventListener("change", refreshHistory);
let historySearchDebounce = null;
el("history-search").addEventListener("input", () => {
  clearTimeout(historySearchDebounce);
  historySearchDebounce = setTimeout(refreshHistory, 300);
});

refreshHistory();
