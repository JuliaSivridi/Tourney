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
const uid = params.get("uid");

// State icons matching bot: 0=pending, 1=winner, 2=loser, 3=eliminated
const STATE_ICON = { 0: "⚪", 1: "🟢", 2: "🔴", 3: "⚫" };
const STATE_CLASS = { 0: "", 1: "winner", 2: "loser", 3: "eliminated" };

async function loadData() {
  if (!uid) {
    render(getMockData());
    return;
  }
  try {
    const res = await fetch(`/api/game/${uid}`);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    render(data);
  } catch (e) {
    console.error("API error:", e);
    render(getMockData());
  }
}

// ── Render ─────────────────────────────────────────────────────
function render(data) {
  document.getElementById("tournament-title").textContent =
    data.title || (data.format === "round_robin" ? "Round Robin" :
                   data.format === "double_elim" ? "Double Elimination" : "Single Elimination");
  renderBracket(data);
  renderStandings(data);
}

// ── Bracket view ───────────────────────────────────────────────
function renderBracket(data) {
  const container = document.getElementById("bracket-container");
  container.innerHTML = "";

  const { matches, players, format } = data;
  if (!matches || !matches.length) {
    container.innerHTML = `<div class="loading">Нет данных о матчах</div>`;
    return;
  }

  // Filter only matches where both slots are filled
  const visible = matches
    .map((m, i) => ({ ...m, idx: i }))
    .filter(m => m.p && isSlot(m.p[0]) && isSlot(m.p[1]));

  if (!visible.length) {
    container.innerHTML = `<div class="loading">Турнир ещё не начат</div>`;
    return;
  }

  if (format === "round_robin") {
    renderRoundRobin(container, visible);
  } else {
    renderElimination(container, visible, format);
  }
}

function isSlot(x) {
  return x && typeof x === "object";
}

function renderElimination(container, matches, format) {
  // Split into winners (grid=true) and losers (grid=false) for DE
  // For SE all matches have grid=null/true
  const winners = matches.filter(m => m.grid !== false);
  const losers  = matches.filter(m => m.grid === false);

  if (format === "double_elim" && losers.length > 0) {
    const wSection = makeSection("Победители", winners);
    const lSection = makeSection("Проигравшие", losers);
    container.appendChild(wSection);
    container.appendChild(lSection);
  } else {
    // SE or DE without losers bracket yet — just show all in sequence
    const section = makeSection("Сетка", matches);
    container.appendChild(section);
  }
}

function renderRoundRobin(container, matches) {
  const section = makeSection("Матчи", matches);
  container.appendChild(section);
}

function makeSection(label, matches) {
  const section = document.createElement("div");
  section.className = "bracket-section";

  const title = document.createElement("div");
  title.className = "bracket-section-label";
  title.textContent = label;
  section.appendChild(title);

  const grid = document.createElement("div");
  grid.className = "matches-grid";

  matches.forEach(m => grid.appendChild(makeMatchCard(m)));
  section.appendChild(grid);
  return section;
}

function makeMatchCard(match) {
  const card = document.createElement("div");
  card.className = "match-card";

  const id = document.createElement("div");
  id.className = "match-id";
  id.textContent = `#${String(match.idx + 1).padStart(2, "0")}`;
  card.appendChild(id);

  match.p.forEach(slot => {
    if (!isSlot(slot)) return;
    const row = document.createElement("div");
    row.className = `match-player ${STATE_CLASS[slot.state] || ""}`;
    row.innerHTML = `
      <span class="state-icon">${STATE_ICON[slot.state] ?? "⚪"}</span>
      <span class="player-name">${escHtml(slot.name)}</span>
    `;
    card.appendChild(row);
  });

  return card;
}

// ── Standings view ─────────────────────────────────────────────
function renderStandings(data) {
  const { players } = data;
  const tbody = document.querySelector("#standings-table tbody");
  tbody.innerHTML = "";

  if (!players || !players.length) return;

  const sorted = [...players].sort((a, b) => {
    const wa = (a.played || 0) - (a.losses || 0);
    const wb = (b.played || 0) - (b.losses || 0);
    if (wb !== wa) return wb - wa;
    return (a.losses || 0) - (b.losses || 0);
  });

  const medals = ["🥇", "🥈", "🥉"];

  sorted.forEach((p, i) => {
    const tr = document.createElement("tr");
    const place = medals[i] || `${i + 1}`;
    const wins = (p.played || 0) - (p.losses || 0);
    tr.innerHTML = `
      <td><span class="place-medal">${place}</span></td>
      <td>${escHtml(p.name)}</td>
      <td>${wins}</td>
      <td>${p.losses || 0}</td>
      <td>${p.played || 0}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ── Helpers ───────────────────────────────────────────────────
function escHtml(str) {
  if (!str) return "";
  return String(str).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ── Mock data for preview/dev ─────────────────────────────────
function getMockData() {
  return {
    title: "Демо-турнир",
    format: "single_elim",
    status: "active",
    players: [
      { name: "Алиса",  losses: 0, played: 2 },
      { name: "Борис",  losses: 1, played: 2 },
      { name: "Катя",   losses: 1, played: 1 },
      { name: "Дима",   losses: 1, played: 1 },
    ],
    matches: [
      { grid: true, p: [
          { id: 0, name: "Алиса", state: 1, next: [2, 0] },
          { id: 3, name: "Дима",  state: 2, next: [] }
        ]
      },
      { grid: true, p: [
          { id: 1, name: "Борис", state: 1, next: [2, 1] },
          { id: 2, name: "Катя",  state: 2, next: [] }
        ]
      },
      { grid: true, p: [
          { id: 0, name: "Алиса", state: 0, next: [] },
          { id: 1, name: "Борис", state: 0, next: [] }
        ]
      },
    ],
    last_m: 1,
    last_p: 1,
  };
}

loadData();
