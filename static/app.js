const feedEl = document.getElementById('feed');
const positionsEl = document.getElementById('positions');
const accountEl = document.getElementById('account-summary');
const watchlistListEl = document.getElementById('watchlist-list');
const watchlistForm = document.getElementById('watchlist-form');
const watchlistInput = document.getElementById('watchlist-input');
const speakToggle = document.getElementById('speak-toggle');

const cardsByArticle = new Map();

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s || '';
  return div.innerHTML;
}

function speak(text) {
  if (!speakToggle.checked || !('speechSynthesis' in window)) return;
  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = 1.05;
  window.speechSynthesis.speak(utter);
}

function notify(title, body) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  new Notification(title, { body });
}

function headlineHtml(headline, url) {
  const text = escapeHtml(headline);
  if (url && /^https?:\/\//i.test(url)) {
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${text}</a>`;
  }
  return text;
}

function renderCard(item) {
  if (cardsByArticle.has(item.id)) return cardsByArticle.get(item.id);
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.articleId = item.id;
  const symbols = (item.symbols && item.symbols.length ? item.symbols.join(', ') : '—');
  card.innerHTML = `
    <div class="headline">${headlineHtml(item.headline, item.url)}</div>
    <div class="meta">${escapeHtml(symbols)} · ${escapeHtml(item.published_at || '')}</div>
    <div class="verdicts"></div>
  `;
  feedEl.prepend(card);
  cardsByArticle.set(item.id, card);
  return card;
}

function upsertPill(articleId, symbol, cssClass, label) {
  const card = cardsByArticle.get(articleId);
  if (!card) return;
  const verdictsEl = card.querySelector('.verdicts');
  const key = `${articleId}:${symbol}`;
  let pill = verdictsEl.querySelector(`[data-key="${key}"]`);
  if (!pill) {
    pill = document.createElement('span');
    pill.dataset.key = key;
    verdictsEl.appendChild(pill);
  }
  pill.className = `pill ${cssClass}`;
  pill.textContent = `${symbol}: ${label}`;
}

async function loadInitialFeed() {
  const res = await fetch('/api/news?limit=50');
  const rows = await res.json();

  const byArticle = new Map();
  for (const row of rows) {
    if (!byArticle.has(row.article_id)) {
      byArticle.set(row.article_id, {
        id: row.article_id,
        headline: row.headline,
        url: row.url,
        published_at: row.published_at,
        symbols: (row.symbols || '').split(',').filter(Boolean),
        verdicts: [],
      });
    }
    if (row.verdict_symbol) {
      byArticle.get(row.article_id).verdicts.push(row);
    }
  }

  // rows arrive newest-first; reverse so prepend ends up in the right order
  const articles = Array.from(byArticle.values()).reverse();
  for (const art of articles) {
    renderCard(art);
    for (const v of art.verdicts) {
      const cls = v.outcome || v.action;
      const label = v.outcome
        ? v.outcome.replace(/_/g, ' ')
        : `${v.action} (${Math.round((v.confidence || 0) * 100)}%)`;
      upsertPill(art.id, v.verdict_symbol, cls, label);
    }
  }
}

async function refreshPositions() {
  try {
    const res = await fetch('/api/positions');
    const positions = await res.json();
    if (!Array.isArray(positions) || !positions.length) {
      positionsEl.innerHTML = '<div class="meta">No open positions</div>';
      return;
    }
    positionsEl.innerHTML = positions.map(p => {
      const up = (p.unrealized_pl ?? 0) >= 0;
      const pct = p.unrealized_plpc != null ? p.unrealized_plpc * 100 : null;
      const sign = up ? '+' : '';
      const qty = parseFloat(p.qty.toFixed(3));
      return `
        <div class="positions-row">
          <span title="${escapeHtml(p.name || p.symbol)}">${escapeHtml(p.symbol)} · ${qty} sh</span>
          <span style="color: ${up ? 'var(--green)' : 'var(--red)'}">
            ${p.unrealized_pl != null ? sign + '$' + p.unrealized_pl.toFixed(2) : ''}
            ${pct != null ? `(${sign}${pct.toFixed(2)}%)` : ''}
          </span>
        </div>
      `;
    }).join('');
  } catch (e) {
    positionsEl.innerHTML = '<div class="meta">Positions unavailable — check Alpaca keys in .env</div>';
  }
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

async function loadWatchlist() {
  const res = await fetch('/api/watchlist');
  const symbols = await res.json();
  watchlistListEl.innerHTML = symbols.map(s => `
    <li>${escapeHtml(s)} <button data-symbol="${escapeHtml(s)}">remove</button></li>
  `).join('');
}

watchlistForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const symbol = watchlistInput.value.trim().toUpperCase();
  if (!symbol) return;
  await fetch('/api/watchlist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol }),
  });
  watchlistInput.value = '';
  loadWatchlist();
});

watchlistListEl.addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-symbol]');
  if (!btn) return;
  await fetch(`/api/watchlist/${btn.dataset.symbol}`, { method: 'DELETE' });
  loadWatchlist();
});

function connectStream() {
  const es = new EventSource('/api/news/stream');
  es.onmessage = (evt) => {
    const data = JSON.parse(evt.data);
    if (data.type === 'news') {
      renderCard(data);
      notify('New financial news', data.headline);
      speak(data.headline);
    } else if (data.type === 'verdict') {
      const label = `${data.action} (${Math.round((data.confidence || 0) * 100)}%)`;
      upsertPill(data.article_id, data.symbol, data.action, label);
    } else if (data.type === 'trade') {
      upsertPill(data.article_id, data.symbol, data.outcome, data.outcome.replace(/_/g, ' '));
      let label;
      if (data.outcome === 'bought') {
        label = `Bought $${(data.amount_usd || 0).toFixed(0)} of ${data.symbol}`;
      } else if (data.outcome === 'profit_take') {
        label = `Took profit: sold ${data.qty} shares of ${data.symbol}`;
      } else if (data.outcome === 'sold') {
        label = `Sold position in ${data.symbol}`;
      } else {
        label = `${data.symbol}: ${data.outcome.replace(/_/g, ' ')}`;
      }
      notify('Paper trade executed', label);
      speak(label);
      refreshPositions();
      refreshAccount();
    }
  };
  es.onerror = () => {
    es.close();
    setTimeout(connectStream, 3000);
  };
}

if ('Notification' in window && Notification.permission === 'default') {
  Notification.requestPermission();
}

loadInitialFeed();
refreshPositions();
refreshAccount();
loadWatchlist();
connectStream();
setInterval(refreshPositions, 30000);
setInterval(refreshAccount, 30000);
