// ---------------------------------------------------------------------------
// Tab switching — event delegation handles tabs injected by HTMX
// ---------------------------------------------------------------------------

document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-tab-target]");
  if (!btn) return;
  const tabName = btn.dataset.tabTarget;
  const scope = btn.closest(".matchup") || document;
  scope.querySelectorAll("[data-tab-target]").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.tabTarget === tabName)
  );
  scope.querySelectorAll("[data-tab-panel]").forEach((p) =>
    p.classList.toggle("is-active", p.dataset.tabPanel === tabName)
  );
});

// ---------------------------------------------------------------------------
// Rating tables: sort, filter, and highlight the two selected teams.
// Event delegation means none of this needs re-initializing after HTMX
// swaps in fresh league content.
// ---------------------------------------------------------------------------

function sortRatingsTable(table, key, direction) {
  const tbody = table.querySelector("tbody");
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll("tr[data-team]"));
  const readValue = (row) => {
    const cell = row.querySelector(`[data-cell="${key}"]`);
    const raw = cell ? cell.textContent.trim() : "";
    return key === "team" ? raw.toLowerCase() : parseFloat(raw) || 0;
  };
  rows.sort((a, b) => {
    const av = readValue(a);
    const bv = readValue(b);
    if (av < bv) return direction === "asc" ? -1 : 1;
    if (av > bv) return direction === "asc" ? 1 : -1;
    return 0;
  });
  rows.forEach((row) => tbody.appendChild(row));
}

document.addEventListener("click", (e) => {
  const th = e.target.closest("th[data-sort-key]");
  if (!th) return;
  const table = th.closest("table");
  if (!table) return;
  const key = th.dataset.sortKey;
  const direction = th.dataset.sortDir === "asc" ? "desc" : "asc";
  table.querySelectorAll("th[data-sort-key]").forEach((h) => {
    delete h.dataset.sortDir;
    h.classList.remove("is-sorted-asc", "is-sorted-desc");
  });
  th.dataset.sortDir = direction;
  th.classList.add(direction === "asc" ? "is-sorted-asc" : "is-sorted-desc");
  sortRatingsTable(table, key, direction);
});

document.addEventListener("input", (e) => {
  if (!e.target || e.target.id !== "team-filter") return;
  const query = e.target.value.trim().toLowerCase();
  document
    .querySelectorAll('table[data-role="home-ratings"] tr[data-team], table[data-role="away-ratings"] tr[data-team]')
    .forEach((row) => {
      const team = (row.dataset.team || "").toLowerCase();
      row.style.display = team.includes(query) ? "" : "none";
    });
});

function highlightSelectedTeams() {
  const homeTeam = document.getElementById("home-team");
  const awayTeam = document.getElementById("away-team");
  document.querySelectorAll('table[data-role="home-ratings"] tr[data-team]').forEach((row) => {
    row.classList.toggle("is-selected-team", !!homeTeam && row.dataset.team === homeTeam.value);
  });
  document.querySelectorAll('table[data-role="away-ratings"] tr[data-team]').forEach((row) => {
    row.classList.toggle("is-selected-team", !!awayTeam && row.dataset.team === awayTeam.value);
  });
}

document.addEventListener("change", (e) => {
  if (e.target && (e.target.id === "home-team" || e.target.id === "away-team")) {
    highlightSelectedTeams();
  }
});

document.addEventListener("htmx:afterSettle", (e) => {
  if (e.target && e.target.id === "league-content") {
    highlightSelectedTeams();
  }
});

document.addEventListener("DOMContentLoaded", highlightSelectedTeams);

// ---------------------------------------------------------------------------
// Multi-match builder
// Reads team data from <script type="application/json" id="league-data">
// injected by the league_content.html fragment.
// ---------------------------------------------------------------------------

const multiState = {
  leagueUrl: "",
  homeTeams: [],
  awayTeams: [],
  rows: [],
};

// Re-initialize after HTMX settles new league content
document.addEventListener("htmx:afterSettle", (e) => {
  if (e.target && e.target.id === "league-content") {
    initMultiFromDOM();
  }
});

// A shared link can load the page with league content already rendered
// server-side (no HTMX swap happens), so initialize from the DOM directly.
document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("league-data")) {
    initMultiFromDOM();
  }
});

