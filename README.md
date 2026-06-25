# Trading Watch Assistant Agent

[中文文档](README.zh-CN.md)

Trading Watch Assistant Agent is a local, semi-automated market watching assistant for personal use. It reads A-share, Hong Kong, and US stock market data, evaluates user-defined strategies, records signals in SQLite, and optionally sends PushPlus notifications.

It does not predict prices, does not place orders, and does not connect to any brokerage account.

## What It Does

- Reads A-share, Hong Kong, and US stock data.
- Uses multi-source market data fallback to reduce single-provider failures.
- Supports close-mode shadow testing with the latest daily bar.
- Stores stock strategies in YAML.
- Stores run logs and signals in SQLite.
- Supports two decision modes:
  - `rule`: deterministic YAML rule execution.
  - `hybrid`: DeepSeek interprets `human_strategy_text` against current market data, then `DecisionGuard` validates the decision.
- Uses DeepSeek for explanations and hybrid scene analysis.
- Uses PushPlus for optional mobile notifications.
- Provides a local FastAPI Web UI.

## Safety Notice

This project is not financial advice. It does not guarantee returns. It does not trade automatically. All signals are reminders for manual review only. If you place trades manually, you are fully responsible for the result.

## Supported Markets

| Market | Config value | Example symbol |
| --- | --- | --- |
| A-share | `A` | `002299` |
| Hong Kong | `HK` | `00700`, `HK2382`, `02382` |
| US stocks | `US` | `MSFT`, `AAPL` |

## Quick Start

### 1. Clone and Install

```bash
git clone https://github.com/weiyuwu47-pixel/Trading-Watch-Assistant-Agent.git
cd Trading-Watch-Assistant-Agent

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
cp config/stocks.example.yaml config/stocks.yaml
```

If your default `python3` is already Python 3.11 or newer, this is also fine:

```bash
python3 -m venv .venv
```

### 2. Configure Environment Variables

Edit `.env`:

```env
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash

PUSHPLUS_TOKEN=
PUSHPLUS_API_URL=https://www.pushplus.plus/send
PUSHPLUS_NORMAL_CHANNEL=app
PUSHPLUS_URGENT_CHANNEL=voice
PUSHPLUS_ENABLE_VOICE=false
PUSHPLUS_DRY_RUN=true

DB_PATH=data/stock_watch.sqlite
STOCK_CONFIG_PATH=config/stocks.yaml
```

DeepSeek is recommended for hybrid mode:

```env
DEEPSEEK_API_KEY=your_deepseek_key
```

PushPlus is optional. If `PUSHPLUS_TOKEN` is empty, the app prints notifications to the console instead of failing.

Safe defaults:

- `PUSHPLUS_DRY_RUN=true`: no real push notification is sent.
- `PUSHPLUS_ENABLE_VOICE=false`: voice calls are disabled.
- Web-triggered runs force voice off.

### 3. Initialize the Database

```bash
python3 -m app.cli.init_db
```

### 4. Run Basic Checks

```bash
python3 -m compileall app
python3 -m app.cli.validate_strategy
```

### 5. Test Market Data Only

These commands do not call DeepSeek, do not write signals, and do not send PushPlus notifications.

A-share:

```bash
python3 -m app.cli.test_market --symbol 002299 --mode close
```

Hong Kong:

```bash
python3 -m app.cli.test_market --symbol 00700 --mode close
python3 -m app.cli.test_market --symbol HK2382 --mode close
```

US:

```bash
python3 -m app.cli.test_market --symbol MSFT --mode close
```

### 6. Test Hybrid Scene Analysis

This reads market data and calls DeepSeek, but does not write SQLite and does not send PushPlus.

```bash
python3 -m app.cli.test_scene --symbol 02382 --mode close
python3 -m app.cli.test_scene --symbol 002299 --mode close
```

### 7. Run Once

Default rule mode:

```bash
python3 -m app.cli.run_once --symbol 002299 --mode close
```

Hybrid mode:

```bash
python3 -m app.cli.run_once --symbol 02382 --mode close --decision-mode hybrid
```

## Local Web UI

Start the Web UI:

```bash
python3 -m app.web.server
```

Open:

```text
http://127.0.0.1:8000
```

The Web UI can:

- Show DeepSeek and PushPlus configuration status.
- List configured stocks.
- Enable or disable a stock.
- Paste natural-language strategy text.
- Parse strategy text.
- Generate a YAML draft.
- Validate, reverse-explain, and compare strategies.
- Test market data.
- Test hybrid scene analysis.
- Select `decision_mode`: `rule` or `hybrid`.
- Run one stock in close mode.
- View recent SQLite signal records.

The Web UI cannot:

- Place orders.
- Connect to a brokerage account.
- Show API keys or tokens.
- Trigger voice calls by default.

## Background Scheduler

Default scheduled times are Beijing time:

- 11:35
- 14:45
- 15:10

```bash
python3 -m app.main
```

For testing:

```bash
python3 -m app.main --interval-minutes 10
```

## Strategy Configuration

Local strategy file:

```text
config/stocks.yaml
```

This file is intentionally ignored by Git because it may contain personal holdings and strategy details. For a demo setup, copy:

```bash
cp config/stocks.example.yaml config/stocks.yaml
```

Core fields:

