# Trading Watch Assistant Agent

本项目是一个本地可运行的个人半自动盯盘 Agent。它不是预测涨跌，也不是自动交易工具，而是“个人交易纪律执行器”：读取 A 股、港股、美股行情，按用户写好的策略判断买入、卖出、不动或复核，再通过 PushPlus 推送提醒。

项目当前支持两种决策模式：

- `rule`：机械规则模式，严格执行 YAML 中的结构化规则。
- `hybrid`：智能盘面理解模式，DeepSeek 根据 `human_strategy_text + 当前行情 + 持仓` 判断当前属于哪个原始策略场景，再由 `DecisionGuard` 做风控校验。

无论哪种模式，本项目都不会自动下单，不接券商接口，不回显任何 API key 或 token。

## 风险声明

本项目不构成投资建议，不保证收益，不自动交易。所有信号只用于个人提醒和复核；用户如手动下单，需自行承担全部风险。

## 功能概览

- A 股 / 港股 / 美股多市场行情读取。
- 多数据源容灾，单个行情源失败时自动 fallback。
- 收盘后 `close` 模式，可用最近交易日日 K 做影子测试。
- YAML 策略配置，最多建议启用 5 只股票。
- 自然语言策略 `human_strategy_text` 保存和语义对比。
- `rule` 模式结构化规则执行。
- `hybrid` 模式智能盘面理解 + 风控校验。
- DeepSeek API 解释信号；DeepSeek 不可用时可降级。
- PushPlus 普通推送和可选 voice，默认 dry-run 且不打电话。
- SQLite 保存 run、signal、raw metrics。
- 本地 Web 管理页面。

## 快速开始

### 1. 克隆和安装

```bash
git clone https://github.com/weiyuwu47-pixel/Trading-Watch-Assistant-Agent.git
cd Trading-Watch-Assistant-Agent

python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config/stocks.example.yaml config/stocks.yaml
```

如果你的系统默认 `python3` 已是 3.11+，也可以用：

```bash
python3 -m venv .venv
```

### 2. 配置 `.env`

`.env.example` 默认如下：

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

DeepSeek 可选但推荐填写：

```env
DEEPSEEK_API_KEY=你的_deepseek_key
```

PushPlus 不配置也能跑 demo；系统会只打印到控制台：

```env
PUSHPLUS_TOKEN=
PUSHPLUS_DRY_RUN=true
PUSHPLUS_ENABLE_VOICE=false
```

安全默认值：

- `PUSHPLUS_DRY_RUN=true`：不会真实发送推送。
- `PUSHPLUS_ENABLE_VOICE=false`：不会打语音电话。
- Web 发起的运行会强制关闭 voice。

### 3. 初始化数据库

```bash
python3 -m app.cli.init_db
```

### 4. 基础检查

```bash
python3 -m compileall app
python3 -m app.cli.validate_strategy
```

### 5. 测试行情，不触发策略、不推送

A 股：

```bash
python3 -m app.cli.test_market --symbol 002299 --mode close
```

港股：

```bash
python3 -m app.cli.test_market --symbol 00700 --mode close
python3 -m app.cli.test_market --symbol HK2382 --mode close
```

美股：

```bash
python3 -m app.cli.test_market --symbol MSFT --mode close
```

### 6. 测试智能理解，不写库、不推送

```bash
python3 -m app.cli.test_scene --symbol 02382 --mode close
python3 -m app.cli.test_scene --symbol 002299 --mode close
```

### 7. 手动运行一次

默认 `rule` 模式：

```bash
python3 -m app.cli.run_once --symbol 002299 --mode close
```

临时使用 `hybrid` 模式：

```bash
python3 -m app.cli.run_once --symbol 02382 --mode close --decision-mode hybrid
```

## 启动 Web Demo

```bash
python3 -m app.web.server
```

浏览器打开：

```text
http://127.0.0.1:8000
```

页面可以：

- 查看 DeepSeek / PushPlus 配置状态。
- 查看、启用、禁用股票。
- 粘贴自然语言策略。
- 解析策略、生成 YAML 草稿、校验策略、反译策略、语义对比。
- 测试行情 close。
- 测试智能理解。
- 选择 `decision_mode`：`rule` 或 `hybrid`。
- 运行一次指定股票。
- 查看最近信号记录。
- 启动或停止后台监控。

页面不会：

- 自动下单。
- 连接券商。
- 默认打语音电话。
- 显示 API key 或 PushPlus token。

## 后台定时运行

默认每天北京时间运行：

- 11:35
- 14:45
- 15:10

```bash
python3 -m app.main
```

测试时可每 N 分钟运行一次：

```bash
python3 -m app.main --interval-minutes 10
```

## 股票配置

策略配置文件：

```text
config/stocks.yaml
```

`config/stocks.yaml` 是本地私有配置，默认被 `.gitignore` 忽略。首次运行 demo 时请复制：

```bash
cp config/stocks.example.yaml config/stocks.yaml
```

核心字段：

- `symbol`：股票代码。A 股如 `002299`，港股如 `00700` 或 `HK2382`，美股如 `MSFT`。
- `market`：`A` / `HK` / `US`。
- `enabled`：是否启用。
- `decision_mode`：`rule` / `hybrid`，不写时默认 `rule`。
- `valid_until`：策略有效期。
- `current_position_shares`：当前持仓。
- `cost_price`：成本价，只用于仓位和风险管理。
- `max_position_shares`：最大持仓。
- `max_invest_amount`：最大投入金额。
- `min_lot`：最小交易单位。A 股常用 100，美股可设 1，港股按真实交易单位配置。
- `human_strategy_text`：原始自然语言策略。
- `buy_rules` / `sell_rules` / `hold_rule`：结构化规则。

