const state = {
  countries: [],
  leagues: [],
  selectedCountry: "",
  selectedLeague: "",
  currentRatings: null,
  loadingLeagueRatings: false,
  loadingComparison: false,
  activeTab: "single",
  multiRows: []
};

const continentSelect = document.getElementById("continent");
const countrySelect = document.getElementById("country");
const leagueSelect = document.getElementById("league");
const buildHistoryButton = document.getElementById("build-history");
const importHistoryButton = document.getElementById("import-history");
const importCountryButton = document.getElementById("import-country");
const statusEl = document.getElementById("status");
const homeTable = document.getElementById("home-table");
const awayTable = document.getElementById("away-table");
const homeCount = document.getElementById("home-count");
const awayCount = document.getElementById("away-count");
const metricSelection = document.getElementById("metric-selection");
const metricHome = document.getElementById("metric-home");
const metricAway = document.getElementById("metric-away");
const selectionPill = document.getElementById("selection-pill");
const homeTeamSelect = document.getElementById("home-team");
const awayTeamSelect = document.getElementById("away-team");
const selectedHomeRating = document.getElementById("selected-home-rating");
const selectedAwayRating = document.getElementById("selected-away-rating");
const ratingGapEl = document.getElementById("rating-gap");
const homeWinProb = document.getElementById("home-win-prob");
const drawProb = document.getElementById("draw-prob");
const awayWinProb = document.getElementById("away-win-prob");
const homeWinOdds = document.getElementById("home-win-odds");
const drawOdds = document.getElementById("draw-odds");
const awayWinOdds = document.getElementById("away-win-odds");
const homeDnbProb = document.getElementById("home-dnb-prob");
const awayDnbProb = document.getElementById("away-dnb-prob");
const homeDnbOdds = document.getElementById("home-dnb-odds");
const awayDnbOdds = document.getElementById("away-dnb-odds");
const over25Prob = document.getElementById("over-25-prob");
const under25Prob = document.getElementById("under-25-prob");
const over25Odds = document.getElementById("over-25-odds");
const under25Odds = document.getElementById("under-25-odds");
const bttsYesProb = document.getElementById("btts-yes-prob");
const bttsNoProb = document.getElementById("btts-no-prob");
const bttsYesOdds = document.getElementById("btts-yes-odds");
const bttsNoOdds = document.getElementById("btts-no-odds");
const marginInput = document.getElementById("margin");
const marketMeta = document.getElementById("market-meta");
const tabButtons = Array.from(document.querySelectorAll("[data-tab-target]"));
const tabPanels = Array.from(document.querySelectorAll("[data-tab-panel]"));
const multiMarginInput = document.getElementById("multi-margin");
const multiList = document.getElementById("multi-list");
const multiRowsCreated = document.getElementById("multi-rows-created");
const multiRowsReady = document.getElementById("multi-rows-ready");
const multiMarginDisplay = document.getElementById("multi-margin-display");
const multiHelp = document.getElementById("multi-help");
const historyCacheMeta = document.getElementById("history-cache-meta");
const historyCachePath = document.getElementById("history-cache-path");
const leagueMatches = document.getElementById("league-matches");
const leagueAvgGoals = document.getElementById("league-avg-goals");
const leagueAvgHomeGoals = document.getElementById("league-avg-home-goals");
const leagueAvgAwayGoals = document.getElementById("league-avg-away-goals");
const leagueHomeWinPct = document.getElementById("league-home-win-pct");
const leagueDrawPct = document.getElementById("league-draw-pct");
const leagueAwayWinPct = document.getElementById("league-away-win-pct");
const homeTeamGoalProfile = document.getElementById("home-team-goal-profile");
const awayTeamGoalProfile = document.getElementById("away-team-goal-profile");
const homeTeamGoalSample = document.getElementById("home-team-goal-sample");
const awayTeamGoalSample = document.getElementById("away-team-goal-sample");

function setStatus(message) {
  statusEl.textContent = message;
}

