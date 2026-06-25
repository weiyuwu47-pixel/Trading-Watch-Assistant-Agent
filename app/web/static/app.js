const $ = (id) => document.getElementById(id);
let running = false;
let parsedStrategy = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

async function safeAction(fn) {
  try {
    await fn();
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    strategyOutput("操作失败：\n" + message);
    renderJSON($("runOutput"), "操作失败：\n" + message);
  }
}

function renderJSON(target, data) {
  target.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

function strategyOutput(data) {
  renderJSON($("strategyOutput"), data);
}

async function loadStatus() {
  const data = await api("/api/status");
  running = data.run_running;
  $("status").innerHTML = `
    <div><b>DeepSeek</b><span>${data.deepseek_configured ? "已配置" : "未配置"}</span></div>
    <div><b>PushPlus</b><span>${data.pushplus_configured ? "已配置" : "未配置"}</span></div>
    <div><b>后台监控</b><span>${data.scheduler_running ? "运行中" : "未运行"}</span></div>
    <div><b>运行状态</b><span>${data.run_running ? "正在运行" : "空闲"}</span></div>
    <div><b>当前步骤</b><span>${data.current_step}</span></div>
    <div><b>当前时间</b><span>${data.now}</span></div>
    <div><b>数据库</b><span>${data.db_path}</span></div>
    <div><b>策略文件</b><span>${data.stock_config_path}</span></div>
  `;
}

async function loadStocks() {
  const data = await api("/api/stocks");
  $("stocksBody").innerHTML = data.stocks.map((s) => `
    <tr>
      <td>${s.enabled}</td>
      <td>${s.symbol}</td>
      <td>${s.name || ""}</td>
      <td>${s.market || ""}</td>
      <td>${s.current_position_shares ?? ""}</td>
      <td>${s.cost_price ?? ""}</td>
      <td>${s.max_invest_amount ?? ""}</td>
      <td>${s.valid_until ?? ""}</td>
      <td>${s.strategy_style || ""}</td>
      <td class="actions">
        <button onclick="runSymbol('${s.symbol}', 'auto')">运行一次</button>
        <button onclick="validateStrategy()">校验</button>
        <button onclick="explainStrategy('${s.symbol}')">反译</button>
        <button onclick="compareStrategy('${s.symbol}')">对比</button>
        <button onclick="toggleStock('${s.symbol}', ${!s.enabled})">${s.enabled ? "禁用" : "启用"}</button>
        <button onclick="fillForm('${s.symbol}')">编辑</button>
      </td>
    </tr>
  `).join("");
  window.stockCache = data.stocks;
}

function fillForm(symbol) {
  const s = (window.stockCache || []).find((item) => item.symbol === symbol);
  if (!s) return;
  $("formSymbol").value = s.symbol || "";
  $("formMarket").value = s.market || "A";
  $("formName").value = s.name || "";
  $("formMaxInvest").value = s.max_invest_amount || "";
  $("formMaxShares").value = s.max_position_shares || "";
  $("formCurrentShares").value = s.current_position_shares || "";
  $("formBaseShares").value = s.base_position_shares || "";
  $("formTShares").value = s.t_position_shares || "";
  $("formTCash").value = s.t_cash_budget || "";
  $("formCost").value = s.cost_price || "";
  $("formMinLot").value = s.min_lot || 100;
  $("formValidUntil").value = s.valid_until || "";
  $("naturalStrategy").value = s.human_strategy_text || "";
  $("yamlDraft").value = jsyamlLike(s);
  parsedStrategy = {
    symbol: s.symbol,
    name: s.name,
    market: s.market || "A",
    max_invest_amount: s.max_invest_amount || 0,
    max_position_shares: s.max_position_shares || 0,
    current_position_shares: s.current_position_shares || 0,
    base_position_shares: s.base_position_shares || 0,
    t_position_shares: s.t_position_shares || 0,
    t_cash_budget: s.t_cash_budget || 0,
    cost_price: s.cost_price || 0,
    min_lot: s.min_lot || 100,
    valid_until: s.valid_until || "",
    strategy_style: s.strategy_style || "",
  };
  renderJSON($("parsedOutput"), parsedStrategy);
}

function jsyamlLike(obj) {
  return JSON.stringify(obj, null, 2);
}

async function toggleStock(symbol, enabled) {
  const data = await api("/api/stocks/toggle", { method: "POST", body: JSON.stringify({ symbol, enabled }) });
  renderJSON($("runOutput"), data);
  strategyOutput(data);
  await loadStocks();
}

async function validateStrategy() {
  strategyOutput("正在校验策略……");
  const draft = $("yamlDraft").value.trim();
  if (draft) {
    const data = await api("/api/strategy/validate_draft", {
      method: "POST",
      body: JSON.stringify({ symbol: $("formSymbol").value.trim(), yaml_text: draft }),
    });
    strategyOutput(data.output);
    return;
  }
  const data = await api("/api/strategy/validate", { method: "POST", body: "{}" });
  strategyOutput(data.output || data);
}

async function explainStrategy(symbol) {
  strategyOutput("正在反译已保存策略……");
  const data = await api(`/api/strategy/explain?symbol=${encodeURIComponent(symbol)}`);
  strategyOutput(data.output);
}

async function compareStrategy(symbol) {
  strategyOutput("正在进行语义对比……");
  const data = await api(`/api/strategy/compare?symbol=${encodeURIComponent(symbol)}`);
  strategyOutput(data.output);
}

async function runSymbol(symbol, mode, decisionMode = null) {
  if (running) return alert("已有任务正在运行");
  if (symbol && isStockDisabled(symbol)) {
    const msg = `${symbol} 当前在 stocks.yaml 中是 disabled，请先点击股票列表里的“启用”，或保存 enabled=true 的策略后再运行。`;
    renderJSON($("runOutput"), msg);
    strategyOutput(msg);
    return;
  }
  renderJSON($("runOutput"), "正在运行中……");
  const data = await api("/api/run_once", {
    method: "POST",
    body: JSON.stringify({ symbol: symbol || null, mode, decision_mode: decisionMode || $("runDecisionMode").value }),
  });
  renderJSON($("runOutput"), data);
  await loadStatus();
  await loadSignals();
}

async function testMarket(symbol) {
  if (!symbol) return strategyOutput("请先填写股票代码");
  const data = await api("/api/market/test", { method: "POST", body: JSON.stringify({ symbol, mode: "close" }) });
  renderJSON($("runOutput"), data);
}

async function testScene(symbol) {
  if (!symbol) return strategyOutput("请先填写股票代码");
  renderJSON($("runOutput"), "正在测试智能理解……");
  const data = await api("/api/scene/test", {
    method: "POST",
    body: JSON.stringify({ symbol, mode: $("runMode").value || "close" }),
  });
  renderJSON($("runOutput"), data);
}

async function loadSignals() {
  const data = await api("/api/signals/recent");
  $("signalsBody").innerHTML = data.signals.map((s) => `
    <tr>
      <td>${s.triggered_at}</td>
      <td>${s.symbol}</td>
      <td>${s.name}</td>
      <td><span class="badge ${s.action}">${s.action}</span></td>
      <td>${s.shares}</td>
      <td>${s.price ?? ""}</td>
      <td>${s.rule_id}</td>
      <td>${s.reason}</td>
      <td>${s.notified}</td>
      <td>${s.market_source ?? ""}</td>
      <td>${s.trade_date ?? ""}</td>
      <td>${s.is_realtime ?? ""}</td>
    </tr>
  `).join("");
}

async function generateStrategy() {
  if (!validateAdvancedFields()) return;
  strategyOutput("正在生成 YAML 草稿……");
  if (!parsedStrategy) {
    await parseStrategy();
  }
  const payload = {
    symbol: $("formSymbol").value,
    name: $("formName").value,
    market: $("formMarket").value || "A",
    parsed: parsedStrategy || collectAdvancedFields(),
    position: {
      max_invest_amount: Number($("formMaxInvest").value || 0),
      max_position_shares: Number($("formMaxShares").value || 0),
      current_position_shares: Number($("formCurrentShares").value || 0),
      base_position_shares: Number($("formBaseShares").value || 0),
      t_position_shares: Number($("formTShares").value || 0),
      t_cash_budget: Number($("formTCash").value || 0),
      cost_price: Number($("formCost").value || 0),
      min_lot: Number($("formMinLot").value || 100),
      valid_until: $("formValidUntil").value,
    },
    natural_strategy_text: $("naturalStrategy").value,
  };
  const data = await api("/api/strategy/generate", { method: "POST", body: JSON.stringify(payload) });
  $("yamlDraft").value = data.yaml_text || "";
  strategyOutput({ message: data.message, explanation: data.explanation || "" });
}

async function saveStrategy() {
  if (!validateAdvancedFields()) return;
  strategyOutput("正在保存策略……");
  const data = await api("/api/strategy/save", {
    method: "POST",
    body: JSON.stringify({ symbol: $("formSymbol").value, yaml_text: $("yamlDraft").value }),
  });
  strategyOutput(data);
  await loadStocks();
}

async function parseStrategy() {
  strategyOutput("正在解析自然语言策略……");
  const payload = {
    symbol: $("formSymbol").value.trim(),
    name: $("formName").value.trim(),
    market: $("formMarket").value || "A",
    natural_strategy_text: $("naturalStrategy").value,
  };
  const data = await api("/api/strategy/parse", { method: "POST", body: JSON.stringify(payload) });
  parsedStrategy = data.parsed;
  fillAdvancedFields(parsedStrategy);
  renderJSON($("parsedOutput"), parsedStrategy);
  $("parsedOutput").classList.toggle("warn", Boolean((parsedStrategy.missing_fields || []).length || (parsedStrategy.warnings || []).length));
  strategyOutput((parsedStrategy.warnings || []).length ? { warnings: parsedStrategy.warnings, missing_fields: parsedStrategy.missing_fields } : "解析完成");
}

async function explainDraft() {
  const symbol = $("formSymbol").value.trim();
  const draft = $("yamlDraft").value.trim();
  strategyOutput("正在反译策略……");
  if (draft) {
    const data = await api("/api/strategy/explain_draft", {
      method: "POST",
      body: JSON.stringify({ symbol, yaml_text: draft }),
    });
    strategyOutput(data.output);
    return;
  }
  if (!symbol) return alert("请先填写股票代码，或先生成 YAML 草稿");
  const data = await api(`/api/strategy/explain?symbol=${encodeURIComponent(symbol)}`);
  strategyOutput(data.output);
}

async function compareDraft() {
  const symbol = $("formSymbol").value.trim();
  const draft = $("yamlDraft").value.trim();
  strategyOutput("正在进行语义对比……");
  if (draft) {
    const data = await api("/api/strategy/compare_draft", {
      method: "POST",
      body: JSON.stringify({
        symbol,
        yaml_text: draft,
        natural_strategy_text: $("naturalStrategy").value,
      }),
    });
    strategyOutput(data.output);
    return;
  }
  if (!symbol) return alert("请先填写股票代码，或先生成 YAML 草稿");
  const data = await api(`/api/strategy/compare?symbol=${encodeURIComponent(symbol)}`);
  strategyOutput(data.output);
}

function fillAdvancedFields(parsed) {
  $("formMaxInvest").value = parsed.max_invest_amount ?? 0;
  $("formMaxShares").value = parsed.max_position_shares ?? 0;
  $("formCurrentShares").value = parsed.current_position_shares ?? 0;
  $("formBaseShares").value = parsed.base_position_shares ?? parsed.current_position_shares ?? 0;
  $("formTShares").value = parsed.t_position_shares ?? 0;
  $("formTCash").value = parsed.t_cash_budget ?? 0;
  $("formCost").value = parsed.cost_price ?? 0;
  $("formMinLot").value = parsed.min_lot || 100;
  $("formValidUntil").value = parsed.valid_until || "";
}

function collectAdvancedFields() {
  return {
    max_invest_amount: Number($("formMaxInvest").value || 0),
    max_position_shares: Number($("formMaxShares").value || 0),
    current_position_shares: Number($("formCurrentShares").value || 0),
    base_position_shares: Number($("formBaseShares").value || 0),
    t_position_shares: Number($("formTShares").value || 0),
    t_cash_budget: Number($("formTCash").value || 0),
    cost_price: Number($("formCost").value || 0),
    min_lot: Number($("formMinLot").value || 100),
    valid_until: $("formValidUntil").value,
  };
}

function validateAdvancedFields() {
  const fields = ["formMaxInvest", "formMaxShares", "formCurrentShares", "formBaseShares", "formTShares", "formTCash", "formCost", "formMinLot"];
  for (const id of fields) {
    const value = Number($(id).value || 0);
    if (value < 0) {
      alert("高级字段不能为负数，请检查 " + id);
      return false;
    }
  }
  if (Number($("formMinLot").value || 100) <= 0) {
    alert("最小手数必须大于 0");
    $("formMinLot").value = 100;
    return false;
  }
  return true;
}

function isStockDisabled(symbol) {
  const stock = (window.stockCache || []).find((item) => item.symbol === symbol);
  return stock ? stock.enabled === false : false;
}

async function startScheduler() {
  renderJSON($("runOutput"), await api("/api/scheduler/start", { method: "POST", body: "{}" }));
  await loadStatus();
}

async function stopScheduler() {
  renderJSON($("runOutput"), await api("/api/scheduler/stop", { method: "POST", body: "{}" }));
  await loadStatus();
}

function bind() {
  $("refreshStatus").onclick = () => safeAction(loadStatus);
  $("refreshStocks").onclick = () => safeAction(loadStocks);
  $("refreshSignals").onclick = () => safeAction(loadSignals);
  $("runAll").onclick = () => safeAction(() => runSymbol(null, "auto", $("runDecisionMode").value));
  $("runOne").onclick = () => safeAction(() => runSymbol($("runSymbol").value.trim(), $("runMode").value, $("runDecisionMode").value));
  $("runClose").onclick = () => safeAction(() => runSymbol($("runSymbol").value.trim(), "close", $("runDecisionMode").value));
  $("testMarket").onclick = () => safeAction(() => testMarket($("runSymbol").value.trim() || $("formSymbol").value.trim()));
  $("testScene").onclick = () => safeAction(() => testScene($("runSymbol").value.trim() || $("formSymbol").value.trim()));
  $("startScheduler").onclick = () => safeAction(startScheduler);
  $("stopScheduler").onclick = () => safeAction(stopScheduler);
  $("generateStrategy").onclick = () => safeAction(generateStrategy);
  $("saveStrategy").onclick = () => safeAction(saveStrategy);
  $("parseStrategy").onclick = () => safeAction(parseStrategy);
  $("explainDraft").onclick = () => safeAction(explainDraft);
  $("compareDraft").onclick = () => safeAction(compareDraft);
  $("runDraftClose").onclick = () => safeAction(() => runSymbol($("formSymbol").value.trim(), "close", $("runDecisionMode").value));
  $("validateStrategyFromForm").onclick = () => safeAction(validateStrategy);
}

bind();
loadStatus();
loadStocks();
loadSignals();
