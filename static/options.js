const accountEl = document.getElementById('account-summary');
const optionsPlSummaryEl = document.getElementById('options-pl-summary');
const positionsBody = document.getElementById('positions-body');
const tradesBody = document.getElementById('options-trades-body');
const showSkippedToggle = document.getElementById('show-skipped');

const ALWAYS_VISIBLE = new Set(['bought', 'profit_take', 'expiration_close', 'error', 'skipped_illiquid', 'skipped_no_contract']);

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s || '';
  return div.innerHTML;
}

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
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

function unrealizedSummaryHtml(label, value) {
  if (value == null) return '';
  const up = value >= 0;
  const sign = up ? '+' : '';
  return `
    <div class="pl-summary-line" style="color: ${up ? 'var(--green)' : 'var(--red)'}">
      ${label} unrealized: <b>${sign}$${value.toFixed(2)}</b>
    </div>
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
    if (optionsPlSummaryEl) {
      optionsPlSummaryEl.innerHTML = unrealizedSummaryHtml('Options', acct.options_unrealized_pl);
    }
  } catch (e) {
    accountEl.textContent = 'Account unavailable — check Alpaca keys in .env';
  }
}

function daysUntil(dateStr) {
  if (!dateStr) return '';
  const target = new Date(dateStr + 'T00:00:00');
  const days = Math.round((target - new Date()) / 86400000);
  if (days < 0) return 'expired';
  if (days === 0) return 'today';
  return `${days}d`;
}

async function refreshPositions() {
  try {
    const res = await fetch('/api/options/positions');
    const positions = await res.json();
    if (!Array.isArray(positions) || !positions.length) {
      positionsBody.innerHTML = '<tr><td colspan="8" class="meta">No open option positions</td></tr>';
      return;
    }
    positionsBody.innerHTML = positions.map(p => {
      const up = (p.unrealized_pl ?? 0) >= 0;
      const pct = p.unrealized_plpc != null ? p.unrealized_plpc * 100 : null;
      const sign = up ? '+' : '';
      const qtyLabel = p.original_qty != null ? `${p.qty} / ${p.original_qty}` : p.qty;
      return `
        <tr>
          <td><strong>${escapeHtml(p.underlying_symbol || '?')}</strong></td>
          <td><span class="pill ${p.option_type === 'call' ? 'buy' : 'sell'}">${escapeHtml(p.option_type || '?')}</span></td>
          <td>${p.strike != null ? '$' + p.strike : '—'}</td>
          <td>${p.expiration_date || '—'} (${daysUntil(p.expiration_date)})</td>
          <td>${qtyLabel}</td>
          <td>$${p.avg_entry_price.toFixed(2)}</td>
          <td>${p.current_price != null ? '$' + p.current_price.toFixed(2) : '—'}</td>
          <td style="color: ${up ? 'var(--green)' : 'var(--red)'}">
            ${p.unrealized_pl != null ? sign + '$' + p.unrealized_pl.toFixed(2) : ''}
            ${pct != null ? `(${sign}${pct.toFixed(1)}%)` : ''}
          </td>
        </tr>
      `;
    }).join('');
  } catch (e) {
    positionsBody.innerHTML = '<tr><td colspan="8" class="meta">Positions unavailable — check Alpaca keys in .env</td></tr>';
  }
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

function contractLabel(t) {
  if (!t.contract_symbol) return '—';
  const parts = [];
  if (t.option_type) parts.push(t.option_type);
  if (t.strike != null) parts.push(`$${t.strike}`);
  if (t.expiration_date) parts.push(`exp ${t.expiration_date}`);
  return parts.length ? parts.join(' ') : t.contract_symbol;
}

function rowHtml(t) {
  const why = t.headline
    ? `${escapeHtml(t.reasoning || '')} — <em>${headlineHtml(t.headline, t.headline_url)}</em>`
    : escapeHtml(t.reasoning || '');
  return `
    <tr>
      <td>${escapeHtml(formatTime(t.created_at))}</td>
      <td><strong>${escapeHtml(t.underlying_symbol)}</strong></td>
      <td>${escapeHtml(contractLabel(t))}</td>
      <td><span class="pill ${escapeHtml(t.outcome)}">${escapeHtml(t.outcome.replace(/_/g, ' '))}</span></td>
      <td>${t.qty ?? '—'}</td>
      <td>${fillStatusHtml(t)}</td>
      <td class="why">${why}</td>
    </tr>
  `;
}

async function loadTrades() {
  try {
    const res = await fetch('/api/options/trades?limit=300');
    const trades = await res.json();
    const filtered = showSkippedToggle.checked ? trades : trades.filter(t => ALWAYS_VISIBLE.has(t.outcome));
    tradesBody.innerHTML = filtered.length
      ? filtered.map(rowHtml).join('')
      : '<tr><td colspan="7" class="meta">No options trades yet</td></tr>';
  } catch (e) {
    tradesBody.innerHTML = '<tr><td colspan="7" class="meta">Trades unavailable</td></tr>';
  }
}

showSkippedToggle.addEventListener('change', loadTrades);

refreshAccount();
refreshPositions();
loadTrades();
setInterval(refreshAccount, 30000);
setInterval(refreshPositions, 30000);
setInterval(loadTrades, 30000);
