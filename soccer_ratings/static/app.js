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