function initMultiFromDOM() {
  const el = document.getElementById("league-data");
  if (!el) return;
  try {
    const data = JSON.parse(el.textContent);
    multiState.leagueUrl = data.league_url || "";
    multiState.homeTeams = data.home || [];
    multiState.awayTeams = data.away || [];
  } catch {
    return;
  }
  multiState.rows = [];
  const rowCount = Math.floor(Math.min(multiState.homeTeams.length, multiState.awayTeams.length) / 2);
  multiState.rows = Array.from({ length: rowCount }, (_, i) => ({
    id: `row-${i + 1}`,
    homeTeam: "",
    awayTeam: "",
    odds: null,
    status: "pending",
  }));
  renderMultiRows();
}

function renderMultiRows() {
  const multiList = document.getElementById("multi-list");
  const multiRowsCreated = document.getElementById("multi-rows-created");
  const multiRowsReady = document.getElementById("multi-rows-ready");
  const multiMarginDisplay = document.getElementById("multi-margin-display");
  const multiHelp = document.getElementById("multi-help");
  const multiMarginInput = document.getElementById("multi-margin");

  if (!multiList) return;

  if (!multiState.rows.length) {
    multiList.innerHTML = `
      <div class="empty">
        <strong>No rows yet</strong>
        Load a league and rows will be created automatically from the league size.
      </div>`;
    if (multiRowsCreated) multiRowsCreated.textContent = "0";
    if (multiRowsReady) multiRowsReady.textContent = "0";
    return;
  }

  multiList.innerHTML =
    `<div class="multi-header multi-grid-template">
      <div class="multi-header-cell is-team">Home Team</div>
      <div class="multi-header-cell is-team">Away Team</div>
      <div class="multi-header-cell">1</div>
      <div class="multi-header-cell">X</div>
      <div class="multi-header-cell">2</div>
      <div class="multi-header-cell">DNB 1</div>
      <div class="multi-header-cell">DNB 2</div>
      <div class="multi-header-cell">O2.5</div>
      <div class="multi-header-cell">U2.5</div>
      <div class="multi-header-cell">BTTS Y</div>
      <div class="multi-header-cell">BTTS N</div>
    </div>` +
    multiState.rows
      .map(
        (row, i) => `
      <div class="multi-row multi-grid-template" data-row-id="${row.id}">
        <div class="control">
          <label>Home Team ${i + 1}</label>
          <select data-field="homeTeam">
            ${buildOptions(multiState.homeTeams, row.homeTeam, "Choose home team")}
          </select>
        </div>
        <div class="control">
          <label>Away Team ${i + 1}</label>
          <select data-field="awayTeam">
            ${buildOptions(multiState.awayTeams, row.awayTeam, "Choose away team")}
          </select>
        </div>
        ${multiOddsCell("1", fmtOdds(row, "1"))}
        ${multiOddsCell("X", fmtOdds(row, "X"))}
        ${multiOddsCell("2", fmtOdds(row, "2"))}
        ${multiOddsCell("DNB 1", fmtOdds(row, "DNB1"))}
        ${multiOddsCell("DNB 2", fmtOdds(row, "DNB2"))}
        ${multiOddsCell("O2.5", fmtOdds(row, "O25"))}
        ${multiOddsCell("U2.5", fmtOdds(row, "U25"))}
        ${multiOddsCell("BTTS Y", fmtOdds(row, "BTTSY"))}
        ${multiOddsCell("BTTS N", fmtOdds(row, "BTTSN"))}
      </div>`
      )
      .join("");

  const ready = multiState.rows.filter((r) => r.odds && typeof r.odds["1"] === "number");
  if (multiRowsCreated) multiRowsCreated.textContent = String(multiState.rows.length);
  if (multiRowsReady) multiRowsReady.textContent = String(ready.length);
  if (multiMarginDisplay && multiMarginInput)
    multiMarginDisplay.textContent = `${Number(multiMarginInput.value || 0).toFixed(2)}%`;
  if (multiHelp)
    multiHelp.textContent =
      multiState.rows.length
        ? `${ready.length} of ${multiState.rows.length} rows have matchup odds.`
        : "Each row shows 1X2, DNB, O/U 2.5, and BTTS prices for one matchup.";
}

function buildOptions(items, selectedValue, placeholder) {
  const ph = `<option value="">${placeholder}</option>`;
  const opts = items
    .map((item) => {
      const val = escapeHtml(String(item.team));
      const sel = val === String(selectedValue) ? " selected" : "";
      return `<option value="${val}"${sel}>${val}</option>`;
    })
    .join("");
  return ph + opts;
}

