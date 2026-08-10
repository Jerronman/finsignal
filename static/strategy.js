function fmtSeconds(s) {
  if (s % 60 === 0) return `${s / 60} min`;
  return `${s}s`;
}

function fmtPct(fraction) {
  return `${Math.round(fraction * 100)}%`;
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
