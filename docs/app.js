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

function gameUrl(path = "") { return `api/game/${uid}${path}`; }

// ── Screen routing ─────────────────────────────────────────────
function show(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.add("hidden"));
  document.getElementById(id).classList.remove("hidden");
}

// ── Tabs ───────────────────────────────────────────────────────
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    const parent = btn.closest(".screen");
    parent.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
    parent.querySelectorAll(".tab-view").forEach(v => v.classList.remove("active"));
    btn.classList.add("active");
    parent.querySelector(`#${btn.dataset.tab}-view`).classList.add("active");
  });
});

// ── Icons & labels ─────────────────────────────────────────────
const ICON  = { 0: "⚪", 1: "🟢", 2: "🔴", 3: "⚫" };
const CLASS = { 0: "", 1: "winner", 2: "loser", 3: "elim" };
const FMT_LABEL = {
  single_elim: "Single Elimination",
  double_elim: "Double Elimination",
  round_robin: "Round Robin",
};

// ── Bracket layout constants ───────────────────────────────────
const COL_W   = 170; // match card column width
const CONN_W  =  32; // connector width between rounds
const CARD_H  =  82; // 2 rows × 40px + 1px border + 1px border-radius gap
const SLOT_PAD = 10; // extra padding above/below card in slot

// ── Load & route ───────────────────────────────────────────────
let refreshTimer = null;
let _lastBracketKey = null;

function _bracketKey(data) {
  // Only re-render bracket when match states or last_m actually change
  return (data.last_m ?? -1) + "|" +
    (data.matches || []).map(m => (m.p?.[0]?.state ?? "-") + (m.p?.[1]?.state ?? "-")).join(",");
}

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
  _lastBracketKey = null;  // reset on route change
  if (!data.format) { show("screen-format"); return; }
  if (data.status === "idle" || data.status === "") { show("screen-players"); return; }
  if (data.status === "active") {
    renderGame(data);
    show("screen-game");
    refreshTimer = setInterval(async () => {
      try { renderGame(await GET(gameUrl())); } catch {}
    }, 4000);
    return;
  }
  if (data.status === "finished") { renderResults(data); show("screen-results"); return; }
  show("screen-format");
}

// ── Format screen ──────────────────────────────────────────────
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

// ── Players screen ─────────────────────────────────────────────
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
    .split("\n").map(s => s.trim()).filter(Boolean);
}

// ── Game screen ────────────────────────────────────────────────
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
  document.getElementById("game-format-label").textContent = FMT_LABEL[data.format] || data.format;
  const key = _bracketKey(data);
  if (key !== _lastBracketKey) {
    _lastBracketKey = key;
    renderBracket(data);
  }
  renderStandings(data);
}

// ── BRACKET RENDERING ──────────────────────────────────────────

function renderBracket(data) {
  const container = document.getElementById("matches-container");
  const { matches, format, last_m } = data;

  if (!matches?.length) {
    container.innerHTML = `<div class="empty">Матчей пока нет</div>`;
    return;
  }

  // Include bye matches (one slot may be empty — waiting for opponent)
  const filled = matches.map((m, i) => ({ ...m, origIdx: i }))
    .filter(m => isSlot(m.p?.[0]) || isSlot(m.p?.[1]));

  if (!filled.length) {
    container.innerHTML = `<div class="empty">Ожидание участников...</div>`;
    return;
  }

  container.innerHTML = "";

  if (format === "round_robin") {
    renderRR(container, filled, last_m);
    return;
  }

  if (format === "double_elim") {
    const winners = filled.filter(m => m.section !== "losers");
    const losers  = filled.filter(m => m.section === "losers");
    if (winners.length) {
      container.appendChild(makeSection("Победители", buildBracket(winners, last_m, false), "winners-section"));
    }
    if (losers.length) {
      container.appendChild(makeSection("Проигравшие", buildBracket(losers, last_m, false), "losers-section"));
    }
  } else {
    container.appendChild(buildBracket(filled, last_m, true));
  }
}

function makeLabel(text) {
  const el = document.createElement("div");
  el.className = "section-title";
  el.textContent = text;
  return el;
}

function makeSection(label, bracketEl, cls) {
  const section = document.createElement("div");
  section.className = `bracket-section ${cls}`;
  section.appendChild(makeLabel(label));
  section.appendChild(bracketEl);
  return section;
}

// ── Horizontal bracket ─────────────────────────────────────────
// drawConnectors=true  → SE: lines appear only when both pair matches decided
// drawConnectors=false → DE: no lines (arbitrary order makes them misleading)