function updateSummary() {
  const country = state.countries.find((item) => item.country_path === state.selectedCountry);
  const league = state.leagues.find((item) => item.league_path === state.selectedLeague);
  if (country && league) {
    selectionPill.textContent = `${country.country} • ${league.league}`;
    metricSelection.textContent = "Live";
    return;
  }
  if (country) {
    selectionPill.textContent = `${country.country} selected`;
    metricSelection.textContent = "Country";
    return;
  }
  selectionPill.textContent = "No league selected";
  metricSelection.textContent = "Idle";
}

function setActiveTab(tabName) {
  state.activeTab = tabName;
  for (const button of tabButtons) {
    button.classList.toggle("is-active", button.dataset.tabTarget === tabName);
  }
  for (const panel of tabPanels) {
    panel.classList.toggle("is-active", panel.dataset.tabPanel === tabName);
  }
}

function renderSelect(select, items, placeholder, labelKey, valueKey) {
  select.innerHTML = "";

  if (!items.length) {
    const option = document.createElement("option");
    option.textContent = placeholder;
    option.value = "";
    select.appendChild(option);
    return;
  }

  const placeholderOption = document.createElement("option");
  placeholderOption.textContent = placeholder;
  placeholderOption.value = "";
  select.appendChild(placeholderOption);

  for (const item of items) {
    const option = document.createElement("option");
    option.textContent = item[labelKey];
    option.value = item[valueKey];
    select.appendChild(option);
  }
}

function renderCountrySelect(select, items, placeholder) {
  select.innerHTML = "";

  const placeholderOption = document.createElement("option");
  placeholderOption.textContent = placeholder;
  placeholderOption.value = "";
  select.appendChild(placeholderOption);

  if (!items.length) return;

  const hasContinent = items.some((item) => item.continent);
  if (!hasContinent) {
    for (const item of items) {
      const option = document.createElement("option");
      option.textContent = item.country;
      option.value = item.country_path;
      select.appendChild(option);
    }
    return;
  }

  const grouped = {};
  for (const item of items) {
    const key = item.continent || "Other";
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(item);
  }

  for (const [continent, countries] of Object.entries(grouped)) {
    const group = document.createElement("optgroup");
    group.label = continent;
    for (const item of countries) {
      const option = document.createElement("option");
      option.textContent = item.country;
      option.value = item.country_path;
      group.appendChild(option);
    }
    select.appendChild(group);
  }
}

function populateContinentSelect(countries) {
  const continents = [...new Set(countries.map((c) => c.continent).filter(Boolean))];
  continentSelect.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All Continents";
  continentSelect.appendChild(all);
  for (const name of continents) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    continentSelect.appendChild(opt);
  }
  continentSelect.disabled = false;
}

function filterCountriesByContinent(continent) {
  const filtered = continent
    ? state.countries.filter((c) => c.continent === continent)
    : state.countries;
  renderCountrySelect(countrySelect, filtered, "Choose a country");
  countrySelect.disabled = !filtered.length;
}

function renderTeamSelect(select, rows, placeholder) {
  renderSelect(select, rows, placeholder, "team", "team");
}

function resetHistoryCacheStatus() {
  historyCacheMeta.textContent = "No league history cache yet.";
  historyCachePath.textContent = "";
}

function resetLeagueStats() {
  leagueMatches.textContent = "-";
  leagueAvgGoals.textContent = "-";
  leagueAvgHomeGoals.textContent = "-";
  leagueAvgAwayGoals.textContent = "-";
  leagueHomeWinPct.textContent = "-";
  leagueDrawPct.textContent = "-";
  leagueAwayWinPct.textContent = "-";
}

function resetTeamGoalContext() {
  homeTeamGoalProfile.textContent = "-";
  awayTeamGoalProfile.textContent = "-";
  homeTeamGoalSample.textContent = "No history sample yet.";
  awayTeamGoalSample.textContent = "No history sample yet.";
}

