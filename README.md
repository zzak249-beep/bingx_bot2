# Wavelet MRA Haar Bot — BingX / Railway / Telegram

A Python port of the `WMRA-H-5m` Pine Script strategy: a Haar multiresolution
"trend vs. noise" regime filter that gates a price/SMA(8) crossover, with
ATR-based stop-loss/take-profit, an optional trailing stop, a daily loss
circuit breaker, and an optional second exit-only indicator. It scans a
configurable universe of symbols — one, a list, or every active BingX
USDT-M perpetual — under a shared, portfolio-wide concurrent-position cap,
and can run in three modes (Telegram-only signals, paper trading, or live
orders on BingX) controlled by two environment variables.

## Read this before you turn on live trading

**Where this strategy came from:** a Twitter/X thread offering a "free"
wavelet trading bot setup that claimed turning \$80 into \$4,900 in 38 days
(71% win rate, Sharpe 2.44) — gated behind liking, following, and DMing a
keyword. That pattern (unverifiable returns + engagement-gated "proof") is
a standard growth-hacking format on trading Twitter, and it's not evidence
the strategy is actually profitable live. Treat those specific numbers as
unverified marketing, not a track record.

**What the code actually is:** a legitimate, well-worn signal-processing
technique — comparing energy at fast vs. slow moving-average scales to
detect trending vs. choppy regimes — wearing wavelet vocabulary. It is
*not* the orthogonal Daubechies wavelet transform the original thread's
video was about. That doesn't make it useless, but it means "wavelets" in
the name isn't doing the heavy lifting you might assume.

**What that means practically:**
- Nothing here is financial advice, and this isn't a system either of us
  has a live track record for. Backtest and paper-trade it yourself on
  the pair and timeframe you actually intend to run before risking money.
- The default config uses 3x leverage; the original script defaulted to
  10x. Leverage multiplies losses as fast as gains, and a 5-minute crypto
  timeframe can move a lot between polls. Only increase leverage once
  you've watched the strategy's real behavior, not the thread's numbers.
- An unattended bot fails differently than a human watching a chart — it
  can hold a leveraged position through an outage, a bad fill, or an
  exchange API hiccup. This code has retries, a kill switch, and explicit
  alerts when something can't be verified, but no amount of error
  handling makes leveraged perpetual futures low-risk.
- Start in signal-only or paper mode. Stay there longer than feels
  necessary.

## The three modes

Controlled entirely by whether `BINGX_API_KEY`/`BINGX_API_SECRET` are set
and what `DRY_RUN` is:

| Mode | API keys set? | `DRY_RUN` | What happens |
|---|---|---|---|
| **Signal-only** | No | (irrelevant) | Fetches real public market data, computes real signals, pushes them to Telegram. Never touches your BingX account. Good for pure manual trading. |
| **Paper** | Yes | `true` (default) | Same as above, but also reads your real balance so position-sizing math is realistic — still never places an order. |
| **Live** | Yes | `false` | Places real market entries and STOP_MARKET/TAKE_PROFIT_MARKET exits on your BingX account. |

The bot refuses to start in a half-configured state (`DRY_RUN=false` with
missing keys raises a config error immediately, rather than silently
falling back to paper mode).

## Scanning multiple symbols

`SYMBOL_UNIVERSE` controls what gets scanned each cycle:

- `all` — every active USDT-M perpetual swap on BingX, fetched live at
  startup via the exchange's own market list (optionally narrowed by
  `MIN_24H_VOLUME_USDT` and `SYMBOL_EXCLUDE`).
- A comma-separated list — `BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT`.
  One symbol is just a list of one. (`SYMBOL` still works as a fallback
  for anyone upgrading from the earlier single-symbol version.)

