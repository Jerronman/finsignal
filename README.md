# FinSignal

Watches financial news ([Marketaux](https://www.marketaux.com)), has Claude
judge each news item's likely price impact per symbol, and automatically
places **paper** trades on Alpaca based on that verdict. A local dashboard
lets you watch (and hear) everything it does, with the reasoning behind
every trade — and every skip.

**This only ever trades Alpaca's paper account (fake money). It does not
place real trades.** Swapping in a real broker later is a deliberate,
separate step (see "Going live later" below).

## How it decides

Every `POLL_INTERVAL_SECONDS` (default 15 min — see the quota note below):

1. Fetch general news from Marketaux, filtered to articles that have at
   least one identified stock entity (Marketaux tags each article with the
   real tickers it's about — no guessing needed).
2. For each new article, ask Claude to judge every tagged symbol in one
   batched call: `buy` / `sell` / `hold`, a confidence 0–1, and one sentence
   of reasoning per symbol.
3. Apply guardrails:
   - `hold` or confidence below `MIN_CONFIDENCE` → skip (logged, not traded).
   - Symbol traded within the last `COOLDOWN_MINUTES` → skip.
   - `sell` with no existing position in that symbol → skip (no shorting by default).
   - Symbol isn't tradable on Alpaca (foreign listing, inactive/expired
     warrant, etc.) → skip. Checked via Alpaca's own asset status before
     attempting an order, so this shows as a clean skip in the Trade Log
     rather than an order-rejection error.
4. If none of those hit: `buy` submits a market order sized between
   `MIN_TRADE_USD` and `MAX_TRADE_USD` (scaled by confidence); `sell` closes
   the existing position.
5. Every outcome — traded or skipped, and why — is logged to SQLite and
   pushed live to the dashboard.

Any symbol Marketaux tags is eligible to be traded — the watchlist (below)
doesn't gate or filter this, per your earlier choice.

**Quota note:** the Marketaux free plan is 100 requests/day. At one request
per poll cycle, 15 minutes keeps you at 96/day with a little headroom. Going
faster requires a higher-quota plan — check Marketaux's pricing if you want
closer-to-real-time polling.

## Setup

1. **Alpaca (paper trading, free)**: sign up at [alpaca.markets](https://alpaca.markets),
   switch to the **Paper Trading** account, generate an API key + secret.
2. **Marketaux**: have your API token ready.
3. **Anthropic**: an API key for the signal engine (console.anthropic.com).
4. Copy `.env.example` to `.env` and fill in the four keys yourself (keeps
   secrets out of any chat history).
5. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

6. **Before running the full app**, sanity-check the news API (uses 1 request):

   ```bash
   python scripts/test_news_api.py
   ```

7. Run the app:

   ```bash
   uvicorn app.main:app --reload
   ```

   Open `http://localhost:8000`.

## Dashboard

- **Activity feed** — every news item, its per-symbol verdict, and the
  resulting trade (or skip reason).
- **Positions / account** — live from your Alpaca paper account.
- **Watchlist** — add/remove symbols; currently informational only (see
  "How it decides" — Marketaux's own tagging drives what's traded, not this
  list). Reserved for a future filter/highlight feature.
- **Trade Log** (`/trades`) — every trade decision (executed or skipped),
  with the source headline, and whether the Alpaca order has actually
  filled yet.
- **Strategy** (`/strategy`) — a plain-language explanation of both the
  buy/sell logic and the take-profit tiers, rendered live from whatever's
  actually configured right now (not a static description that can drift
  out of sync with `.env`).
- **Options** (`/options`) — separate options-trading pipeline, see below.
- New items and executed trades trigger a browser notification and are read
  aloud (Web Speech API) — toggle off with the checkbox if it gets noisy.

## Options trading

A second, independent pipeline that reuses the exact same news verdicts as
stocks (no extra Marketaux calls) but always trades options instead:

- `buy` verdict → **Buy-to-Open a call**; `sell` verdict → **Buy-to-Open a
  put**. Never writes/sells options short, never reacts to `hold`.
- **Weekly, ~`OPTIONS_OTM_PCT`** (default 5%) **out of the money.** Strike
  is the nearest available to that target, at the earliest listed
  expiration on/after the target date (so a holiday or thin chain doesn't
  come up empty).
- **Expiration**: the nearest Friday **at least 2 days out** — a signal on
  Thursday or Friday rolls to the *following* week's Friday instead of the
  1-or-0-day-out one.
- **Liquidity filter** (checked before every order): skipped if open
  interest is below `OPTIONS_MIN_OPEN_INTEREST` (default 50), the bid-ask
  spread is wider than `OPTIONS_MAX_SPREAD_PCT` (default 15% of midpoint),
  or there's no real bid at all.
- **Sizing**: up to `OPTIONS_MAX_TRADE_USD` (default $5,000) per trade —
  `floor(budget / (ask price × 100))` contracts. Skipped entirely if even 1
  contract would exceed the budget.
- **Own cooldown** (`OPTIONS_COOLDOWN_MINUTES`) and confidence bar
  (`OPTIONS_MIN_CONFIDENCE`), independent of the stock pipeline's.
- **Take-profit tiers** (`OPTIONS_TIERS`, default `25:0.25,50:0.25,75:0.25,200:0.25`)
  — the same ratchet mechanic as stocks, but keyed off the option's own
  gain since entry, which moves far more than the underlying stock does.
- **Forced close the Thursday before its own expiration**, regardless of
  P&L — a losing contract is never held into Friday expiration/assignment,
  it's just sold for whatever it's worth by then. This is a time-based
  exit, not a loss-based stop: **there is no stop-loss for options either**,
  by explicit choice — a losing contract rides all the way to that
  Thursday with no early cut.

## Take-profit

Independent of the news signal, and only calls Alpaca (no news-API quota
impact): every `TAKE_PROFIT_CHECK_INTERVAL_SECONDS` (default 2 min), each
open position's gain **since your entry price** is checked (Alpaca's
`unrealized_plpc` — not "today's" move). `TAKE_PROFIT_TIERS` defines a
ratchet: each tier sells a fixed fraction of the **original** share count
the first time it's crossed. Default:

| Gain since entry | Action | Cumulative sold |
|---|---|---|
| +5% | sell 25% of original | 25% |
| +10% | sell another 25% | 50% |
| +20% | sell another 25% | 75% |
| +50% | sell whatever remains | 100% |

If price gaps past several tiers between checks, all newly-crossed tiers
fire in the same pass. "Original" is snapshotted the first time the checker
sees the position open; buying more of the same symbol later doesn't
retroactively grow it until the position fully closes and a fresh plan
starts. **There's no symmetric stop-loss** — a losing position has no
automatic exit here, deliberately deferred for now.

## Configuration (`.env`)

| Var | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | 900 | How often to poll for news (mind the Marketaux quota) |
| `MIN_CONFIDENCE` | 0.6 | Verdicts below this are skipped |
| `MIN_TRADE_USD` / `MAX_TRADE_USD` | 200 / 1000 | Position size range, scaled by confidence |
| `COOLDOWN_MINUTES` | 60 | Minimum gap between trades on the same symbol |
| `SIGNAL_MODEL` | claude-haiku-4-5 | Model used to judge each news item |
| `TAKE_PROFIT_TIERS` | `5:0.25,10:0.25,20:0.25,50:0.25` | Take-profit tiers, `gain%:fraction_of_original` |
| `TAKE_PROFIT_CHECK_INTERVAL_SECONDS` | 120 | How often positions are checked for take-profit |
| `OPTIONS_ENABLED` | true | Master on/off switch for the options pipeline |
| `OPTIONS_OTM_PCT` | 0.05 | How far out of the money to target |
| `OPTIONS_MAX_TRADE_USD` | 5000 | Per-trade budget cap for options |
| `OPTIONS_MIN_OPEN_INTEREST` / `OPTIONS_MAX_SPREAD_PCT` | 50 / 0.15 | Liquidity filter thresholds |
| `OPTIONS_TIERS` | `25:0.25,50:0.25,75:0.25,200:0.25` | Options take-profit tiers, same format as stocks |
| `APP_USERNAME` / `APP_PASSWORD` | *(unset)* | Shared login for the whole app — blank means no login prompt (fine for local use, required once hosted) |

## Hosting (Railway)

The app has three always-running background loops (news poller, stock
take-profit checker, options manager), so it needs a host that keeps a
process alive 24/7, not a
request-only serverless function. It also writes to a local SQLite file, so
it needs persistent storage. [Railway](https://railway.com) fits both, and
doesn't require a credit card to start.

1. Set `APP_USERNAME` and `APP_PASSWORD` in your **local** `.env` first and
   confirm the login prompt works (`uvicorn app.main:app --reload`, reload
   `localhost:8000`) — cheaper to catch typos locally than after deploying.
2. Push this repo to GitHub if you haven't (it already builds from the
   `Dockerfile` in the repo root — Railway auto-detects it).
3. On [railway.com](https://railway.com): New Project → Deploy from GitHub
   repo → pick this repo.
4. **Add a volume**: in the service's Settings → Volumes, mount one at
   `/data`. This is where the SQLite file will live so it survives
   redeploys/restarts.
5. **Set environment variables** (Variables tab) — all the same names as
   your `.env`, but note `DB_PATH` needs to point at the volume:
   ```
   DB_PATH=/data/finsignal.db
   ```
   plus `MARKETAUX_API_TOKEN`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`,
   `ANTHROPIC_API_KEY`, `APP_USERNAME`, `APP_PASSWORD`, and any of the
   trading knobs above you want to override. Enter these directly in
   Railway's dashboard — never commit real values to `.env.example` or the
   repo.
6. Railway assigns a public URL automatically (Settings → Networking →
   Generate Domain). That URL is what you and your dad both use — the
   `Dockerfile` binds to Railway's `$PORT` automatically.
7. Check the deploy logs for the poller/take-profit startup lines to confirm
   the background loops actually started, not just the web server.

## Going live later (real money via Schwab)

Trading is isolated behind `app/broker/base.py`'s `BrokerInterface`. To move
to Schwab:

1. Register a Schwab developer app, implement OAuth + refresh-token handling.
2. Write `app/broker/schwab_broker.py` implementing `BrokerInterface`.
3. Swap the instance in `app/broker/__init__.py` behind a config flag.

**Do this deliberately, not casually** — automated *real-money* trading is a
materially different risk than automated paper trading. Consider adding a
confirmation step, position/day caps, and a kill switch before that swap,
none of which exist today because they weren't needed for paper trading.

## Not built (by design, for now)

- Short selling on bearish signals with no existing position.
- Max concurrent positions / daily trade caps (only the per-symbol cooldown
  guardrail exists).
- Manual approve-before-execute mode — everything here is fully automatic.
- **Stop-loss / downside protection**, for stocks or options. The
  take-profit tiers only manage winners; a losing position has no
  loss-based automatic exit today (options do get a *time*-based forced
  close ahead of expiration, but that's not the same thing).
- **Strike selection beyond "closest to target %"** — no delta-targeting,
  no fallback to a nearby strike if the first choice fails the liquidity
  check (it just skips the trade).