function renderLeagueStats(stats) {
  if (!stats) {
    resetLeagueStats();
    return;
  }

  leagueMatches.textContent = String(stats.matches ?? "-");
  leagueAvgGoals.textContent = Number(stats.avg_goals).toFixed(2);
  leagueAvgHomeGoals.textContent = Number(stats.avg_home_goals).toFixed(2);
  leagueAvgAwayGoals.textContent = Number(stats.avg_away_goals).toFixed(2);
  leagueHomeWinPct.textContent = `${Number(stats.home_win_pct).toFixed(1)}%`;
  leagueDrawPct.textContent = `${Number(stats.draw_pct).toFixed(1)}%`;
  leagueAwayWinPct.textContent = `${Number(stats.away_win_pct).toFixed(1)}%`;
}

function cloneRows(rows) {
  return (rows || []).map((row) => ({ ...row }));
}

function resetComparison() {
  renderTeamSelect(homeTeamSelect, [], "Load league ratings first");
  renderTeamSelect(awayTeamSelect, [], "Load league ratings first");
  homeTeamSelect.disabled = true;
  awayTeamSelect.disabled = true;
  selectedHomeRating.textContent = "-";
  selectedAwayRating.textContent = "-";
  ratingGapEl.textContent = "-";
  resetTeamGoalContext();
  homeWinProb.textContent = "-";
  drawProb.textContent = "-";
  awayWinProb.textContent = "-";
  homeDnbProb.textContent = "-";
  awayDnbProb.textContent = "-";
  homeWinOdds.textContent = "Odds -";
  drawOdds.textContent = "Odds -";
  awayWinOdds.textContent = "Odds -";
  homeDnbOdds.textContent = "Odds -";
  awayDnbOdds.textContent = "Odds -";
  over25Prob.textContent = "-";
  under25Prob.textContent = "-";
  over25Odds.textContent = "Odds -";
  under25Odds.textContent = "Odds -";
  bttsYesProb.textContent = "-";
  bttsNoProb.textContent = "-";
  bttsYesOdds.textContent = "Odds -";
  bttsNoOdds.textContent = "Odds -";
  marketMeta.textContent = `Fair odds with ${Number(marginInput.value || 0).toFixed(2)}% margin.`;
}

function resetMultiBuilder() {
  state.multiRows = [];
  renderMultiRows();
}

function initializeMultiRows(homeRows, awayRows) {
  const rowCount = Math.floor(Math.min(homeRows.length, awayRows.length) / 2);
  state.multiRows = Array.from({ length: rowCount }, (_, index) => ({
    id: `row-${index + 1}`,
    homeTeam: "",
    awayTeam: "",
    odds: null,
    status: "pending"
  }));
  renderMultiRows();
}

function renderMultiRows() {
  const homeRows = cloneRows(state.currentRatings?.home || []);
  const awayRows = cloneRows(state.currentRatings?.away || []);

  if (!state.multiRows.length) {
    multiList.innerHTML = `
      <div class="empty">
        <strong>No rows yet</strong>
        Load a league and rows will be created automatically from the league size.
      </div>
    `;
    updateMultiSummary();
    return;
  }

  multiList.innerHTML = `
    <div class="multi-header multi-grid-template">
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
    </div>
  ` + state.multiRows.map((row, index) => `
    <div class="multi-row multi-grid-template" data-row-id="${row.id}">
      <div class="control">
        <label>Home Team ${index + 1}</label>
        <select data-field="homeTeam">
          ${buildOptions(homeRows, row.homeTeam, "Choose home team", "team", "team")}
        </select>
      </div>
      <div class="control">
        <label>Away Team ${index + 1}</label>
        <select data-field="awayTeam">
          ${buildOptions(awayRows, row.awayTeam, "Choose away team", "team", "team")}
        </select>
      </div>
      ${buildMultiOddsCell("1", formatMultiOdds(row, "1"))}
      ${buildMultiOddsCell("X", formatMultiOdds(row, "X"))}
      ${buildMultiOddsCell("2", formatMultiOdds(row, "2"))}
      ${buildMultiOddsCell("DNB 1", formatMultiOdds(row, "DNB1"))}
      ${buildMultiOddsCell("DNB 2", formatMultiOdds(row, "DNB2"))}
      ${buildMultiOddsCell("O2.5", formatMultiOdds(row, "O25"))}
      ${buildMultiOddsCell("U2.5", formatMultiOdds(row, "U25"))}
      ${buildMultiOddsCell("BTTS Y", formatMultiOdds(row, "BTTSY"))}
      ${buildMultiOddsCell("BTTS N", formatMultiOdds(row, "BTTSN"))}
    </div>
  `).join("");

  updateMultiSummary();
}

