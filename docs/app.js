// ── Telegram WebApp init ───────────────────────────────────────
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const uid = new URLSearchParams(window.location.search).get("uid")
  || tg?.initDataUnsafe?.user?.id
  || null;

// ── API helpers ────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
const GET  = (p)    => api("GET",  p);
const POST = (p, b) => api("POST", p, b);

// Relative URL (no leading slash) so nginx prefix /tourney-api/ is preserved
function gameUrl(path = "") { return `api/game/${uid}${path}`; }

// ── Screen routing ─────────────────────────────────────────────
function show(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.add("hidden"));
  document.getElementById(id).classList.remove("hidden");
}

// ── Tab switching ──────────────────────────────────────────────
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    const parent = btn.closest(".screen");
    parent.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    parent.querySelectorAll(".tab-view").forEach(v => v.classList.remove("active"));
    btn.classList.add("active");
    parent.querySelector(`#${btn.dataset.tab}-view`).classList.add("active");
  });
});

// ── State icons (matching bot) ─────────────────────────────────
const ICON  = { 0: "⚪", 1: "🟢", 2: "🔴", 3: "⚫" };
const CLASS = { 0: "", 1: "winner", 2: "loser", 3: "elim" };
const FMT_LABEL = {
  single_elim: "Single Elimination",
  double_elim: "Double Elimination",
  round_robin: "Round Robin",
};

// ── Main: load current state and decide which screen ──────────
let refreshTimer = null;

async function init() {
  if (!uid) { show("screen-format"); return; }

  show("screen-loading");
  try {
    const data = await GET(gameUrl());
    route(data);
  } catch {
    show("screen-format");
  }
}

function route(data) {
  clearInterval(refreshTimer);

  if (!data.format) {
    show("screen-format");
    return;
  }
  if (data.status === "idle" || data.status === "") {
    // Format chosen, waiting for players
    show("screen-players");
    return;
  }
  if (data.status === "active") {
    renderGame(data);
    show("screen-game");
    // Poll for updates (so inline-keyboard changes appear here too)
    refreshTimer = setInterval(async () => {
      try { renderGame(await GET(gameUrl())); } catch {}
    }, 4000);
    return;
  }
  if (data.status === "finished") {
    renderResults(data);
    show("screen-results");
    return;
  }
  show("screen-format");
}

// ── Screen: Format selection ───────────────────────────────────
document.querySelectorAll(".format-btn").forEach(btn => {
  btn.addEventListener("click", async () => {
    if (!uid) { alert("Открой через Telegram бот"); return; }
    try {
      await POST(gameUrl("/new"));
      await POST(gameUrl("/format"), { format: btn.dataset.fmt });
      show("screen-players");
    } catch (e) { alert("Ошибка: " + e.message); }
  });
});

// ── Screen: Players ────────────────────────────────────────────
document.getElementById("back-from-players").addEventListener("click", async () => {
  try { await POST(gameUrl("/new")); } catch {}
  show("screen-format");
});

document.getElementById("btn-shuffle").addEventListener("click", () => {
  const lines = getPlayerLines();
  for (let i = lines.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [lines[i], lines[j]] = [lines[j], lines[i]];
  }
  document.getElementById("players-input").value = lines.join("\n");
});

document.getElementById("btn-start").addEventListener("click", async () => {
  const names = getPlayerLines();
  if (names.length < 2) { alert("Нужно минимум 2 участника"); return; }
  try {
    await POST(gameUrl("/players"), { players: names });
    const data = await POST(gameUrl("/start"));
    renderGame(data);
    show("screen-game");
    refreshTimer = setInterval(async () => {
      try { renderGame(await GET(gameUrl())); } catch {}
    }, 4000);
  } catch (e) { alert("Ошибка: " + e.message); }
});

function getPlayerLines() {
  return document.getElementById("players-input").value
    .split("\n")
    .map(s => s.trim())
    .filter(Boolean);
}

// ── Screen: Game ───────────────────────────────────────────────
document.getElementById("btn-new-game").addEventListener("click", async () => {
  if (!confirm("Начать новый турнир?")) return;
  clearInterval(refreshTimer);
  try { await POST(gameUrl("/new")); } catch {}
  show("screen-format");
});

document.getElementById("btn-new-after-results").addEventListener("click", async () => {
  try { await POST(gameUrl("/new")); } catch {}
  show("screen-format");
});

function renderGame(data) {
  document.getElementById("game-format-label").textContent =
    FMT_LABEL[data.format] || data.format;
  renderMatches(data);
  renderStandings(data);
}

