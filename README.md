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
- New items and executed trades trigger a browser notification and are read
  aloud (Web Speech API) — toggle off with the checkbox if it gets noisy.

## Take-profit

Independent of the news signal, and only calls Alpaca (no news-API quota
impact): every `TAKE_PROFIT_CHECK_INTERVAL_SECONDS` (default 2 min), each
open position's gain *today* is checked. The first time it's up
`TAKE_PROFIT_PCT` (default 5%), `TAKE_PROFIT_SELL_FRACTION` (default 25%) of
the position is sold — at most once per symbol per calendar day. There's no
symmetric stop-loss; a position down 5% today doesn't trigger anything.

## Configuration (`.env`)

| Var | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | 900 | How often to poll for news (mind the Marketaux quota) |
| `MIN_CONFIDENCE` | 0.6 | Verdicts below this are skipped |
| `MIN_TRADE_USD` / `MAX_TRADE_USD` | 200 / 1000 | Position size range, scaled by confidence |
| `COOLDOWN_MINUTES` | 60 | Minimum gap between trades on the same symbol |
| `SIGNAL_MODEL` | claude-haiku-4-5 | Model used to judge each news item |
| `TAKE_PROFIT_PCT` / `TAKE_PROFIT_SELL_FRACTION` | 0.05 / 0.25 | Take-profit threshold and trim size |
| `TAKE_PROFIT_CHECK_INTERVAL_SECONDS` | 120 | How often positions are checked for take-profit |
| `APP_USERNAME` / `APP_PASSWORD` | *(unset)* | Shared login for the whole app — blank means no login prompt (fine for local use, required once hosted) |

## Hosting (Railway)

The app has an always-running background loop (news poller + take-profit
checker), so it needs a host that keeps a process alive 24/7, not a
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