function buildMultiOddsCell(label, value) {
  return `
    <div class="multi-leg-odds">
      <strong>${label}</strong>
      <span>${value}</span>
    </div>
  `;
}

function buildOptions(items, selectedValue, placeholder, labelKey, valueKey) {
  const placeholderOption = `<option value="">${placeholder}</option>`;
  const options = items.map((item) => {
    const value = String(item[valueKey]);
    const selected = value === String(selectedValue) ? " selected" : "";
    return `<option value="${escapeHtml(value)}"${selected}>${escapeHtml(String(item[labelKey]))}</option>`;
  }).join("");
  return placeholderOption + options;
}

function formatMultiOdds(row, market) {
  if (row.status === "loading") {
    return "…";
  }
  if (row.status === "error") {
    return "Err";
  }
  if (row.odds && typeof row.odds[market] === "number" && row.odds[market] > 0) {
    return Number(row.odds[market]).toFixed(2);
  }
  return "-";
}

function updateMultiSummary() {
  const readyRows = state.multiRows.filter((row) => row.odds && typeof row.odds["1"] === "number");
  multiRowsCreated.textContent = `${state.multiRows.length}`;
  multiRowsReady.textContent = `${readyRows.length}`;
  multiMarginDisplay.textContent = `${Number(multiMarginInput.value || 0).toFixed(2)}%`;

  if (!state.multiRows.length) {
    multiHelp.textContent = "Each row shows `1`, `X`, `2`, `DNB`, `O2.5`, `U2.5`, and `BTTS` prices for one matchup from the selected league.";
    return;
  }

  multiHelp.textContent = `${readyRows.length} of ${state.multiRows.length} rows currently have matchup odds.`;
}

async function updateMultiRow(rowId) {
  const row = state.multiRows.find((item) => item.id === rowId);
  if (!row || !state.selectedLeague) {
    return;
  }

  if (!row.homeTeam || !row.awayTeam) {
    row.odds = null;
    row.status = "pending";
    renderMultiRows();
    return;
  }

  if (row.homeTeam === row.awayTeam) {
    row.odds = null;
    row.status = "error";
    renderMultiRows();
    return;
  }

  row.status = "loading";
  renderMultiRows();

  try {
    const data = await fetchJson(
      `/api/compare?league_url=${encodeURIComponent(state.selectedLeague)}&home_team=${encodeURIComponent(row.homeTeam)}&away_team=${encodeURIComponent(row.awayTeam)}&margin=${encodeURIComponent(multiMarginInput.value || "0")}`
    );
    row.odds = {
      "1": Number(data.market_odds.home),
      "X": Number(data.market_odds.draw),
      "2": Number(data.market_odds.away),
      "DNB1": Number(data.market_dnb_odds.home),
      "DNB2": Number(data.market_dnb_odds.away),
      "O25": Number(data.market_total_goals_odds.over),
      "U25": Number(data.market_total_goals_odds.under),
      "BTTSY": Number(data.market_btts_odds.yes),
      "BTTSN": Number(data.market_btts_odds.no)
    };
    row.status = "ready";
  } catch (error) {
    row.odds = null;
    row.status = "error";
    setStatus(error.message);
  }

  renderMultiRows();
}

async function refreshAllMultiRows() {
  for (const row of state.multiRows) {
    await updateMultiRow(row.id);
  }
}

function renderTable(container, rows) {
  if (!rows.length) {
    container.innerHTML = `
      <div class="empty">
        <strong>No data yet</strong>
        Load a league to display the current team ratings table.
      </div>
    `;
    return;
  }

  const body = rows.map((row) => `
    <tr>
      <td>${row.rank}</td>
      <td>${escapeHtml(row.team)}</td>
      <td>${Number(row.rating).toFixed(2)}</td>
    </tr>
  `).join("");

  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Rank</th>
            <th>Team</th>
            <th>Rating</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
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
  const response = await fetch(url);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ error: "Request failed" }));
    throw new Error(payload.error || "Request failed");
  }
  return response.json();
}

