from __future__ import annotations

import argparse

from app.config import load_app_config, load_stock_configs
from app.llm.deepseek_provider import DeepSeekProvider
from app.strategy.explainer import explain_stock_strategy


def main() -> None:
    parser = argparse.ArgumentParser(description="比较自然语言策略和 YAML 反译摘要是否一致")
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()

    config = load_app_config()
    stocks = load_stock_configs(config.stock_config_path)
    stock = next((item for item in stocks if str(item.get("symbol")) == args.symbol), None)
    if stock is None:
        raise SystemExit(f"未找到股票: {args.symbol}")

    summary = explain_stock_strategy(stock)
    human_text = str(stock.get("human_strategy_text") or "").strip()
    if not human_text:
        print("该股票未配置 human_strategy_text，无法做语义对比。")
        print(summary)
        return
    if not config.deepseek_api_key:
        print("未配置 DEEPSEEK_API_KEY，跳过 LLM 语义校验，请人工核对以下 YAML 反译摘要：")
        print(summary)
        return

    provider = DeepSeekProvider(config.deepseek_api_key, config.deepseek_base_url, config.deepseek_model, timeout=30)
    prompt = _build_compare_prompt(human_text, summary)
    result = provider.complete_text("你是交易策略语义校验助手，只比较文本含义，不给投资建议。", prompt, max_tokens=800)

    if not result:
        print("DeepSeek 不可用，跳过 LLM 语义校验，请人工核对以下 YAML 反译摘要：")
        print(summary)
        return

    print(result)


def _build_compare_prompt(human_text: str, yaml_summary: str) -> str:
    return f"""
请比较“原始自然语言策略”和“YAML反译摘要”是否语义一致。

输出格式必须包含：
1. 结论：✅ 一致 / ⚠️ 部分不一致 / ❌ 严重不一致
2. 原策略条件
3. YAML 当前表达
4. 差异原因
5. 建议修正

只做语义校验，不要给投资建议，不要扩展策略，不要自动修正。
判断规则：
- 如果 YAML 用 position_condition.current_position_shares_gt: base_position_shares 表达“T仓存在”，应视为语义等价。
- 如果 YAML 用 block_buy_rules 表达“禁止买入、停止加仓、需要复核”，应视为合法表达方式。
- 如果 YAML 将模糊词明确量化为 human_strategy_text 已写明的阈值，应视为一致。
- 如果原文包含“附近、最好、优先”等弹性表达，YAML 选择更保守的明确阈值，不改变买/卖方向和股数时，应视为一致。
- 如果原文用均线位置解释关键价附近的盘面状态，而 YAML 用明确价格位表达同一触发区，不应仅因未重复 MA 字段判定不一致。
- 只有当 YAML 改变动作、价位、量能方向、仓位前提或股数时，才判定为不一致。

原始自然语言策略：
{human_text}

YAML反译摘要：
{yaml_summary}
""".strip()


if __name__ == "__main__":
    main()