美股 demo 示例：

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
    explanation_template: 美股示例未配置买卖规则，默认观察不动
```

## 支持的规则类型

`rule` 模式支持：

- `breakout_recent_high`：放量突破近 N 日高点。
- `pullback_ma`：回踩均线附近。
- `break_ma`：跌破均线。
- `far_above_ma`：高于均线过多。
- `reclaim_price_level`：站回指定价位。
- `break_price_level`：突破指定价位。
- `break_price_level_down`：跌破指定价位。
- `stabilize_in_price_range`：在价格区间内缩量企稳。
- `range_rebound_fail`：反弹区间内未突破关键价且量能不足。

每条买卖规则可以设置：

```yaml
position_condition:
  current_position_shares_gt: 7800
```

支持：

- `current_position_shares_gt`
- `current_position_shares_gte`
- `current_position_shares_lt`
- `current_position_shares_lte`
- `current_position_shares_eq`

## Hybrid Mode

`hybrid` 模式用于降低“自然语言策略”和“机器 YAML 规则”语义不一致的风险。

流程：

1. `MultiSourceMarketProvider` 获取行情。
2. `SceneAnalyzer` 调用 DeepSeek，只根据 `human_strategy_text` 判断当前盘面属于哪个策略场景。
3. DeepSeek 必须输出 JSON：`action`、`shares`、`scene`、`matched_strategy_clause`、`excluded_clauses`、`reason`、`confidence`。
4. `DecisionGuard` 做硬校验：
   - action 必须是 `buy/sell/hold/review`。
   - 买卖必须引用原始策略条款。
   - 低置信度或需要人工复核时转 `review`。
   - 股数必须符合 `min_lot`。
   - 买入不能超过最大持仓和最大投入。
   - 卖出不能超过当前持仓，且不能破坏底仓保护。
   - 不允许因为回本、怕踏空、摊薄成本等理由买卖。
5. 生成最终 Signal。

测试：

```bash
python3 -m app.cli.test_scene --symbol 02382 --mode close
```

运行：

```bash
python3 -m app.cli.run_once --symbol 02382 --mode close --decision-mode hybrid
```

## 行情数据源与容灾

统一数据结构为 `MarketSnapshot`。如果实时失败但日 K 可用，收盘后可继续用最近交易日 close/high/low/open/volume 判断。只有所有数据源失败时才输出 `review`。

Provider 顺序：

- A 股 realtime/auto：EastMoney 实时 + AkShare 东方财富日 K → 腾讯实时 + AkShare 腾讯日 K → 东方财富日 K close → 腾讯日 K close。
- A 股 close：东方财富日 K close → 腾讯日 K close。
- 港股 realtime/auto：AkShare 东方财富港股实时 + 港股日 K → 腾讯港股实时 + 新浪港股日 K → 港股日 K close。
- 港股 close：东方财富港股日 K close → 新浪港股日 K close。
- 美股 realtime/auto：AkShare 东方财富美股实时 + 日 K → Yahoo quote + Yahoo 日 K → AkShare 美股日 K → Yahoo 日 K → Nasdaq 日 K → Stooq 日 K。
- 美股 close：AkShare 美股日 K → Yahoo 日 K → Nasdaq 日 K → Stooq 日 K。

实际网络环境中，部分源可能因为代理、SSL、限流失败。系统会记录 `provider_errors` 并自动尝试下一个源。

## PushPlus 通知

测试 dry-run：

```bash
python3 -m app.cli.test_notify --action hold
python3 -m app.cli.test_notify --action buy
```

默认：

- `hold/review` 普通消息。
- `buy/sell` 在 `PUSHPLUS_ENABLE_VOICE=true` 时先 voice，再普通消息兜底。
- `.env.example` 默认不会真实发送，也不会打电话。

## 常用命令

```bash
# 初始化数据库
python3 -m app.cli.init_db

# 校验策略
python3 -m app.cli.validate_strategy

# 反译策略
python3 -m app.cli.explain_strategy --symbol 002299

# 语义对比
python3 -m app.cli.compare_strategy --symbol 002299

# 测试行情
python3 -m app.cli.test_market --symbol MSFT --mode close

# 测试智能理解
python3 -m app.cli.test_scene --symbol 02382 --mode close

# 运行一次
python3 -m app.cli.run_once --symbol 002299 --mode close

# 启动 Web
python3 -m app.web.server
```

## Demo 注意事项

- 第一次运行请保持 `PUSHPLUS_DRY_RUN=true`。
- 不要把 `.env` 提交到 GitHub。
- 不要把真实 `config/stocks.yaml` 提交到 GitHub；仓库只保留脱敏的 `config/stocks.example.yaml`。
- `data/` 里的 SQLite 数据库不应提交。
- 如果行情接口受限，`test_market` 会显示 provider 错误链路；这是预期容灾行为。
- 美股 Yahoo 可能返回 429，系统会 fallback 到 Nasdaq。
- Web 页面运行前请先刷新，避免浏览器缓存旧 JS。

## 下一步计划

- 增加 A 股 / 港股 / 美股交易日历。
- 增加更多 mock 行情回放测试。
- 增加策略变更审计。
- 增加信号导出。
