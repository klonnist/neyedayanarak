const state = { data: null, activeProfile: null, chart: null };

const fmtUsdt = (n) => `${Number(n).toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`;
const fmtPct = (n) => `${n >= 0 ? "+" : ""}${Number(n).toFixed(2)}%`;
const pnlClass = (n) => (n > 0 ? "up" : n < 0 ? "down" : "flat");

async function loadData() {
  const res = await fetch(`data/status.json?_=${Date.now()}`);
  if (!res.ok) throw new Error(`status.json alinamadi: ${res.status}`);
  return res.json();
}

function renderHeader(data) {
  const updated = new Date(data.generated_at);
  document.getElementById("updated-at").textContent = updated.toLocaleString("tr-TR", { timeZone: "UTC", hour12: false }) + " UTC";
}

function unrealizedPct(profile) {
  const pos = profile.open_position;
  if (!pos || !profile.last_price) return null;
  const dir = pos.direction;
  return dir * (profile.last_price / pos.entry_price - 1) * 100;
}

function renderCards(data) {
  const container = document.getElementById("cards");
  container.innerHTML = "";
  data.profiles.forEach((p) => {
    const card = document.createElement("div");
    card.className = "card" + (p.id === state.activeProfile ? " active" : "");
    card.onclick = () => {
      state.activeProfile = p.id;
      renderCards(data);
      renderChart(p);
    };

    const upnl = unrealizedPct(p);
    const posHtml = p.open_position
      ? `<div class="position">
           <strong>${p.open_position.direction === 1 ? "LONG" : "SHORT"}</strong> @ ${Number(p.open_position.entry_price).toFixed(2)}
           ${upnl !== null ? `&nbsp;<span class="${pnlClass(upnl)}">${fmtPct(upnl)}</span>` : ""}
         </div>`
      : `<div class="position flat">Pozisyon yok</div>`;

    card.innerHTML = `
      <div class="title">
        <span>${p.symbol}</span>
        <span class="badge">${p.timeframe}</span>
      </div>
      <div class="balance">${fmtUsdt(p.balance)}</div>
      <div class="pnl ${pnlClass(p.total_pnl)}">${fmtPct(p.total_pnl_pct)} (${p.total_pnl >= 0 ? "+" : ""}${p.total_pnl.toFixed(2)} USDT)</div>
      <div class="stats">
        <span>Kazanma: ${p.win_rate_pct}%</span>
        <span>İşlem: ${p.num_trades}</span>
      </div>
      ${posHtml}
    `;
    container.appendChild(card);
  });
}

function renderChart(profile) {
  const ctx = document.getElementById("equity-chart").getContext("2d");
  document.getElementById("chart-title").textContent = `${profile.symbol} ${profile.timeframe} — Equity Eğrisi (Sanal Hesap)`;

  const labels = profile.equity_curve.map((pt) => pt.t);
  const values = profile.equity_curve.map((pt) => pt.equity);

  if (state.chart) state.chart.destroy();
  state.chart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Equity (USDT)",
          data: values,
          borderColor: "#4f8cff",
          backgroundColor: "rgba(79,140,255,0.08)",
          fill: true,
          tension: 0.15,
          pointRadius: 0,
          borderWidth: 1.6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#8b93a3", maxTicksLimit: 8 }, grid: { color: "#262b36" } },
        y: { ticks: { color: "#8b93a3" }, grid: { color: "#262b36" } },
      },
      plugins: { legend: { display: false } },
    },
  });
}

function renderTrades(data) {
  const tbody = document.querySelector("#trades-table tbody");
  tbody.innerHTML = "";
  if (!data.recent_trades.length) {
    document.getElementById("trades-empty").style.display = "block";
    return;
  }
  document.getElementById("trades-empty").style.display = "none";

  data.recent_trades.forEach((t) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${t.symbol} <span class="badge">${t.timeframe}</span></td>
      <td>${t.direction === "long" ? "LONG" : "SHORT"}</td>
      <td>${Number(t.entry_price).toFixed(2)}</td>
      <td>${Number(t.exit_price).toFixed(2)}</td>
      <td class="${pnlClass(t.pnl_pct)}">${fmtPct(t.pnl_pct)}</td>
      <td>${t.exit_reason}</td>
      <td>${new Date(t.exit_time).toLocaleString("tr-TR", { timeZone: "UTC", hour12: false })} UTC</td>
    `;
    tbody.appendChild(tr);
  });
}

async function init() {
  try {
    const data = await loadData();
    state.data = data;
    state.activeProfile = data.profiles[0]?.id ?? null;
    renderHeader(data);
    renderCards(data);
    if (data.profiles[0]) renderChart(data.profiles[0]);
    renderTrades(data);
  } catch (err) {
    document.getElementById("cards").innerHTML = `<div class="empty">Veri yüklenemedi: ${err.message}</div>`;
  }
}

init();
setInterval(init, 5 * 60 * 1000);