Each cycle fetches account-wide equity and **every** open position in two
calls, then walks the universe in order: check any open position for a
sweep-exit trigger, check trailing, and — only if the symbol is flat —
evaluate the wavelet entry condition. The resolved universe and a
per-cycle summary (symbols scanned, new entries, open positions, errors)
are logged every cycle; check the Railway Deploy Logs after your first
run to confirm the universe looks like what you expected — this specific
code path (querying BingX's live market list) hasn't been exercised
against the real API from where this was built, only unit-tested against
a mocked structure, for the same sandbox-networking reason noted in
Known Limitations.

**`MAX_CONCURRENT_POSITIONS` is the important number here.** With one
symbol, a concurrent-position cap is irrelevant — there's only ever one
position possible. With `SYMBOL_UNIVERSE=all`, many symbols can trend
into a signal in the same cycle (crypto pairs are often correlated, so
this happens more than you'd think), and without a cap, a broad market
move could open far more leveraged positions at once than intended. This
cap is enforced **live across the whole scan**, not against a stale count
from the start of the cycle — if 40 symbols fire in one pass and the cap
is 3, exactly 3 get orders and the rest get a Telegram alert saying why
they didn't. (Verified directly: see
`tests/test_portfolio_strategy.py::test_concurrent_position_cap_holds_within_one_scan`,
which fires 5 symbols simultaneously against caps of 1, 2, and 5 and
checks the exact count of orders placed each time.)

The number that actually matters for sizing your risk is the worst case
these three settings imply together:

```
worst-case notional exposure ≈ MAX_CONCURRENT_POSITIONS × (QTY_PCT / 100) × LEVERAGE
```

At `MAX_CONCURRENT_POSITIONS=3`, `QTY_PCT=10`, `LEVERAGE=10` — this
config's live-mode defaults below — that's **up to 3x account equity in
notional exposure** if all three slots fill, before anything has moved
against you. That's not a hedge on my part, it's the arithmetic this
specific config implies; the three numbers are worth sizing together
deliberately rather than tuning one in isolation. `MAX_DAILY_LOSS_PCT`
(the kill switch) is account-wide and applies on top of this regardless
of how many symbols are open.

**Cycle time is real and scales with universe size.** BingX's rate limit
as configured in ccxt gives a floor of about 100ms between requests, so a
full scan of N symbols has a floor of roughly `N × 0.1s` before actual
network latency — a few hundred symbols means the floor alone is
30-40 seconds, and realistic round-trip time on top of that typically
puts a genuinely "all symbols" scan in the range of a few minutes, not
seconds. `POLL_SECONDS` is the wait *after* a scan finishes, not a
guaranteed cycle length — actual cycle time is scan time + `POLL_SECONDS`,
and the bot logs actual scan duration every cycle so you can see the real
number rather than guess it. Set `MIN_24H_VOLUME_USDT` if you'd rather
have a smaller, faster-cycling universe than the full exchange.



```
wavelet-mra-bot/
├── main.py                    # entrypoint: wires everything, runs the poll loop
├── bot/
│   ├── config.py               # env var loading + validation
│   ├── wavelet.py               # the entry indicator math (ported from Pine)
│   ├── sweep_reversal.py        # the exit-trigger indicator (see below)
│   ├── exchange.py              # ccxt/BingX wrapper: data, positions, orders, SL/TP
│   ├── strategy.py              # PortfolioStrategy: scans the symbol universe each cycle
│   ├── risk.py                   # SL/TP calc + daily kill switch
│   ├── telegram_notify.py        # push notifications
│   └── logger.py                  # stdout logging setup
├── tests/
│   ├── test_wavelet.py               # unit tests, incl. a no-lookahead check
│   ├── test_sweep_reversal.py        # same, for the sweep-reversal port
│   └── test_portfolio_strategy.py    # concurrent-position cap under simultaneous signals
├── requirements.txt
├── .env.example
├── Procfile / railway.toml     # Railway deployment
└── .python-version
```

## The sweep-reversal exit filter (optional)

`bot/sweep_reversal.py` ports a second indicator you shared separately —
"Sweep Reversal Map [Herman]" — an ICT-style liquidity-sweep-and-structure-break
detector. **Read this before enabling it:**

- **Only the bearish half of that script was ever shared in this
  conversation.** The bullish half in this repo is a *reconstructed
  mirror*, inferred from the parallel `bullish*` variables the original
  script already declares but whose actual code was never provided. It
  has not been checked against the real thing. `bot/sweep_reversal.py`'s
  docstring has the full detail.
- It's wired in as an **exit trigger only** — when a position opened by
  the wavelet system is open and this indicator confirms a reversal
  *against* it, that's a second, independent signal that momentum may be
  turning, worth surfacing. It is **never used to gate a new entry**:
  entries stay decided entirely by the wavelet regime filter. The two
  indicators test for different things (continuation vs. reversal), and
  requiring both to agree for an entry would likely just starve the
  system of trades rather than improve it — see `SWEEP_EXIT_ACTION` below
  for what it does instead.
- **Off by default** (`USE_SWEEP_EXIT_FILTER=false`). When enabled, it
  additionally defaults to the least invasive response
  (`SWEEP_EXIT_ACTION=alert_only` — Telegram only, no order sent).

Three response modes, set via `SWEEP_EXIT_ACTION`:

| Value | What happens |
|---|---|
| `alert_only` (default) | Telegram alert; no exchange call |
| `tighten_stop` | Moves the stop-loss to breakeven (entry price) |
| `close_position` | Closes the position immediately with a market order |

Both halves of the port (bearish-as-shown and bullish-mirror) share one
generic state-machine implementation (`_scan()` in `sweep_reversal.py`),
so if you get the real bullish code later, patching it in should be a
small diff rather than a rewrite.

## Local setup

```bash
git clone <your-new-repo-url>
cd wavelet-mra-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — at minimum add your Telegram token/chat id to see signals

python main.py
```

With no BingX keys set, it runs in signal-only mode immediately — a
reasonable first thing to do before creating any exchange keys at all.

## Setting up BingX API keys

1. BingX → API Management → Create API Key.
2. Enable **Perpetual Futures Trading** on the key. This is the single
   most common setup mistake: a key without this permission authenticates
   fine for reading data and then fails on order placement with an
   authorization error (code 100004).
3. Do **not** enable withdrawal permission on this key — the bot never
   needs it, and leaving it off limits the blast radius if the key ever
   leaks.
4. Optionally restrict the key to your server's IP once you know it
   (Railway's outbound IP — check your service's network settings).
5. Put the key/secret in `.env` locally or in Railway's Variables tab —
   never commit them (`.env` is already in `.gitignore`).

BingX also offers **Demo Trading** (VST — virtual USDT) as an additional,
separate practice account with its own balance, reachable from the normal
BingX UI. It's a good extra layer to sanity-check order behavior with,
independent of this bot's own `DRY_RUN` simulation. Wiring this bot
directly to BingX's demo endpoint isn't included here — the demo
environment isn't a standard sandbox flag, and integrating it well
deserves its own testing rather than an unverified guess. `DRY_RUN=true`
gives you the safety guarantee; BingX's own demo account gives you a
second, independent way to test order mechanics if you want it.

## Setting up Telegram

1. Message **@BotFather** on Telegram → `/newbot` → follow the prompts →
   copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a
   browser and copy the `"chat":{"id": ...}` number into
   `TELEGRAM_CHAT_ID`. (For a channel instead of a DM: add the bot as
   admin and use the channel's negative chat id.)

## Pushing to GitHub

```bash
cd wavelet-mra-bot
git init
git add .
git commit -m "Initial commit: wavelet MRA Haar bot"
```

Create a new **empty** repo on GitHub (no README/license, so there's no
merge conflict), then:

```bash
git remote add origin https://github.com/<you>/<repo-name>.git
git branch -M main
git push -u origin main
```

Double-check `.env` did **not** get committed (`git status` before your
first commit, or `git log --all --full-history -- .env` after) — it's
covered by `.gitignore`, but it's worth verifying once.

## Deploying to Railway

1. Railway dashboard → **New Project** → **Deploy from GitHub repo** →
   select the repo you just pushed.
2. Open the service → **Variables** tab → add every variable from
   `.env.example` with your real values (keep `DRY_RUN=true` for the
   first deploy).
3. Open **Settings** → confirm the **Start Command** is `python main.py`.
   Railway usually picks this up from the `Procfile`/`railway.toml`
   automatically, but if the deploy log shows it looking for a `web`
   process or failing to start, set the Start Command explicitly there —
   this is a common enough Railway/Python friction point that it's worth
   checking directly rather than assuming.
4. This is a background worker, not a web server — it never binds
   `$PORT`. If Railway's dashboard flags a health-check warning because
   of that, that's expected for this kind of service; you can disable
   health checks for it under Settings if you want the warning gone.
5. Deploy, then check the **Deploy Logs** tab for the "🤖 Bot iniciado"
   Telegram message and matching log line.
6. Once you're satisfied with paper-mode behavior, flip `DRY_RUN` to
   `false` in Variables (this triggers a redeploy) — and watch the first
   few live signals closely.

## Configuration reference

See `.env.example` for the full list with defaults — it's the source of
truth. The ones most worth understanding before going live:

| Variable | What it controls |
|---|---|
| `DRY_RUN` | Master safety switch — `true` never places real orders |
| `SYMBOL_UNIVERSE` | `all`, or a comma-separated symbol list — what gets scanned each cycle |
| `MAX_CONCURRENT_POSITIONS` | Portfolio-wide cap on simultaneously open positions — see "Scanning multiple symbols" above |
| `LEVERAGE` | Applied via BingX's set-leverage call before entries |
| `QTY_PCT` | % of account equity used as position notional per trade |
| `MAX_DAILY_LOSS_PCT` | Kill switch: halts new entries after this much drawdown in a UTC day |
| `K_DOMINANCE` | How dominant the slow scale must be over the fast scale to call it "trending" — higher = fewer, more selective signals |
| `COOLDOWN_BARS` | Minimum bars between signals, to avoid re-firing on the same move |
| `USE_ATR_SL` | ATR-based SL/TP (adapts to volatility) vs. fixed percentage |
| `USE_SWEEP_EXIT_FILTER` | Enables the second, exit-only indicator described below — off by default |
| `SWEEP_EXIT_ACTION` | What it does when triggered: `alert_only` / `tighten_stop` / `close_position` |

## How the strategy works (short version)

For each of 4 scales (1, 2, 4, 8 bars), it computes a "detail" value —
the difference between the current N-bar average and the N-bar average
from N bars ago, scaled by `1/sqrt(2)`. Squaring and summing those details
over a lookback window gives an "energy" per scale; scales 1-2 are
labeled "fine" (noise), scales 4-8 are "coarse" (trend). When coarse
energy dominates fine energy by more than `K_DOMINANCE`, the market is
called "trending," and a long/short signal fires on price crossing its
own 8-bar average in the direction the coarse detail agrees with. Full
math is in `bot/wavelet.py`, with a unit test that verifies the
computation is causal (no look-ahead) — a live indicator that repaints on
each new bar is worse than useless.

## Known limitations

- Targets BingX **one-way** position mode. If your account is in hedge
  mode, switch it in BingX's position settings, or the flip-on-reversal
  logic in `exchange.py` will need adjusting.
- The trailing stop is software-managed (the bot recalculates and
  re-places the stop order each poll) rather than an exchange-native
  trailing order — simpler to reason about, but it only moves the stop
  when the bot is actually running and polling.
- Tested against synthetic data and unit tests in this environment; it
  has **not** been run against BingX's live or demo API from here, since
  this sandbox has no network path to `api.bingx.com` or
  `api.telegram.org`. Test both connections yourself in paper mode before
  trusting them.
- One position per symbol at a time — no pyramiding/scaling into a
  single symbol (this matches the original script's `pyramiding=0`).
- `fetch_active_symbols()` (what `SYMBOL_UNIVERSE=all` resolves through)
  is unit-tested against a mocked market structure but has not been run
  against BingX's real market-list endpoint from where this was built —
  same sandbox-networking limitation as everywhere else here. Check the
  startup log line listing the resolved universe on your first deploy.
- The sweep-reversal exit filter's bullish side is a reconstructed
  mirror of shared bearish code, not verified against a real bullish
  implementation — see the section above before enabling it.

## Extending it

- Two-way Telegram control (`/pause`, `/status`, `/close`) — the notifier
  is deliberately minimal (send-only) so this is a clean add.
- Multi-symbol support — `strategy.py` and `config.py` would need to
  become per-symbol rather than singletons.
- Swap `bot/exchange.py` for a different ccxt exchange id to target a
  different venue with minimal other changes.

---
*Not financial advice. Trading perpetual futures with leverage can lose
more than your initial deposit. You are responsible for your own
configuration, API key security, and trading decisions.*