function renderMatches(data) {
  const container = document.getElementById("matches-container");
  const { matches, players, format, last_m } = data;

  if (!matches || !matches.length) {
    container.innerHTML = `<div class="empty">Матчей пока нет</div>`;
    return;
  }

  const visible = matches
    .map((m, i) => ({ ...m, idx: i }))
    .filter(m => isSlot(m.p?.[0]) && isSlot(m.p?.[1]));

  if (!visible.length) {
    container.innerHTML = `<div class="empty">Ожидание участников...</div>`;
    return;
  }

  // Split winners / losers for DE
  const winners = visible.filter(m => m.grid !== false);
  const losers  = visible.filter(m => m.grid === false);

  container.innerHTML = "";

  if (format === "double_elim" && losers.length) {
    container.appendChild(makeSection("Победители", winners, last_m));
    container.appendChild(makeSection("Проигравшие", losers, last_m));
  } else {
    container.appendChild(makeSection(null, visible, last_m));
  }
}

function makeSection(label, matches, last_m) {
  const wrap = document.createElement("div");
  if (label) {
    const h = document.createElement("div");
    h.className = "section-label";
    h.textContent = label;
    wrap.appendChild(h);
  }
  matches.forEach(m => wrap.appendChild(makeMatchCard(m, last_m)));
  return wrap;
}

function isSlot(x) { return x && typeof x === "object"; }

function makeMatchCard(match, last_m) {
  const card = document.createElement("div");
  card.className = "match-card";

  const decided = match.p[0].state !== 0 && match.p[1].state !== 0;

  const num = document.createElement("div");
  num.className = "match-num";
  num.textContent = `#${String(match.idx + 1).padStart(2, "0")}`;
  card.appendChild(num);

  match.p.forEach((slot, slotIdx) => {
    const row = document.createElement("div");
    row.className = `match-player ${CLASS[slot.state] || ""}`;

    const icon = document.createElement("span");
    icon.className = "slot-icon";
    icon.textContent = ICON[slot.state] ?? "⚪";

    const name = document.createElement("span");
    name.className = "slot-name";
    name.textContent = slot.name;

    row.appendChild(icon);
    row.appendChild(name);

    // Clickable if match is pending
    if (!decided) {
      row.classList.add("clickable");
      row.addEventListener("click", () => pickWinner(match.idx, slotIdx));
    }

    // Undo button on last decided match
    if (decided && match.idx === last_m) {
      const undo = document.createElement("button");
      undo.className = "undo-btn";
      undo.textContent = "↩";
      undo.title = "Отменить результат";
      undo.addEventListener("click", (e) => {
        e.stopPropagation();
        undoMatch(match.idx);
      });
      row.appendChild(undo);
    }

    card.appendChild(row);
  });

  return card;
}

async function pickWinner(m_idx, winner_slot) {
  try {
    const data = await POST(gameUrl("/match"), { m_idx, winner_slot });
    if (data.finished) {
      clearInterval(refreshTimer);
      // Small delay so user sees the result
      setTimeout(async () => {
        renderResults(await GET(gameUrl()));
        show("screen-results");
      }, 600);
    } else {
      renderGame(data);
    }
  } catch (e) { alert("Ошибка: " + e.message); }
}

async function undoMatch(m_idx) {
  try {
    const data = await POST(gameUrl("/undo"), { m_idx });
    renderGame(data);
  } catch (e) { alert("Ошибка: " + e.message); }
}

// ── Standings ──────────────────────────────────────────────────
function renderStandings(data) {
  const tbody = document.querySelector("#standings-table tbody");
  tbody.innerHTML = "";
  const { players } = data;
  if (!players?.length) return;

  const sorted = [...players].sort((a, b) => {
    const wa = (a.played || 0) - (a.losses || 0);
    const wb = (b.played || 0) - (b.losses || 0);
    return wb - wa || (a.losses || 0) - (b.losses || 0);
  });

  const medals = ["🥇", "🥈", "🥉"];
  sorted.forEach((p, i) => {
    const wins = (p.played || 0) - (p.losses || 0);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${medals[i] || i + 1}</td>
      <td>${esc(p.name)}</td>
      <td>${wins}</td>
      <td>${p.losses || 0}</td>
      <td>${p.played || 0}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ── Results screen ─────────────────────────────────────────────
function renderResults(data) {
  const list = document.getElementById("results-list");
  const { players } = data;
  if (!players?.length) { list.innerHTML = ""; return; }

  const sorted = [...players].sort((a, b) => {
    const wa = (a.played || 0) - (a.losses || 0);
    const wb = (b.played || 0) - (b.losses || 0);
    return wb - wa || (a.losses || 0) - (b.losses || 0);
  });

  const medals = ["🥇", "🥈", "🥉"];
  list.innerHTML = sorted.map((p, i) =>
    `<div class="result-row">
      <span class="result-place">${medals[i] || "#" + (i + 1)}</span>
      <span class="result-name">${esc(p.name)}</span>
    </div>`
  ).join("");
}

// ── Helpers ────────────────────────────────────────────────────
function esc(s) {
  return String(s || "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ── Start ──────────────────────────────────────────────────────
init();