- `symbol`: stock symbol.
- `market`: `A`, `HK`, or `US`.
- `enabled`: whether this stock should run.
- `decision_mode`: `rule` or `hybrid`; default is `rule`.
- `valid_until`: strategy expiration date.
- `current_position_shares`: current position.
- `cost_price`: cost basis, used only for risk and position management.
- `max_position_shares`: max allowed shares.
- `max_invest_amount`: max allowed investment amount.
- `min_lot`: lot size. A-share usually uses `100`, US stocks can use `1`, Hong Kong stocks depend on the stock.
- `human_strategy_text`: original natural-language strategy.
- `buy_rules`, `sell_rules`, `hold_rule`: structured rules for rule mode.

US demo example:

```yaml
- symbol: MSFT
  market: US
  name: Microsoft
  enabled: false
  valid_until: '2026-12-31'
  max_invest_amount: 0
  max_position_shares: 0
  current_position_shares: 0
  cost_price: 0
  min_lot: 1
  strategy_style: us_watch_example
  buy_rules: []
  sell_rules: []
  hold_rule:
    explanation_template: US demo strategy has no buy/sell rule, so it holds by default
```

## Rule Mode

`rule` mode executes structured YAML rules exactly. Supported rule types:

- `breakout_recent_high`
- `pullback_ma`
- `break_ma`
- `far_above_ma`
- `reclaim_price_level`
- `break_price_level`
- `break_price_level_down`
- `stabilize_in_price_range`
- `range_rebound_fail`

Optional position condition:

```yaml
position_condition:
  current_position_shares_gt: 7800
```

Supported fields:

- `current_position_shares_gt`
- `current_position_shares_gte`
- `current_position_shares_lt`
- `current_position_shares_lte`
- `current_position_shares_eq`

## Hybrid Mode

`hybrid` mode is designed to reduce semantic drift between natural-language strategy text and generated YAML rules.

Flow:

1. `MultiSourceMarketProvider` reads market data.
2. `SceneAnalyzer` calls DeepSeek and asks it to match current market data against `human_strategy_text`.
3. DeepSeek must return strict JSON with `action`, `shares`, `scene`, `matched_strategy_clause`, `excluded_clauses`, `reason`, and `confidence`.
4. `DecisionGuard` validates the result:
   - action must be `buy`, `sell`, `hold`, or `review`;
   - buy/sell must cite a matched strategy clause;
   - low confidence becomes `review`;
   - share count must match `min_lot`;
   - buy cannot exceed max position or max investment;
   - sell cannot exceed current position or break base-position protection;
   - reasons based on break-even, fear of missing out, or averaging down are rejected.
5. The guarded result becomes the final signal.

Test:

```bash
python3 -m app.cli.test_scene --symbol 02382 --mode close
```

Run:

```bash
python3 -m app.cli.run_once --symbol 02382 --mode close --decision-mode hybrid
```

## Market Data Fallbacks

All providers return a unified `MarketSnapshot`.

Fallback order:

- A-share realtime/auto: EastMoney realtime + AkShare EM daily -> Tencent realtime + AkShare Tencent daily -> EM close -> Tencent close.
- A-share close: EM close -> Tencent close.
- Hong Kong realtime/auto: AkShare HK EM spot + HK daily -> Tencent HK realtime + Sina HK daily -> HK daily close.
- Hong Kong close: AkShare HK EM daily -> Sina HK daily.
- US realtime/auto: AkShare US EM spot + daily -> Yahoo quote + Yahoo daily -> AkShare daily -> Yahoo daily -> Nasdaq daily -> Stooq daily.
- US close: AkShare daily -> Yahoo daily -> Nasdaq daily -> Stooq daily.

Some providers may fail because of proxy, SSL, rate limits, or regional network restrictions. The app records `provider_errors` and automatically tries the next provider. If every provider fails, the signal becomes `review`.

## PushPlus Notifications

Dry-run test:

```bash
python3 -m app.cli.test_notify --action hold
python3 -m app.cli.test_notify --action buy
```

Default behavior:

- `hold` and `review`: normal message.
- `buy` and `sell`: voice first only when `PUSHPLUS_ENABLE_VOICE=true`, then normal fallback.
- `.env.example` does not send real messages and does not call by default.

## Useful Commands

```bash
# Initialize database
python3 -m app.cli.init_db

# Validate strategy config
python3 -m app.cli.validate_strategy

# Reverse-explain a strategy
python3 -m app.cli.explain_strategy --symbol 002299

# Compare natural-language strategy and YAML
python3 -m app.cli.compare_strategy --symbol 002299

# Test market data
python3 -m app.cli.test_market --symbol MSFT --mode close

# Test hybrid scene analysis
python3 -m app.cli.test_scene --symbol 02382 --mode close

# Run once
python3 -m app.cli.run_once --symbol 002299 --mode close

# Start Web UI
python3 -m app.web.server
```

## Demo Notes

- Keep `PUSHPLUS_DRY_RUN=true` on first run.
- Never commit `.env`.
- Never commit real `config/stocks.yaml`.
- Never commit `data/`.
- If a market provider fails, check `provider_errors`.
- Yahoo may return 429; US fallback can continue with Nasdaq.

## Roadmap

- Add trading calendars for A-share, Hong Kong, and US markets.
- Add mock market replay tests.
- Add strategy-change audit logs.
- Add signal export.
