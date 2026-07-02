# byoa_coach_demo_case — 部署指南

**目标：** 将一个简化版 BYOA Agent 部署到 BTP Cloud Foundry Trial，使用智谱 GLM-4-Flash + Mock 数据，通过标准 A2A 协议对外提供服务。

**环境信息：**
- CF API: `https://api.cf.us10-001.hana.ondemand.com`
- Org: `5d1d4790trial_test1-w2lww3zy`
- Space: `dev-cliff`
- App 名称: `byoa-coach-demo`
- App URL: `https://byoa-coach-demo.cfapps.us10-001.hana.ondemand.com`

---

## 架构概览

```
HTTP Client (curl / Joule)
        │  POST /  (A2A JSON-RPC)
        ▼
__main__.py  ── A2AStarletteApplication (uvicorn)
        │
        ▼
executor.py  ── InvoiceAgentExecutor (AgentExecutor)
        │
        ▼
agent.py     ── LangGraph 双节点图
        ├── node "agent"   : System Prompt + Mock 数据 → GLM-4-Flash
        └── node "respond" : 状态分类 (completed / input_required / error)
```

**依赖说明：**
- `a2a-sdk` — A2A 协议 HTTP Server，与 Joule 集成的标准框架
- `langgraph` — Agent 推理图
- `langchain-openai` — 兼容 OpenAI 格式调用智谱 GLM
- 无 XSUAA、无 OData、无 SAP AI Core

---

## 前置条件

### 1. 安装 CF CLI

```bash
# macOS
brew install cloudfoundry/tap/cf-cli@8

# 验证
cf version
# cf version 8.x.x+...
```

### 2. 安装 uv（Python 包管理）

```bash
pip install uv
uv --version
```

### 3. 安装 Python 3.13

```bash
# macOS
brew install python@3.13
python3.13 --version
```

---

## Step 1 — 登录 CF

```bash
cf login -a https://api.cf.us10-001.hana.ondemand.com --sso
```

浏览器会弹出 SSO 页面，登录 SAP BTP Trial 账号。登录后选择：
- Org: `5d1d4790trial_test1-w2lww3zy`
- Space: `dev-cliff`

验证：
```bash
cf target
# API endpoint:   https://api.cf.us10-001.hana.ondemand.com
# org:            5d1d4790trial_test1-w2lww3zy
# space:          dev-cliff
```

---

## Step 2 — 进入项目目录

```bash
cd <path-to>/byoa_coach_demo_case
```

目录结构应为：
```
byoa_coach_demo_case/
├── src/
│   ├── __init__.py
│   ├── agent.py
│   ├── executor.py
│   └── __main__.py
├── pyproject.toml
├── Procfile
├── runtime.txt
└── manifest.yml
```

---

## Step 3 — 导出 requirements.txt

CF Python buildpack 需要 `requirements.txt`，用 uv 从 `pyproject.toml` 生成：

```bash
uv venv && source .venv/bin/activate
uv sync
uv export --format requirements-txt --no-hashes -o requirements.txt
```

验证：
```bash
head -5 requirements.txt
# 应看到 a2a-sdk、langgraph、langchain-openai 等
```

---

## Step 4 — 设置环境变量

在 `manifest.yml` 的 `env` 块中填入真实 key：

```yaml
env:
  ZHIPU_API_KEY: de769874390945d58c4a0458d2b9962a.c3uvnHDvBxBi92q0
  USE_MOCK_DATA: "true"
  LOG_LEVEL: INFO
```

> **注意：**
> - 不要设置 `PORT`：CF 会自动注入，手动设置会报错 `Env cannot set PORT`
> - 不要把真实 key 提交到 GitHub，推送前替换为占位符 `YOUR_ZHIPU_API_KEY`

---

## Step 5 — CF Push

```bash
cf push
```

CF 会读取 `manifest.yml` 自动完成：
1. 上传代码
2. 选择 `python_buildpack`
3. 安装 `requirements.txt` 依赖
4. 执行 `Procfile` 中的启动命令：`python -m src`

预计耗时：2 ~ 4 分钟。

成功标志：
```
name:              byoa-coach-demo
requested state:   started
routes:            byoa-coach-demo.cfapps.us10-001.hana.ondemand.com
```

---

## Step 6 — 验证部署（测试闭环）

### 6.1 前置检查：浏览器打开 Agent Card

在浏览器直接访问：

```
https://byoa-coach-demo.cfapps.us10-001.hana.ondemand.com/.well-known/agent.json
```

看到以下 JSON 说明 Agent 在线：

```json
{
  "name": "Billing Validator Demo Agent",
  "version": "1.0.0",
  "url": "https://byoa-coach-demo.cfapps.us10-001.hana.ondemand.com/",
  "capabilities": {"streaming": true, "pushNotifications": true},
  "skills": [{"id": "billing_validate", "name": "Billing Validator & Summary"}]
}
```

---

### 6.2 Bruno 三轮对话测试

