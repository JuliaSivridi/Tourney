const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

// ── Tab switching ──────────────────────────────────────────────
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab + "-view").classList.add("active");
  });
});

// ── Load data ─────────────────────────────────────────────────
const params = new URLSearchParams(window.location.search);
const tid = params.get("tid");

async function loadData() {
  if (!tid) {
    // No tid — show mock data for preview/dev
    render(getMockData());
    return;
  }
  try {
    const res = await fetch(`/api/tournament/${tid}`);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    render(data);
  } catch (e) {
    render(getMockData());
  }
}

// ── Render ─────────────────────────────────────────────────────
function render(data) {
  document.getElementById("tournament-title").textContent = data.title || "Tournament";
  renderBracket(data);
  renderStandings(data);
}

function renderBracket(data) {
  const container = document.getElementById("bracket-container");
  container.innerHTML = "";

  const { matches, players, format } = data;
  const playerMap = Object.fromEntries(players.map(p => [p.id, p]));

  if (format === "round_robin") {
    renderRoundRobin(container, matches, playerMap);
  } else {
    renderElimination(container, matches, playerMap);
  }
}

function renderElimination(container, matches, playerMap) {
  // Group by bracket section, then by round
  const sections = ["winners", "losers", "final"];
  const sectionLabels = { winners: "Winners", losers: "Losers", final: "Grand Final" };

  sections.forEach(section => {
    const sectionMatches = matches.filter(m => m.bracket === section);
    if (!sectionMatches.length) return;

    const rounds = groupBy(sectionMatches, m => m.round);
    const roundNums = Object.keys(rounds).map(Number).sort((a, b) => a - b);

    const sectionEl = document.createElement("div");
    sectionEl.className = "bracket-section";

    const label = document.createElement("div");
    label.className = "bracket-section-label";
    label.textContent = sectionLabels[section] || section;
    sectionEl.appendChild(label);

    const colsEl = document.createElement("div");
    colsEl.style.display = "flex";

    roundNums.forEach((rNum, rIdx) => {
      const col = document.createElement("div");
      col.className = "round-col";

      const rlabel = document.createElement("div");
      rlabel.className = "round-label";
      rlabel.textContent = roundName(section, rNum, roundNums.length, rIdx);
      col.appendChild(rlabel);

      rounds[rNum].forEach(m => {
        col.appendChild(makeMatchCard(m, playerMap));
      });

      colsEl.appendChild(col);
    });

    sectionEl.appendChild(colsEl);
    container.appendChild(sectionEl);
  });
}

function renderRoundRobin(container, matches, playerMap) {
  const rounds = groupBy(matches, m => m.round);
  const roundNums = Object.keys(rounds).map(Number).sort((a, b) => a - b);

  const colsEl = document.createElement("div");
  colsEl.style.display = "flex";

  roundNums.forEach(rNum => {
    const col = document.createElement("div");
    col.className = "round-col";

    const rlabel = document.createElement("div");
    rlabel.className = "round-label";
    rlabel.textContent = `Round ${rNum}`;
    col.appendChild(rlabel);

    rounds[rNum].forEach(m => col.appendChild(makeMatchCard(m, playerMap)));
    colsEl.appendChild(col);
  });

  container.appendChild(colsEl);
}

function makeMatchCard(match, playerMap) {
  const card = document.createElement("div");
  card.className = "match-card";

  const id = document.createElement("div");
  id.className = "match-id";
  id.textContent = `#${String(match.id).padStart(2, "0")}`;
  card.appendChild(id);

  [match.player1_id, match.player2_id].forEach(pid => {
    const row = document.createElement("div");
    row.className = "match-player";

    if (!pid) {
      row.classList.add("bye");
      row.innerHTML = `<span class="player-name">BYE</span>`;
    } else {
      const p = playerMap[pid];
      const isWinner = match.winner_id === pid;
      const isLoser = match.winner_id && match.winner_id !== pid;
      if (isWinner) row.classList.add("winner");
      if (isLoser) row.classList.add("loser");

      row.innerHTML = `
        <span class="player-seed">${p.seed}</span>
        <span class="player-name">${escHtml(p.name)}</span>
        <span class="player-icon">${isWinner ? "✅" : isLoser ? "❌" : ""}</span>
      `;
    }
    card.appendChild(row);
  });

  return card;
}

function renderStandings(data) {
  const { players, matches } = data;
  const tbody = document.querySelector("#standings-table tbody");
  tbody.innerHTML = "";

  // Calculate wins per player from matches
  const wins = {};
  players.forEach(p => { wins[p.id] = 0; });
  matches.forEach(m => { if (m.winner_id) wins[m.winner_id] = (wins[m.winner_id] || 0) + 1; });

  const sorted = [...players].sort((a, b) => {
    const wDiff = (wins[b.id] || 0) - (wins[a.id] || 0);
    return wDiff !== 0 ? wDiff : a.losses - b.losses;
  });

  const medals = ["🥇", "🥈", "🥉"];

  sorted.forEach((p, i) => {
    const tr = document.createElement("tr");
    const place = medals[i] || `${i + 1}`;
    tr.innerHTML = `
      <td><span class="place-medal">${place}</span></td>
      <td>${escHtml(p.name)}</td>
      <td>${wins[p.id] || 0}</td>
      <td>${p.losses}</td>
      <td>${p.played}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ── Helpers ───────────────────────────────────────────────────
function groupBy(arr, fn) {
  return arr.reduce((acc, x) => {
    const k = fn(x);
    (acc[k] = acc[k] || []).push(x);
    return acc;
  }, {});
}

function escHtml(str) {
  return str.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function roundName(section, rNum, total, idx) {
  if (section === "final") return "Grand Final";
  if (total === 1) return section === "winners" ? "Final" : "Final";
  if (idx === total - 1) return section === "winners" ? "Final" : "LB Final";
  if (idx === total - 2) return section === "winners" ? "Semifinal" : "LB Semifinal";
  return `Round ${rNum}`;
}

function showError(msg) {
  document.getElementById("bracket-container").innerHTML = `<div id="loading">${msg}</div>`;
}

// ── Mock data for preview/dev ─────────────────────────────────
function getMockData() {
  return {
    title: "Demo Tournament",
    format: "single_elim",
    players: [
      { id: 1, name: "Alice", seed: 1, losses: 0, played: 2 },
      { id: 2, name: "Bob", seed: 2, losses: 1, played: 2 },
      { id: 3, name: "Charlie", seed: 3, losses: 1, played: 1 },
      { id: 4, name: "Diana", seed: 4, losses: 1, played: 1 },
    ],
    matches: [
      { id: 1, round: 1, position: 0, bracket: "winners", player1_id: 1, player2_id: 4, winner_id: 1 },
      { id: 2, round: 1, position: 1, bracket: "winners", player1_id: 2, player2_id: 3, winner_id: 2 },
      { id: 3, round: 2, position: 0, bracket: "winners", player1_id: 1, player2_id: 2, winner_id: null },
    ],
  };
}

loadData();