async function loadCountries() {
  setStatus("Loading countries...");
  const data = await fetchJson("/api/countries");
  state.countries = data.countries;
  populateContinentSelect(state.countries);
  renderCountrySelect(countrySelect, state.countries, "Choose a country");
  countrySelect.disabled = false;
  updateSummary();
  setStatus("Choose a continent and country to load leagues.");
}

async function loadLeagues(countryUrl) {
  leagueSelect.disabled = true;
  renderSelect(leagueSelect, [], "Loading leagues...", "league", "league_path");
  setStatus("Loading leagues...");

  const data = await fetchJson(`/api/leagues?country_url=${encodeURIComponent(countryUrl)}`);
  state.leagues = data.leagues;
  renderSelect(leagueSelect, state.leagues, "Choose a league", "league", "league_path");
  leagueSelect.disabled = false;
  updateSummary();
  setStatus("Choose a league to view home and away ratings.");
}

async function loadRatings(leagueUrl) {
  state.loadingLeagueRatings = true;
  leagueSelect.disabled = true;
  setStatus("Loading home and away ratings...");
  const data = await fetchJson(`/api/league-ratings?league_url=${encodeURIComponent(leagueUrl)}`);
  state.currentRatings = data;
  renderLeagueStats(data.league_stats || null);
  renderTable(homeTable, data.home || []);
  renderTable(awayTable, data.away || []);
  homeCount.textContent = `${(data.home || []).length} teams`;
  awayCount.textContent = `${(data.away || []).length} teams`;
  metricHome.textContent = `${(data.home || []).length}`;
  metricAway.textContent = `${(data.away || []).length}`;
  renderTeamSelect(homeTeamSelect, data.home || [], "Choose home team");
  renderTeamSelect(awayTeamSelect, data.away || [], "Choose away team");
  homeTeamSelect.disabled = !(data.home || []).length;
  awayTeamSelect.disabled = !(data.away || []).length;
  initializeMultiRows(data.home || [], data.away || []);
  buildHistoryButton.disabled = false;
  importHistoryButton.disabled = false;
  leagueSelect.disabled = false;
  state.loadingLeagueRatings = false;
  const league = state.leagues.find((item) => item.league_path === leagueUrl);
  updateSummary();
  await loadHistoryCacheStatus(leagueUrl);
  setStatus(`Showing ratings for ${league ? league.league : "selected league"}.`);
}

async function loadHistoryCacheStatus(leagueUrl) {
  if (!leagueUrl) {
    resetHistoryCacheStatus();
    return;
  }

  const data = await fetchJson(`/api/league-history/status?league_url=${encodeURIComponent(leagueUrl)}`);
  if (!data.cached) {
    historyCacheMeta.textContent = "No cached league history dataset for this league yet.";
    historyCachePath.textContent = "";
    return;
  }

  historyCacheMeta.textContent = `Cached dataset: ${data.deduped_match_count} deduped matches from ${data.team_count} teams (${data.raw_match_count} raw rows).`;
  historyCachePath.textContent = data.cache_path || "";
}

async function buildLeagueHistoryCache(forceRefresh = true) {
  if (!state.selectedLeague) {
    return;
  }

  buildHistoryButton.disabled = true;
  buildHistoryButton.textContent = forceRefresh ? "Refreshing..." : "Building...";
  setStatus("Building league history cache...");
  const data = await fetchJson(
    `/api/league-history/build?league_url=${encodeURIComponent(state.selectedLeague)}&refresh=${forceRefresh ? "1" : "0"}`
  );
  historyCacheMeta.textContent = `Cached dataset: ${data.deduped_match_count} deduped matches from ${data.team_count} teams (${data.raw_match_count} raw rows).`;
  historyCachePath.textContent = data.cache_path || "";
  buildHistoryButton.textContent = "Refresh Cache";
  buildHistoryButton.disabled = false;
  await loadRatings(state.selectedLeague);
  setStatus("League history cache is ready.");
}