function multiOddsCell(label, value) {
  return `<div class="multi-leg-odds"><strong>${label}</strong><span>${value}</span></div>`;
}

function fmtOdds(row, market) {
  if (row.status === "loading") return "…";
  if (row.status === "error") return "Err";
  if (row.odds && typeof row.odds[market] === "number" && row.odds[market] > 0)
    return Number(row.odds[market]).toFixed(2);
  return "-";
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// ---------------------------------------------------------------------------
// Multi-match CSV export
// ---------------------------------------------------------------------------

const MULTI_CSV_HEADERS = ["Home Team", "Away Team", "1", "X", "2", "DNB 1", "DNB 2", "O2.5", "U2.5", "BTTS Y", "BTTS N"];
const MULTI_CSV_MARKETS = ["1", "X", "2", "DNB1", "DNB2", "O25", "U25", "BTTSY", "BTTSN"];

function csvField(value) {
  const str = String(value ?? "");
  return /[",\r\n]/.test(str) ? `"${str.replaceAll('"', '""')}"` : str;
}

// Pure and DOM-free so it can be exercised directly in a JS console/test
// runner without needing a browser: rows in, CSV text out.
function buildMultiRowsCsv(rows) {
  const lines = [MULTI_CSV_HEADERS.map(csvField).join(",")];
  for (const row of rows) {
    if (!row.homeTeam && !row.awayTeam) continue;
    const cells = [row.homeTeam, row.awayTeam, ...MULTI_CSV_MARKETS.map((market) => fmtOdds(row, market))];
    lines.push(cells.map(csvField).join(","));
  }
  return lines.join("\r\n");
}

function slugifyLeagueUrl(url) {
  const slug = (url || "").replace(/^\/+|\/+$/g, "").replace(/\//g, "-");
  return slug || "league";
}

function downloadTextFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

document.addEventListener("click", (e) => {
  if (!e.target || e.target.id !== "multi-export-csv") return;
  const csv = buildMultiRowsCsv(multiState.rows);
  const dateStr = new Date().toISOString().slice(0, 10);
  const filename = `multi-match-odds-${slugifyLeagueUrl(multiState.leagueUrl)}-${dateStr}.csv`;
  downloadTextFile(filename, csv, "text/csv;charset=utf-8;");
});

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ error: "Request failed" }));
    throw new Error(payload.error || "Request failed");
  }
  return res.json();
}

async function updateMultiRow(rowId) {
  const row = multiState.rows.find((r) => r.id === rowId);
  if (!row || !multiState.leagueUrl) return;

  if (!row.homeTeam || !row.awayTeam || row.homeTeam === row.awayTeam) {
    row.odds = null;
    row.status = "pending";
    renderMultiRows();
    return;
  }

  row.status = "loading";
  renderMultiRows();

  const multiMarginInput = document.getElementById("multi-margin");
  const margin = multiMarginInput ? multiMarginInput.value || "0" : "0";

  try {
    const data = await fetchJson(
      `/api/compare?league_url=${encodeURIComponent(multiState.leagueUrl)}` +
        `&home_team=${encodeURIComponent(row.homeTeam)}` +
        `&away_team=${encodeURIComponent(row.awayTeam)}` +
        `&margin=${encodeURIComponent(margin)}`
    );
    row.odds = {
      "1": Number(data.market_odds.home),
      X: Number(data.market_odds.draw),
      "2": Number(data.market_odds.away),
      DNB1: Number(data.market_dnb_odds.home),
      DNB2: Number(data.market_dnb_odds.away),
      O25: Number(data.market_total_goals_odds.over),
      U25: Number(data.market_total_goals_odds.under),
      BTTSY: Number(data.market_btts_odds.yes),
      BTTSN: Number(data.market_btts_odds.no),
    };
    row.status = "ready";
  } catch {
    row.odds = null;
    row.status = "error";
  }

  renderMultiRows();
}

// Event delegation for multi-row selects (works after HTMX re-injects rows)
document.addEventListener("change", (e) => {
  const target = e.target;
  if (!(target instanceof HTMLSelectElement)) return;
  const rowEl = target.closest("[data-row-id]");
  if (!rowEl) return;
  const row = multiState.rows.find((r) => r.id === rowEl.dataset.rowId);
  if (!row) return;
  const field = target.dataset.field;
  if (!field) return;
  row[field] = target.value;
  row.odds = null;
  row.status = "pending";
  updateMultiRow(row.id).catch(() => {
    row.status = "error";
    renderMultiRows();
  });
});