function matchDecided(m) {
  return isSlot(m.p[0]) && isSlot(m.p[1]) && m.p[0].state !== 0 && m.p[1].state !== 0;
}

function buildBracket(matches, last_m, drawConnectors) {
  const byRound = {};
  matches.forEach(m => {
    const r = m.round || 1;
    (byRound[r] = byRound[r] || []).push(m);
  });
  const rounds = Object.keys(byRound).map(Number).sort((a, b) => a - b);
  const nRounds = rounds.length;

  const r1Count = byRound[rounds[0]].length;
  const slotH1  = CARD_H + SLOT_PAD * 2;
  const totalH  = r1Count * slotH1;
  const totalW  = nRounds * COL_W + (nRounds - 1) * CONN_W;

  const wrap = document.createElement("div");
  wrap.className = "bracket-wrap";

  // ── Round labels ───────────────────────────────────────────
  const labelsRow = document.createElement("div");
  labelsRow.className = "bracket-labels-row";
  labelsRow.style.width = totalW + "px";
  rounds.forEach((r, ri) => {
    const lbl = document.createElement("div");
    lbl.className = "round-label";
    lbl.style.width = COL_W + "px";
    lbl.style.marginRight = ri < nRounds - 1 ? CONN_W + "px" : "0";
    const isLast    = ri === nRounds - 1;
    const isPreLast = ri === nRounds - 2;
    lbl.textContent = isLast ? "Финал"
      : (isPreLast && nRounds > 2) ? "Полуфинал"
      : `Раунд ${r}`;
    labelsRow.appendChild(lbl);
  });
  wrap.appendChild(labelsRow);

  // ── Bracket area ───────────────────────────────────────────
  const area = document.createElement("div");
  area.className = "bracket-area";
  area.style.height = totalH + "px";
  area.style.width  = totalW + "px";

  rounds.forEach((r, ri) => {
    const roundMatches = byRound[r];
    const count  = roundMatches.length;
    const slotH  = totalH / count;
    const x      = ri * (COL_W + CONN_W);

    // Place cards
    roundMatches.forEach((m, mi) => {
      const centerY = slotH * mi + slotH / 2;
      const cardTop = Math.round(centerY - CARD_H / 2);
      const cardWrap = document.createElement("div");
      cardWrap.style.cssText = `position:absolute;left:${x}px;top:${cardTop}px;width:${COL_W}px;`;
      cardWrap.appendChild(makeMatchCard(m, last_m));
      area.appendChild(cardWrap);
    });

    // Draw connectors (SE only, pair-complete logic)
    if (drawConnectors && ri < nRounds - 1) {
      const nextCount = byRound[rounds[ri + 1]].length;
      const armX = x + COL_W;
      const midX = armX + CONN_W / 2;

      for (let pi = 0; pi < count; pi += 2) {
        const m0 = roundMatches[pi];
        const m1 = pi + 1 < count ? roundMatches[pi + 1] : null;
        const parentIdx = Math.floor(pi / 2);
        if (parentIdx >= nextCount) continue;

        const nextSlotH  = totalH / nextCount;
        const nextCenterY = nextSlotH * parentIdx + nextSlotH / 2;
        const c0Y = slotH * pi + slotH / 2;

        if (!m1) {
          // Bye / odd solo match — draw connector when it's decided
          if (matchDecided(m0)) {
            area.appendChild(line(armX, c0Y, CONN_W / 2, 2));
            area.appendChild(line(midX, nextCenterY, CONN_W / 2, 2));
          }
        } else {
          // Pair — draw full connector only when BOTH decided
          if (matchDecided(m0) && matchDecided(m1)) {
            const c1Y = slotH * (pi + 1) + slotH / 2;
            area.appendChild(line(armX, c0Y, CONN_W / 2, 2));        // arm from m0
            area.appendChild(line(armX, c1Y, CONN_W / 2, 2));        // arm from m1
            area.appendChild(line(midX - 1, c0Y, 2, c1Y - c0Y));    // vertical bar
            area.appendChild(line(midX, nextCenterY, CONN_W / 2, 2)); // arm to next
          }
        }
      }
    }
  });

  wrap.appendChild(area);
  return wrap;
}

function line(x, y, w, h) {
  const d = document.createElement("div");
  d.className = "conn-line";
  d.style.cssText = `left:${x}px;top:${Math.round(y) - (h === 2 ? 1 : 0)}px;width:${w}px;height:${h}px;`;
  return d;
}

function isSlot(x) { return x && typeof x === "object"; }

// ── Match card ─────────────────────────────────────────────────