async function importLeagueHistoryToDb() {
  if (!state.selectedLeague) {
    return;
  }

  importHistoryButton.disabled = true;
  importHistoryButton.textContent = "Importing...";
  setStatus("Importing league history into Postgres...");
  const data = await fetchJson(
    `/api/league-history/import?league_url=${encodeURIComponent(state.selectedLeague)}`
  );
  importHistoryButton.textContent = "Import To DB";
  importHistoryButton.disabled = false;
  await loadRatings(state.selectedLeague);
  setStatus(`Imported ${data.matches_imported} matches to Postgres for the selected league.`);
}

async function importCountryToDb() {
  if (!state.selectedCountry) {
    return;
  }

  importCountryButton.disabled = true;
  importCountryButton.textContent = "Importing...";
  setStatus("Importing all leagues for this country into Postgres — this may take a while...");
  const data = await fetchJson(
    `/api/country-history/import?country_url=${encodeURIComponent(state.selectedCountry)}`
  );
  importCountryButton.textContent = "Import Country to DB";
  importCountryButton.disabled = false;
  const leagues = data.leagues_processed ?? 0;
  const matches = data.matches_imported ?? 0;
  const failures = data.failure_count ?? 0;
  const failNote = failures ? ` (${failures} league(s) failed)` : "";
  setStatus(`Country import done: ${leagues} leagues, ${matches} matches imported${failNote}.`);
}

async function compareTeams() {
  if (!state.selectedLeague || !homeTeamSelect.value || !awayTeamSelect.value || state.loadingComparison) {
    return;
  }

  state.loadingComparison = true;
  homeTeamSelect.disabled = true;
  awayTeamSelect.disabled = true;
  setStatus("Calculating matchup probabilities and odds...");
  const data = await fetchJson(
    `/api/compare?league_url=${encodeURIComponent(state.selectedLeague)}&home_team=${encodeURIComponent(homeTeamSelect.value)}&away_team=${encodeURIComponent(awayTeamSelect.value)}&margin=${encodeURIComponent(marginInput.value || "0")}`
  );

  selectedHomeRating.textContent = Number(data.home_team.rating).toFixed(2);
  selectedAwayRating.textContent = Number(data.away_team.rating).toFixed(2);
  ratingGapEl.textContent = Number(data.rating_gap).toFixed(2);
  homeWinProb.textContent = `${(Number(data.probabilities.home) * 100).toFixed(1)}%`;
  drawProb.textContent = `${(Number(data.probabilities.draw) * 100).toFixed(1)}%`;
  awayWinProb.textContent = `${(Number(data.probabilities.away) * 100).toFixed(1)}%`;
  homeDnbProb.textContent = `${(Number(data.dnb_probabilities.home) * 100).toFixed(1)}%`;
  awayDnbProb.textContent = `${(Number(data.dnb_probabilities.away) * 100).toFixed(1)}%`;
  homeWinOdds.textContent = `Odds ${Number(data.market_odds.home).toFixed(2)}`;
  drawOdds.textContent = `Odds ${Number(data.market_odds.draw).toFixed(2)}`;
  awayWinOdds.textContent = `Odds ${Number(data.market_odds.away).toFixed(2)}`;
  homeDnbOdds.textContent = `Odds ${Number(data.market_dnb_odds.home).toFixed(2)}`;
  awayDnbOdds.textContent = `Odds ${Number(data.market_dnb_odds.away).toFixed(2)}`;
  over25Prob.textContent = `${(Number(data.total_goals_probabilities.over) * 100).toFixed(1)}%`;
  under25Prob.textContent = `${(Number(data.total_goals_probabilities.under) * 100).toFixed(1)}%`;
  over25Odds.textContent = `Odds ${Number(data.market_total_goals_odds.over).toFixed(2)}`;
  under25Odds.textContent = `Odds ${Number(data.market_total_goals_odds.under).toFixed(2)}`;
  bttsYesProb.textContent = `${(Number(data.btts_probabilities.yes) * 100).toFixed(1)}%`;
  bttsNoProb.textContent = `${(Number(data.btts_probabilities.no) * 100).toFixed(1)}%`;
  bttsYesOdds.textContent = `Odds ${Number(data.market_btts_odds.yes).toFixed(2)}`;
  bttsNoOdds.textContent = `Odds ${Number(data.market_btts_odds.no).toFixed(2)}`;
  const historyContext = data.historical_context;
  const teamGoalContext = data.team_goal_context;
  if (teamGoalContext) {
    homeTeamGoalProfile.textContent = `${Number(teamGoalContext.home_team_home_scored).toFixed(2)} scored • ${Number(teamGoalContext.home_team_home_conceded).toFixed(2)} conceded`;
    awayTeamGoalProfile.textContent = `${Number(teamGoalContext.away_team_away_scored).toFixed(2)} scored • ${Number(teamGoalContext.away_team_away_conceded).toFixed(2)} conceded`;
    homeTeamGoalSample.textContent = `${teamGoalContext.home_team_home_sample} home matches in history sample`;
    awayTeamGoalSample.textContent = `${teamGoalContext.away_team_away_sample} away matches in history sample`;
  } else {
    resetTeamGoalContext();
  }
  const historyMeta = historyContext
    ? ` • ${data.history_source} history • ${historyContext.sample_size} completed matches • local sample ${historyContext.local_match_count} • exp goals ${Number(data.expected_goals.home).toFixed(2)}-${Number(data.expected_goals.away).toFixed(2)}`
    : " • rating-only model";
  marketMeta.textContent = `Shin margin ${Number(data.margin_percent).toFixed(2)}% • 1X2 overround ${(Number(data.shin.overround) * 100).toFixed(2)}% • z ${Number(data.shin.z).toFixed(4)}${historyMeta}`;
  homeTeamSelect.disabled = false;
  awayTeamSelect.disabled = false;
  state.loadingComparison = false;
  setStatus(`Comparison ready for ${data.home_team.team} vs ${data.away_team.team}.`);
}