// Refresh all multi rows when margin changes
document.addEventListener("input", (e) => {
  if (e.target && e.target.id === "multi-margin") {
    for (const row of multiState.rows) {
      updateMultiRow(row.id).catch(() => {});
    }
  }
});

// ---------------------------------------------------------------------------
// Calibration sweep results: "Copy Results" button
// Reads the job result JSON from the <script id="calibration-sweep-data">
// tag injected by calibration_sweep_status.html and copies a plain-text /
// tab-separated report to the clipboard, so it pastes cleanly into chat,
// email, or a spreadsheet.
// ---------------------------------------------------------------------------

function fmtBrierValue(value) {
  return typeof value === "number" ? value.toFixed(4) : "-";
}

// Pure and DOM-free so it can be exercised directly in a test runner
// without needing a browser: the job's result JSON in, report text out.
function buildCalibrationSweepSummaryText(result) {
  const lines = ["Calibration Sweep Results"];
  lines.push(
    `Evaluated: ${result.leagues_evaluated} of ${result.leagues_considered} leagues` +
      (result.leagues_skipped ? ` (${result.leagues_skipped} skipped)` : "")
  );

  const summary = result.summary;
  if (summary) {
    lines.push(`Median Best Weight Scale: ${summary.median_best_weight_scale}`);
    lines.push(
      `Avg Brier Improvement vs Default: ${
        summary.avg_brier_improvement_vs_default != null
          ? fmtBrierValue(summary.avg_brier_improvement_vs_default)
          : "-"
      }`
    );
  }
  lines.push("");

  const leagues = result.leagues || [];
  if (leagues.length) {
    lines.push(["Country", "League", "Matches", "Best Scale", "Best Brier", "Default (1.0) Brier"].join("\t"));
    for (const row of leagues) {
      lines.push(
        [
          row.country || "-",
          row.league || row.league_path,
          row.matches_available,
          row.best.weight_scale,
          fmtBrierValue(row.best.avg_brier),
          row.default_avg_brier != null ? fmtBrierValue(row.default_avg_brier) : "-",
        ].join("\t")
      );
    }
  } else {
    lines.push("No league had enough imported history to evaluate.");
  }

  const skipped = result.skipped_leagues || [];
  if (skipped.length) {
    lines.push("");
    const minMatches = skipped[0].min_matches_required;
    const names = skipped.map((row) => row.league || row.league_path).join(", ");
    lines.push(`Skipped (fewer than ${minMatches} matches): ${names}`);
  }

  return lines.join("\n");
}

document.addEventListener("click", (e) => {
  if (!e.target || e.target.id !== "calibration-sweep-copy") return;
  const dataEl = document.getElementById("calibration-sweep-data");
  const feedback = document.getElementById("calibration-sweep-copy-feedback");
  if (!dataEl) return;

  const button = e.target;
  const originalText = button.textContent;

  const showFeedback = (text) => {
    if (text === "Copied!") {
      button.textContent = "Copied!";
      button.classList.add("copied");
      setTimeout(() => {
        button.textContent = originalText;
        button.classList.remove("copied");
      }, 2000);
    } else {
      if (!feedback) return;
      feedback.textContent = text;
      setTimeout(() => {
        feedback.textContent = "";
      }, 2000);
    }
  };

  let text;
  try {
    text = buildCalibrationSweepSummaryText(JSON.parse(dataEl.textContent));
  } catch {
    showFeedback("Copy failed.");
    return;
  }

  navigator.clipboard.writeText(text).then(
    () => showFeedback("Copied!"),
    () => showFeedback("Copy failed — select and copy manually.")
  );
});


// ---------------------------------------------------------------------------
// Backtest results: "Copy Results" and "Export CSV" buttons
// ---------------------------------------------------------------------------

function fmtBacktestValue(value) {
  return typeof value === "number" ? value.toFixed(4) : "-";
}