function makeMatchCard(match, last_m) {
  const card = document.createElement("div");
  card.className = "match-card";

  const decided = match.p[0].state !== 0 && match.p[1].state !== 0;

  const num = document.createElement("div");
  num.className = "match-num";
  num.textContent = `#${String((match.origIdx ?? match.idx ?? 0) + 1).padStart(2, "0")}`;
  card.appendChild(num);

  match.p.forEach((slot, si) => {
    const row = document.createElement("div");
    if (!isSlot(slot)) {
      // Bye slot — waiting for opponent to be determined
      row.className = "match-player";
      row.innerHTML = `<span class="slot-icon" style="opacity:.3">⚪</span>
                       <span class="slot-name"></span>`;
      card.appendChild(row);
      return;
    }
    row.className = `match-player ${CLASS[slot.state] || ""}`;
    if (!decided) row.classList.add("clickable");

    row.innerHTML = `<span class="slot-icon">${ICON[slot.state] ?? "⚪"}</span>
                     <span class="slot-name">${esc(slot.name)}</span>`;

    if (!decided) {
      row.addEventListener("click", () => pickWinner(match.origIdx ?? match.idx, si));
    }

    // Undo button on decided match that was the last one
    if (decided && (match.origIdx ?? match.idx) === last_m) {
      const undo = document.createElement("button");
      undo.className = "undo-btn";
      undo.title = "Отменить результат";
      undo.textContent = "↺";
      undo.addEventListener("click", e => {
        e.stopPropagation();
        undoMatch(match.origIdx ?? match.idx);
      });
      row.appendChild(undo);
    }

    card.appendChild(row);
  });

  return card;
}

// ── Round Robin ────────────────────────────────────────────────

function renderRR(container, matches, last_m) {
  const byRound = {};
  matches.forEach(m => {
    const r = m.round || 1;
    (byRound[r] = byRound[r] || []).push(m);
  });
  Object.keys(byRound).sort((a,b) => a-b).forEach(r => {
    const lbl = document.createElement("div");
    lbl.className = "section-label";
    lbl.textContent = `Тур ${r}`;
    container.appendChild(lbl);
    byRound[r].forEach(m => {
      container.appendChild(makeMatchCard(m, last_m));
    });
  });
}

// ── Match actions ──────────────────────────────────────────────

async function pickWinner(m_idx, winner_slot) {
  try {
    const data = await POST(gameUrl("/match"), { m_idx, winner_slot });
    if (data.finished) {
      clearInterval(refreshTimer);
      setTimeout(async () => {
        renderResults(await GET(gameUrl()));
        show("screen-results");
      }, 500);
    } else {
      renderGame(data);
    }
  } catch (e) { alert("Ошибка: " + e.message); }
}

async function undoMatch(m_idx) {
  try { renderGame(await POST(gameUrl("/undo"), { m_idx })); }
  catch (e) { alert("Ошибка: " + e.message); }
}

// ── Standings ──────────────────────────────────────────────────

function renderStandings(data) {
  const tbody = document.querySelector("#standings-table tbody");
  tbody.innerHTML = "";
  const { players } = data;
  if (!players?.length) return;

  const sorted = [...players].sort((a, b) => {
    const wa = (a.played||0) - (a.losses||0), wb = (b.played||0) - (b.losses||0);
    return wb - wa || (a.losses||0) - (b.losses||0);
  });

  const medals = ["🥇", "🥈", "🥉"];
  sorted.forEach((p, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${medals[i]||i+1}</td><td>${esc(p.name)}</td>
      <td>${(p.played||0)-(p.losses||0)}</td><td>${p.losses||0}</td><td>${p.played||0}</td>`;
    tbody.appendChild(tr);
  });
}

// ── Results ────────────────────────────────────────────────────

function renderResults(data) {
  const list = document.getElementById("results-list");
  const { players } = data;
  if (!players?.length) { list.innerHTML = ""; return; }

  const sorted = [...players].sort((a, b) => {
    const wa = (a.played||0)-(a.losses||0), wb = (b.played||0)-(b.losses||0);
    return wb - wa || (a.losses||0)-(b.losses||0);
  });

  const medals = ["🥇","🥈","🥉"];
  list.innerHTML = sorted.map((p, i) =>
    `<div class="result-row">
      <span class="result-place">${medals[i]||"#"+(i+1)}</span>
      <span class="result-name">${esc(p.name)}</span>
    </div>`
  ).join("");
}

// ── Helpers ────────────────────────────────────────────────────
function esc(s) {
  return String(s||"").replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

init();