continentSelect.addEventListener("change", (event) => {
  const continent = event.target.value;
  state.selectedCountry = "";
  state.selectedLeague = "";
  renderTable(homeTable, []);
  renderTable(awayTable, []);
  homeCount.textContent = "0 teams";
  awayCount.textContent = "0 teams";
  metricHome.textContent = "0";
  metricAway.textContent = "0";
  state.currentRatings = null;
  state.leagues = [];
  renderSelect(leagueSelect, [], "Select a country first", "league", "league_path");
  leagueSelect.disabled = true;
  buildHistoryButton.disabled = true;
  importHistoryButton.disabled = true;
  importCountryButton.disabled = true;
  buildHistoryButton.textContent = "Build Local Cache";
  importHistoryButton.textContent = "Import To DB";
  resetComparison();
  resetMultiBuilder();
  resetHistoryCacheStatus();
  resetLeagueStats();
  updateSummary();
  filterCountriesByContinent(continent);
  setStatus(continent ? `Showing ${continent} countries. Choose one to load leagues.` : "Choose a country to load its leagues.");
});

countrySelect.addEventListener("change", async (event) => {
  state.selectedCountry = event.target.value;
  state.selectedLeague = "";
  renderTable(homeTable, []);
  renderTable(awayTable, []);
  homeCount.textContent = "0 teams";
  awayCount.textContent = "0 teams";
  metricHome.textContent = "0";
  metricAway.textContent = "0";
  state.currentRatings = null;
  resetComparison();
  updateSummary();

  if (!state.selectedCountry) {
    state.leagues = [];
    renderSelect(leagueSelect, [], "Select a country first", "league", "league_path");
    leagueSelect.disabled = true;
    buildHistoryButton.disabled = true;
    importHistoryButton.disabled = true;
    importCountryButton.disabled = true;
    buildHistoryButton.textContent = "Build Local Cache";
    importHistoryButton.textContent = "Import To DB";
    resetMultiBuilder();
    resetHistoryCacheStatus();
    resetLeagueStats();
    setStatus("Choose a country to load its leagues.");
    return;
  }
  importCountryButton.disabled = false;

  try {
    await loadLeagues(state.selectedCountry);
  } catch (error) {
    setStatus(error.message);
  }
});

