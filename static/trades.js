const accountEl = document.getElementById('account-summary');
const tbody = document.getElementById('trades-body');
const outcomeFiltersEl = document.getElementById('outcome-filters');
const symbolFilterInput = document.getElementById('symbol-filter');
const paginationEl = document.getElementById('pagination');

const PAGE_SIZE = 100;

// Every outcome a trade row can have, in display order. Labels are the
// human-readable form; the button itself is styled via the same .pill
// classes used for the Outcome column so colors line up.
const OUTCOMES = [
  { value: 'bought', label: 'Bought' },
  { value: 'sold', label: 'Sold' },
  { value: 'profit_take', label: 'Profit take' },
  { value: 'error', label: 'Error' },
  { value: 'skipped_not_tradable', label: 'Skipped: not tradable' },
  { value: 'skipped_cooldown', label: 'Skipped: cooldown' },
  { value: 'skipped_hold', label: 'Skipped: hold' },
  { value: 'skipped_low_confidence', label: 'Skipped: low confidence' },
  { value: 'skipped_no_position', label: 'Skipped: no position' },
];

// Active by default -- matches the old "show skipped decisions too" unchecked
// default view (attempted trades + blocks, not routine guardrail skips).
const activeOutcomes = new Set(['bought', 'sold', 'profit_take', 'error', 'skipped_not_tradable']);

let pageTrades = [];     // rows for the currently loaded page (already server-paginated + symbol-filtered)
let currentPage = 0;     // 0-indexed
let currentQuery = '';   // '' = no symbol search active
let totalCount = 0;      // total rows matching currentQuery, across all pages
let searchDebounceTimer = null;

function renderOutcomeFilters() {
  outcomeFiltersEl.innerHTML = OUTCOMES.map(o => `
    <button type="button"
      class="outcome-btn pill ${escapeHtml(o.value)} ${activeOutcomes.has(o.value) ? 'active' : ''}"
      data-outcome="${escapeHtml(o.value)}">${escapeHtml(o.label)}</button>
  `).join('');
}

outcomeFiltersEl.addEventListener('click', (e) => {
  const btn = e.target.closest('.outcome-btn');
  if (!btn) return;
  const outcome = btn.dataset.outcome;
  if (activeOutcomes.has(outcome)) {
    activeOutcomes.delete(outcome);
  } else {
    activeOutcomes.add(outcome);
  }
  btn.classList.toggle('active');
  renderTrades();
});

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

function realizedPlHtml(t) {
  if (t.realized_pl == null) return '<span class="meta">—</span>';
  const up = t.realized_pl >= 0;
  const sign = up ? '+' : '';
  return `<span style="color: ${up ? 'var(--green)' : 'var(--red)'}">${sign}$${t.realized_pl.toFixed(2)}</span>`;
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
      <td>${realizedPlHtml(t)}</td>
      <td>${fillStatusHtml(t)}</td>
      <td class="why">${why}</td>
    </tr>
  `;
}

function renderTrades() {
  // AND filter: this page's rows already matched the symbol search server-side
  // (see loadPage) -- this just further narrows by the active outcome buttons.
  const filtered = pageTrades.filter(t => activeOutcomes.has(t.outcome));

  const emptyReason = activeOutcomes.size === 0
    ? 'No outcome filters selected'
    : currentQuery
      ? `No trades matching "${escapeHtml(currentQuery)}"`
      : 'No trades yet';

  tbody.innerHTML = filtered.length
    ? filtered.map(rowHtml).join('')
    : `<tr><td colspan="7" class="meta">${emptyReason}</td></tr>`;
}

function renderPagination() {
  const start = totalCount === 0 ? 0 : currentPage * PAGE_SIZE + 1;
  const end = Math.min((currentPage + 1) * PAGE_SIZE, totalCount);
  const hasPrev = currentPage > 0;
  const hasNext = end < totalCount;

  paginationEl.innerHTML = `
    <button type="button" id="prev-page" ${hasPrev ? '' : 'disabled'}>◀ Prev</button>
    <span class="meta">${start}–${end} of ${totalCount}</span>
    <button type="button" id="next-page" ${hasNext ? '' : 'disabled'}>Next ▶</button>
  `;
  document.getElementById('prev-page').addEventListener('click', () => {
    if (!hasPrev) return;
    currentPage -= 1;
    loadPage();
  });
  document.getElementById('next-page').addEventListener('click', () => {
    if (!hasNext) return;
    currentPage += 1;
    loadPage();
  });
}

async function loadPage() {
  // Server-paginated: only `limit` rows cross the wire per request, and the
  // `symbol` search runs at the database level (not client-side over an
  // already-fetched batch), so an old match is never missed just because a
  // lot of trading has happened since.
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: currentPage * PAGE_SIZE });
  if (currentQuery) params.set('symbol', currentQuery);
  try {
    const res = await fetch(`/api/trades?${params}`);
    const data = await res.json();
    pageTrades = data.trades;
    totalCount = data.total;
  } catch (e) {
    pageTrades = [];
    totalCount = 0;
  }
  renderTrades();
  renderPagination();
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

symbolFilterInput.addEventListener('input', () => {
  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    currentQuery = symbolFilterInput.value.trim();
    currentPage = 0; // a new search always starts back at page 1
    loadPage();
  }, 300);
});

renderOutcomeFilters();
loadPage();
refreshAccount();
setInterval(loadPage, 30000);
setInterval(refreshAccount, 30000);
