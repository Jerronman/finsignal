const accountEl = document.getElementById('account-summary');
const tbody = document.getElementById('trades-body');
const showSkippedToggle = document.getElementById('show-skipped');
const symbolFilterInput = document.getElementById('symbol-filter');

// Shown even with "show skipped" off -- these are attempted trades that
// were blocked, not routine guardrail skips (hold/low-confidence/cooldown).
const ALWAYS_VISIBLE = new Set(['bought', 'sold', 'profit_take', 'error', 'skipped_not_tradable']);

let allTrades = [];

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s || '';
  return div.innerHTML;
}

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function formatAmount(t) {
  if (t.outcome === 'bought' && t.amount_usd != null) return `$${t.amount_usd.toFixed(2)}`;
  if (t.outcome === 'sold') return 'closed';
  if (t.outcome === 'profit_take') return 'partial sell';
  return '—';
}

function fillStatusHtml(t) {
  if (!t.order_id) return '<span class="meta">—</span>';
  const status = t.fill_status || 'pending';
  return `<span class="pill fill-${escapeHtml(status)}">${escapeHtml(status.replace(/_/g, ' '))}</span>`;
}

function headlineHtml(headline, url) {
  const text = escapeHtml(headline);
  if (url && /^https?:\/\//i.test(url)) {
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${text}</a>`;
  }
  return text;
}

function rowHtml(t) {
  const why = t.headline
    ? `${escapeHtml(t.reasoning || '')} — <em>${headlineHtml(t.headline, t.headline_url)}</em>`
    : escapeHtml(t.reasoning || '');
  return `
    <tr>
      <td>${escapeHtml(formatTime(t.created_at))}</td>
      <td><strong>${escapeHtml(t.symbol)}</strong></td>
      <td><span class="pill ${escapeHtml(t.outcome)}">${escapeHtml(t.outcome.replace(/_/g, ' '))}</span></td>
      <td>${escapeHtml(formatAmount(t))}</td>
      <td>${fillStatusHtml(t)}</td>
      <td class="why">${why}</td>
    </tr>
  `;
}

function renderTrades() {
  let filtered = showSkippedToggle.checked ? allTrades : allTrades.filter(t => ALWAYS_VISIBLE.has(t.outcome));

  const query = symbolFilterInput.value.trim().toUpperCase();
  if (query) {
    filtered = filtered.filter(t => (t.symbol || '').toUpperCase().includes(query));
  }

  tbody.innerHTML = filtered.length
    ? filtered.map(rowHtml).join('')
    : `<tr><td colspan="6" class="meta">${query ? `No trades matching "${escapeHtml(query)}"` : 'No trades yet'}</td></tr>`;
}

async function loadTrades() {
  const res = await fetch('/api/trades?limit=300');
  allTrades = await res.json();
  renderTrades();
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

showSkippedToggle.addEventListener('change', renderTrades);
symbolFilterInput.addEventListener('input', renderTrades);

loadTrades();
refreshAccount();
setInterval(loadTrades, 30000);
setInterval(refreshAccount, 30000);