leagueSelect.addEventListener("change", (event) => {
  state.selectedLeague = event.target.value;
  state.currentRatings = null;
  resetComparison();
  resetMultiBuilder();
  resetHistoryCacheStatus();
  resetLeagueStats();
  buildHistoryButton.disabled = !state.selectedLeague;
  importHistoryButton.disabled = !state.selectedLeague;
  buildHistoryButton.textContent = "Build Local Cache";
  importHistoryButton.textContent = "Import To DB";
  updateSummary();
  if (state.selectedLeague) {
    loadRatings(state.selectedLeague).catch((error) => {
        state.loadingLeagueRatings = false;
        leagueSelect.disabled = false;
      setStatus(error.message);
    });
  } else {
    setStatus("Choose a league to view home and away ratings.");
  }
});

homeTeamSelect.addEventListener("change", () => {
  if (homeTeamSelect.value && awayTeamSelect.value) {
    compareTeams().catch((error) => {
      state.loadingComparison = false;
      homeTeamSelect.disabled = false;
      awayTeamSelect.disabled = false;
      setStatus(error.message);
    });
  }
});

awayTeamSelect.addEventListener("change", () => {
  if (homeTeamSelect.value && awayTeamSelect.value) {
    compareTeams().catch((error) => {
      state.loadingComparison = false;
      homeTeamSelect.disabled = false;
      awayTeamSelect.disabled = false;
      setStatus(error.message);
    });
  }
});

marginInput.addEventListener("input", () => {
  marketMeta.textContent = `Shin margin ${Number(marginInput.value || 0).toFixed(2)}% pending recalculation.`;
  if (homeTeamSelect.value && awayTeamSelect.value) {
    compareTeams().catch((error) => {
      state.loadingComparison = false;
      homeTeamSelect.disabled = false;
      awayTeamSelect.disabled = false;
      setStatus(error.message);
    });
  }
});

multiMarginInput.addEventListener("input", () => {
  updateMultiSummary();
  refreshAllMultiRows().catch((error) => {
    setStatus(error.message);
  });
});

multiList.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) {
    return;
  }

  const rowEl = target.closest("[data-row-id]");
  if (!rowEl) {
    return;
  }

  const row = state.multiRows.find((item) => item.id === rowEl.dataset.rowId);
  if (!row) {
    return;
  }

  const field = target.dataset.field;
  if (!field) {
    return;
  }

  row[field] = target.value;
  row.odds = null;
  row.status = "pending";
  updateMultiRow(row.id).catch((error) => {
    row.status = "error";
    setStatus(error.message);
    renderMultiRows();
  });
});

for (const button of tabButtons) {
  button.addEventListener("click", () => {
    setActiveTab(button.dataset.tabTarget || "single");
  });
}

buildHistoryButton.addEventListener("click", () => {
  buildLeagueHistoryCache(true).catch((error) => {
    buildHistoryButton.disabled = false;
    buildHistoryButton.textContent = "Build Local Cache";
    setStatus(error.message);
  });
});

importHistoryButton.addEventListener("click", () => {
  importLeagueHistoryToDb().catch((error) => {
    importHistoryButton.disabled = false;
    importHistoryButton.textContent = "Import To DB";
    setStatus(error.message);
  });
});

importCountryButton.addEventListener("click", () => {
  importCountryToDb().catch((error) => {
    importCountryButton.disabled = false;
    importCountryButton.textContent = "Import Country to DB";
    setStatus(error.message);
  });
});

renderTable(homeTable, []);
renderTable(awayTable, []);
resetComparison();
resetMultiBuilder();
resetHistoryCacheStatus();
resetLeagueStats();
setActiveTab("single");
updateSummary();

loadCountries().catch((error) => {
  setStatus(error.message);
});
