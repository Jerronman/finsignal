const accountEl = document.getElementById('account-summary');

function fmtSeconds(s) {
  if (s % 60 === 0) return `${s / 60} min`;
  return `${s}s`;
}

function fmtPct(fraction) {
  return `${Math.round(fraction * 100)}%`;
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

function renderTiers(tbody, tiers, disabledMessage) {
  if (!tiers) {
    tbody.innerHTML = `<tr><td colspan="3" class="meta">${disabledMessage}</td></tr>`;
    return;
  }
  let cumulative = 0;
  tbody.innerHTML = tiers.map(([threshold, fraction], i) => {
    const isLast = i === tiers.length - 1;
    cumulative = isLast ? 1 : cumulative + fraction;
    const action = isLast
      ? `Sell whatever remains (${fmtPct(fraction)} of original, nominally)`
      : `Sell ${fmtPct(fraction)} of the original position`;
    return `
      <tr>
        <td><strong>+${threshold}%</strong></td>
        <td>${action}</td>
        <td>${fmtPct(cumulative)} sold</td>
      </tr>
    `;
  }).join('');
}

async function load() {
  const res = await fetch('/api/strategy-config');
  const cfg = await res.json();

  document.getElementById('poll-interval').textContent = fmtSeconds(cfg.poll_interval_seconds);
  document.getElementById('min-confidence').textContent = fmtPct(cfg.min_confidence);
  document.getElementById('cooldown').textContent = `${cfg.cooldown_minutes} min`;
  document.getElementById('min-trade').textContent = `$${cfg.min_trade_usd}`;
  document.getElementById('max-trade').textContent = `$${cfg.max_trade_usd}`;
  document.getElementById('tp-interval').textContent = fmtSeconds(cfg.take_profit_check_interval_seconds);

  renderTiers(
    document.getElementById('tiers-body'),
    cfg.take_profit_enabled ? cfg.take_profit_tiers : null,
    'Take-profit is currently disabled (TAKE_PROFIT_ENABLED=false)',
  );
}

async function loadOptions() {
  const res = await fetch('/api/options/config');
  const cfg = await res.json();

  document.getElementById('opt-min-confidence').textContent = fmtPct(cfg.min_confidence);
  document.getElementById('opt-cooldown').textContent = `${cfg.cooldown_minutes} min`;
  document.getElementById('opt-otm').textContent = fmtPct(cfg.otm_pct);
  document.getElementById('opt-oi').textContent = cfg.min_open_interest;
  document.getElementById('opt-spread').textContent = fmtPct(cfg.max_spread_pct);
  document.getElementById('opt-budget').textContent = `$${cfg.max_trade_usd}`;
  document.getElementById('opt-interval').textContent = fmtSeconds(cfg.check_interval_seconds);

  renderTiers(
    document.getElementById('opt-tiers-body'),
    cfg.enabled ? cfg.tiers : null,
    'Options trading is currently disabled (OPTIONS_ENABLED=false)',
  );
}

load();
loadOptions();
refreshAccount();
setInterval(refreshAccount, 30000);
