const accountEl = document.getElementById('account-summary');
const form = document.getElementById('run-form');
const input = document.getElementById('tickers-input');
const runBtn = document.getElementById('run-btn');
const statusEl = document.getElementById('status');
const tbody = document.getElementById('adam-body');

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s == null ? '' : String(s);
  return div.innerHTML;
}

function plBadgeHtml(acct) {
  const up = acct.pl_today >= 0;
  const sign = up ? '+' : '';
  return `
    <span class="pl-badge ${up ? 'pl-up' : 'pl-down'}" title="Total account value change since yesterday's close (realized + unrealized)">
      P/L Today: <b>${sign}$${acct.pl_today.toFixed(2)} (${sign}${acct.pl_today_pct.toFixed(2)}%)</b>
    </span>
  `;
}

function realizedBadgeHtml(acct) {
  if (acct.realized_pl == null) return '';
  const up = acct.realized_pl >= 0;
  const sign = up ? '+' : '';
  return `
    <span class="pl-badge ${up ? 'pl-up' : 'pl-down'}" title="Cumulative realized gain/loss since account inception (excludes open positions still unrealized)">
      Realized: <b>${sign}$${acct.realized_pl.toFixed(2)}</b>
    </span>
  `;
}

async function refreshAccount() {
  try {
    const res = await fetch('/api/account');
    const acct = await res.json();
    accountEl.innerHTML = `
      <span>Equity: <b>$${acct.portfolio_value.toFixed(2)}</b></span>
      <span>Cash: <b>$${acct.cash.toFixed(2)}</b></span>
      ${plBadgeHtml(acct)}
      ${realizedBadgeHtml(acct)}
    `;
  } catch (e) {
    accountEl.textContent = 'Account unavailable — check Alpaca keys in .env';
  }
}

async function loadDefaultTickers() {
  try {
    const res = await fetch('/api/adam/default-tickers');
    const data = await res.json();
    input.value = data.tickers.join(', ');
    input.placeholder = '';
  } catch (e) {
    input.placeholder = 'AAPL, MSFT, ...';
  }
}

function rowHtml(r) {
  return `
    <tr>
      <td><strong>${escapeHtml(r.ticker)}</strong></td>
      <td>${escapeHtml(r.name)}</td>
      <td>${escapeHtml(r.sector)}</td>
      <td>$${r.price}</td>
      <td>$${r.high_52wk}</td>
      <td style="color: var(--red)">-${r.pullback_pct}%</td>
      <td>${r.pe ?? '—'}</td>
      <td>${r.pb ?? '—'}</td>
      <td>${r.debt_to_equity ?? '—'}</td>
      <td>${r.current_ratio ?? '—'}</td>
      <td>${r.free_cash_flow_millions ?? '—'}</td>
      <td>${r.profit_margin_pct != null ? r.profit_margin_pct + '%' : '—'}</td>
      <td>${r.market_cap_billions ?? '—'}</td>
    </tr>
  `;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const tickers = input.value.split(',').map(t => t.trim()).filter(Boolean);
  if (!tickers.length) return;

  runBtn.disabled = true;
  runBtn.textContent = 'Running…';
  statusEl.textContent = `Screening ${tickers.length} ticker(s) — this fetches each one from Yahoo Finance, so it can take a little while...`;
  tbody.innerHTML = '<tr><td colspan="13" class="meta">Running…</td></tr>';

  try {
    const res = await fetch('/api/adam/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tickers }),
    });
    const data = await res.json();
    const results = data.results || [];
    statusEl.textContent = `Screened ${data.tickers_screened.length} ticker(s) — ${results.length} matched.`;
    tbody.innerHTML = results.length
      ? results.map(rowHtml).join('')
      : '<tr><td colspan="13" class="meta">No stocks matched the criteria</td></tr>';
  } catch (e) {
    statusEl.textContent = 'Screener run failed — check the server logs.';
    tbody.innerHTML = '<tr><td colspan="13" class="meta">Error running screener</td></tr>';
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = 'Run Screener';
  }
});

loadDefaultTickers();
refreshAccount();
setInterval(refreshAccount, 30000);