> **推荐工具：[Bruno](https://www.usebruno.com/)** — 本地 API 测试工具，类似 Postman，免费无需注册。
> 也可用 Postman / Hoppscotch（在线，无需安装）等任意 HTTP 工具。

#### Bruno 配置

| 项目 | 值 |
|------|-----|
| Method | `POST` |
| URL | `https://byoa-coach-demo.cfapps.us10-001.hana.ondemand.com/` |
| Header | `Content-Type: application/json` |
| Body | JSON（见下方各轮） |

> ⚠️ **常见错误：** 粘贴 JSON 后，检查 Body 最后一行必须是 `}` 结尾，不能有多余字符（如 `}v`），否则报 `Extra data` 解析错误。

---

#### Round 1 — 账单总览（首轮，无 contextId）

Body 完整粘贴：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "帮我总结一下当前账单状态"}],
      "messageId": "msg-001"
    }
  }
}
```

**成功响应关键字段：**

```json
{
  "result": {
    "contextId": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "status": {
      "state": "completed",
      "message": {
        "parts": [{"kind": "text", "text": "| 账单编号 | ..."}]
      }
    }
  }
}
```

> 记下 `result.contextId`，后续轮次必须带上它才能保持对话上下文。

**实际响应内容（2026-06-27 验证）：**
```
state: completed

| 账单编号   | 文件名                     | 状态             | 总金额  | 结论 |
|------------|---------------------------|-----------------|---------|------|
| upload-001 | CEVA-HKG-TPE-2026-06.pdf  | VALIDATED        | $48,500 | ⚠️   |
| upload-002 | CEVA-HKG-TPE-2026-05.pdf  | PENDING_APPROVAL | $51,200 | ⚠️   |
| upload-003 | KERRY-SHA-TPE-2026-06.pdf | APPROVED         | $32,800 | ✅   |
```

---

#### Round 2 — 问题账单详情（续话）

将 Round 1 响应中的 `result.contextId` 填入 `"contextId"` 字段：

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "哪些账单有问题？详细说明原因"}],
      "messageId": "msg-002",
      "contextId": "（粘贴 Round 1 的 result.contextId）"
    }
  }
}
```

**实际响应内容：**
```
state: completed

upload-002：燃料附加费 5900 USD，超合同 110%（合同价 2809.52）；HANDLING 费未在费率卡中列明。
upload-001：燃料附加费 2950 USD，超合同 5%；汇率轻微偏差（31.5 vs 31.4）。
```

---

#### Round 3 — 费率卡查询（续话）

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "当前有哪些费率卡，列出服务项目和单价"}],
      "messageId": "msg-003",
      "contextId": "（粘贴 Round 2 的 result.contextId，与 Round 1 相同）"
    }
  }
}
```

**实际响应内容：**
```
state: completed

rc-001  CEVA Air Freight HKG-TPE 2026
  AIR-KG    2.75 USD/kg（min 100 kg）
  FUEL-SUR  2809.52 USD/lot

rc-002  Kerry Sea Freight SHA-TPE 2026
  SEA-CBM   680 USD/cbm
  DOCS      200 USD/lot
```

---

### 6.3 验证结论

| 步骤 | 操作 | 预期结果 | 验证通过 |
|------|------|---------|---------|
| Agent Card | 浏览器 GET `/.well-known/agent.json` | 返回包含 `name`/`skills` 的 JSON | ✅ |
| Round 1 | Bruno POST，无 contextId | `state: completed`，返回账单汇总表 | ✅ |
| Round 2 | Bruno POST，带 contextId | `state: completed`，同一 contextId，问题分析 | ✅ |
| Round 3 | Bruno POST，带 contextId | `state: completed`，同一 contextId，费率卡清单 | ✅ |

技术闭环完成：Agent Card 发现 → A2A 首轮调用 → 多轮续话，全部验证通过。

---

## Step 7 — 查看日志

```bash
cf logs byoa-coach-demo --recent
```

实时日志：
```bash
cf logs byoa-coach-demo
```

---

## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `Buildpack not found` | buildpack 名称错误 | 用 `cf buildpacks` 确认名称 |
| `ModuleNotFoundError` | requirements.txt 未生成 | 重新执行 Step 3 |
| `GLM API error 401` | ZHIPU_API_KEY 错误 | `cf set-env byoa-coach-demo ZHIPU_API_KEY <new-key>` 后 `cf restart` |
| App crashed | 内存不足 | `manifest.yml` memory 改为 `512M` |
| `ModuleNotFoundError: No module named 'agent'` | src/ 子目录需相对导入 | executor.py / __main__.py 使用 `from .agent import` 而非 `from agent import` |
| `Env cannot set PORT` | manifest.yml 中手动设置了 PORT | 删掉 env 中的 `PORT` 行，CF 自动注入 |
| Bruno 报 `Extra data: line N column N` | Body JSON 末尾有多余字符 | 检查最后一行是否只有 `}` 结尾，删除多余字符 |

---

## 重新部署（改代码后）

```bash
uv export --format requirements-txt --no-hashes -o requirements.txt
cf push
```

---

## 清理（用完后）

```bash
cf delete byoa-coach-demo -f
```

---

*生成时间：2026-06-27 | 基于 billing-validator BYOA PoC 裁剪*
