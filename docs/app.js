// ── Telegram WebApp init ───────────────────────────────────────
const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
  if (tg.colorScheme === "light") {
    document.documentElement.classList.add("light-theme");
  }
}

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
  _lastBracketKey = null;
  if (!data.format) { resetToFormat(); return; }
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
  resetToFormat();
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
function resetToFormat() {
  document.getElementById("players-input").value = "";
  _lastBracketKey = null;
  show("screen-format");
}

document.getElementById("btn-new-game").addEventListener("click", async () => {
  if (!confirm("Начать новый турнир?")) return;
  clearInterval(refreshTimer);
  try { await POST(gameUrl("/new")); } catch {}
  resetToFormat();
});

document.getElementById("btn-new-after-results").addEventListener("click", async () => {
  try { await POST(gameUrl("/new")); } catch {}
  resetToFormat();
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

function maxRoundOf(arr) {
  return arr.reduce((m, x) => Math.max(m, x.round || 1), 1);
}

// Label a round based on its distance from the final round
function roundLabel(r, maxRound, isLosers, isDE) {
  if (isLosers) return `Раунд ${r}`;
  const dist = maxRound - r;
  if (isDE) {
    if (dist === 0) return "Суперфинал";
    if (dist === 1) return "Финал";
    if (dist === 2 && maxRound >= 3) return "Полуфинал";
    if (dist === 3 && maxRound >= 4) return "1/4 финала";
    if (dist === 4 && maxRound >= 5) return "1/8 финала";
  } else {
    if (dist === 0) return "Финал";
    if (dist === 1 && maxRound >= 2) return "Полуфинал";
    if (dist === 2 && maxRound >= 3) return "1/4 финала";
    if (dist === 3 && maxRound >= 4) return "1/8 финала";
  }
  return `Раунд ${r}`;
}

function renderBracket(data) {
  const container = document.getElementById("matches-container");
  const { matches, format, last_m } = data;

  if (!matches?.length) {
    container.innerHTML = `<div class="empty">Матчей пока нет</div>`;
    return;
  }

  // Compute total expected rounds from ALL matches (including future unfilled ones)
  const maxWR = maxRoundOf(matches.filter(m => m.section !== "losers"));
  const maxLR = maxRoundOf(matches.filter(m => m.section === "losers"));

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
      container.appendChild(makeSection("Победители", buildBracket(winners, last_m, false, maxWR, false, true), "winners-section"));
    }
    if (losers.length) {
      container.appendChild(makeSection("Проигравшие", buildBracket(losers, last_m, false, maxLR, true, false), "losers-section"));
    }
  } else {
    container.appendChild(buildBracket(filled, last_m, false, maxWR, false, false));
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

function buildBracket(matches, last_m, drawConnectors, maxRound, isLosers, isDE) {
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
    lbl.textContent = roundLabel(r, maxRound, isLosers, isDE);
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

  // Explicit width so the block expands to fit the bracket columns
  wrap.style.width = totalW + "px";

  // Scroll wrapper — clips overflow and provides horizontal scroll
  // (overflow-x: auto on the section itself doesn't reliably clip absolute children)
  const scrollWrap = document.createElement("div");
  scrollWrap.className = "bracket-scroll";
  scrollWrap.appendChild(wrap);
  return scrollWrap;
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

  const bothPresent = isSlot(match.p[0]) && isSlot(match.p[1]);
  const decided = bothPresent && match.p[0].state !== 0 && match.p[1].state !== 0;

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
    if (!decided && bothPresent) row.classList.add("clickable");

    row.innerHTML = `<span class="slot-icon">${ICON[slot.state] ?? "⚪"}</span>
                     <span class="slot-name">${esc(slot.name)}</span>`;

    if (!decided && bothPresent) {
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
    console.log("[pickWinner] ok:", data.ok, "finished:", data.finished,
      "has_matches:", !!data.matches, "last_m:", data.last_m, "error:", data.error);
    if (!data.ok || !data.matches) {
      console.warn("[pickWinner] skipping render, server response:", JSON.stringify(data));
      return;
    }
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

  const sorted = sortedPlayers(players);

  const medals = ["🥇", "🥈", "🥉"];
  sorted.forEach((p, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${medals[i]||i+1}</td><td>${esc(p.name)}</td>
      <td>${(p.played||0)-(p.losses||0)}</td><td>${p.losses||0}</td><td>${p.played||0}</td>`;
    tbody.appendChild(tr);
  });
}

// ── Results ────────────────────────────────────────────────────

function sortedPlayers(players) {
  return [...players].sort((a, b) => {
    const wa = (a.played||0) - (a.losses||0);
    const wb = (b.played||0) - (b.losses||0);
    return wb - wa || (a.losses||0) - (b.losses||0);
  });
}

function renderResults(data) {
  const list = document.getElementById("results-list");
  const { players } = data;
  if (!players?.length) { list.innerHTML = ""; return; }

  const sorted = sortedPlayers(players);
  const medals = ["🥇","🥈","🥉"];

  // Group tied players (same wins and losses)
  const groups = [];
  for (const p of sorted) {
    const wins = (p.played||0) - (p.losses||0);
    const last = groups[groups.length - 1];
    if (last) {
      const lp = last[0];
      if ((lp.played||0)-(lp.losses||0) === wins && (lp.losses||0) === (p.losses||0)) {
        last.push(p); continue;
      }
    }
    groups.push([p]);
  }

  let place = 0;
  list.innerHTML = groups.map(group => {
    const icon = medals[place] || `#${place+1}`;
    const names = group.map(p => esc(p.name)).join(", ");
    place += 1;   // dense ranking: next group is always +1, regardless of tie size
    return `<div class="result-row">
      <span class="result-place">${icon}</span>
      <span class="result-name">${names}</span>
    </div>`;
  }).join("");
}

// ── Helpers ────────────────────────────────────────────────────
function esc(s) {
  return String(s||"").replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

init();
