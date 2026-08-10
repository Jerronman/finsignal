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

async function load() {
  const res = await fetch('/api/strategy-config');
  const cfg = await res.json();

  document.getElementById('poll-interval').textContent = fmtSeconds(cfg.poll_interval_seconds);
  document.getElementById('min-confidence').textContent = fmtPct(cfg.min_confidence);
  document.getElementById('cooldown').textContent = `${cfg.cooldown_minutes} min`;
  document.getElementById('min-trade').textContent = `$${cfg.min_trade_usd}`;
  document.getElementById('max-trade').textContent = `$${cfg.max_trade_usd}`;
  document.getElementById('tp-interval').textContent = fmtSeconds(cfg.take_profit_check_interval_seconds);

  const tbody = document.getElementById('tiers-body');
  if (!cfg.take_profit_enabled) {
    tbody.innerHTML = '<tr><td colspan="3" class="meta">Take-profit is currently disabled (TAKE_PROFIT_ENABLED=false)</td></tr>';
    return;
  }

  let cumulative = 0;
  tbody.innerHTML = cfg.take_profit_tiers.map(([threshold, fraction], i) => {
    const isLast = i === cfg.take_profit_tiers.length - 1;
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

load();
refreshAccount();
setInterval(refreshAccount, 30000);
