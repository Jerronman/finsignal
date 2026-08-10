const accountEl = document.getElementById('account-summary');
const tbody = document.getElementById('trades-body');
const showSkippedToggle = document.getElementById('show-skipped');

const EXECUTED = new Set(['bought', 'sold', 'profit_take']);

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

function rowHtml(t) {
  const why = t.headline ? `${escapeHtml(t.reasoning || '')} — <em>${escapeHtml(t.headline)}</em>` : escapeHtml(t.reasoning || '');
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

async function loadTrades() {
  const res = await fetch('/api/trades?limit=300');
  const trades = await res.json();
  const filtered = showSkippedToggle.checked ? trades : trades.filter(t => EXECUTED.has(t.outcome) || t.outcome === 'error');
  tbody.innerHTML = filtered.length
    ? filtered.map(rowHtml).join('')
    : '<tr><td colspan="6" class="meta">No trades yet</td></tr>';
}

async function refreshAccount() {
  try {
    const res = await fetch('/api/account');
    const acct = await res.json();
    accountEl.innerHTML = `
      <span>Equity: <b>$${acct.portfolio_value.toFixed(2)}</b></span>
      <span>Cash: <b>$${acct.cash.toFixed(2)}</b></span>
      <span>Buying power: <b>$${acct.buying_power.toFixed(2)}</b></span>
    `;
  } catch (e) {
    accountEl.textContent = 'Account unavailable — check Alpaca keys in .env';
  }
}

showSkippedToggle.addEventListener('change', loadTrades);

loadTrades();
refreshAccount();
setInterval(loadTrades, 30000);
setInterval(refreshAccount, 30000);