function buildBacktestSummaryText(result) {
  const lines = ["Backtest Results"];
  lines.push(`Matches Backtested: ${result.matches_evaluated}`);
  lines.push(`Avg Brier Score: ${fmtBacktestValue(result.avg_brier)}`);
  lines.push(`Pick Accuracy: ${result.pick_accuracy_percent != null ? result.pick_accuracy_percent.toFixed(1) + "%" : "-"}`);
  lines.push(`Value Bets Found: ${result.value_bet_count}`);
  lines.push(`Value Bet Hit Rate: ${result.hit_rate_percent != null ? result.hit_rate_percent.toFixed(1) + "%" : "-"}`);
  lines.push(`ROI (flat stake): ${result.roi_percent != null ? result.roi_percent.toFixed(1) + "%" : "-"}`);
  lines.push(`Edge Threshold: ${result.edge_threshold_percent != null ? result.edge_threshold_percent.toFixed(1) + "%" : "-"}`);
  lines.push("");

  const calib = result.calibration || [];
  if (calib.length) {
    lines.push("Calibration Table");
    lines.push(["Predicted Range", "Predicted Avg", "Actual Freq", "Samples"].join("\t"));
    for (const row of calib) {
      lines.push([
        `${row.range_low}-${row.range_high}%`,
        `${row.predicted_percent.toFixed(1)}%`,
        `${row.actual_percent.toFixed(1)}%`,
        row.count
      ].join("\t"));
    }
    lines.push("");
  }

  const matches = result.matches || [];
  if (matches.length) {
    lines.push(["Date", "Match", "Result", "Model Home", "Market Home", "Edge Home", "Model Draw", "Market Draw", "Edge Draw", "Model Away", "Market Away", "Edge Away"].join("\t"));
    for (const m of matches) {
      lines.push([
        m.date,
        `${m.home_team} vs ${m.away_team}`,
        m.result,
        `${(m.model_probabilities.home * 100).toFixed(0)}%`,
        `${(m.market_probabilities.home * 100).toFixed(0)}%`,
        m.edges.home.toFixed(1),
        `${(m.model_probabilities.draw * 100).toFixed(0)}%`,
        `${(m.market_probabilities.draw * 100).toFixed(0)}%`,
        m.edges.draw.toFixed(1),
        `${(m.model_probabilities.away * 100).toFixed(0)}%`,
        `${(m.market_probabilities.away * 100).toFixed(0)}%`,
        m.edges.away.toFixed(1)
      ].join("\t"));
    }
  }

  return lines.join("\n");
}

function buildBacktestCSV(result) {
  const matches = result.matches || [];
  const lines = [];
  lines.push(["Date", "Match", "Result", "Model Home", "Market Home", "Edge Home", "Model Draw", "Market Draw", "Edge Draw", "Model Away", "Market Away", "Edge Away"].join(","));
  for (const m of matches) {
    const row = [
      m.date,
      `"${m.home_team} vs ${m.away_team}"`,
      m.result,
      `${(m.model_probabilities.home * 100).toFixed(0)}%`,
      `${(m.market_probabilities.home * 100).toFixed(0)}%`,
      m.edges.home.toFixed(1),
      `${(m.model_probabilities.draw * 100).toFixed(0)}%`,
      `${(m.market_probabilities.draw * 100).toFixed(0)}%`,
      m.edges.draw.toFixed(1),
      `${(m.model_probabilities.away * 100).toFixed(0)}%`,
      `${(m.market_probabilities.away * 100).toFixed(0)}%`,
      m.edges.away.toFixed(1)
    ];
    lines.push(row.join(","));
  }
  return lines.join("\n");
}

document.addEventListener("click", (e) => {
  if (!e.target) return;
  if (e.target.id === "backtest-copy" || e.target.id === "backtest-export-csv") {
    const dataEl = document.getElementById("backtest-data");
    const feedback = document.getElementById("backtest-action-feedback");
    if (!dataEl) return;

    const button = e.target;
    const originalText = button.textContent;

    const showFeedback = (text) => {
      if (text === "Copied!" || text === "Exported!") {
        button.textContent = text;
        button.classList.add("copied");
        setTimeout(() => {
          button.textContent = originalText;
          button.classList.remove("copied");
        }, 2000);
      } else {
        if (!feedback) return;
        feedback.textContent = text;
        setTimeout(() => {
          feedback.textContent = "";
        }, 2000);
      }
    };

    let result;
    try {
      result = JSON.parse(dataEl.textContent);
    } catch {
      showFeedback("Action failed.");
      return;
    }

    if (e.target.id === "backtest-copy") {
      const text = buildBacktestSummaryText(result);
      navigator.clipboard.writeText(text).then(
        () => showFeedback("Copied!"),
        () => showFeedback("Copy failed — select and copy manually.")
      );
    } else if (e.target.id === "backtest-export-csv") {
      const csv = buildBacktestCSV(result);
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.setAttribute("href", url);
      link.setAttribute("download", "backtest_results.csv");
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      showFeedback("Exported!");
    }
  }
});
