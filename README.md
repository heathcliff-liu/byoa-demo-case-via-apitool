# byoa-demo-case-via-apitool

A minimal **BYOA (Bring Your Own Agent)** demo deployed on SAP BTP Cloud Foundry.

The agent exposes a 3PL billing validation assistant via the [A2A protocol](https://github.com/google/a2a-sdk), powered by **Zhipu GLM-4-Flash** and hardcoded mock data — no SAP AI Core, no XSUAA, no OData required.

---

## Architecture

```
HTTP Client (curl / Bruno / Joule)
        │  POST /  (A2A JSON-RPC)
        ▼
__main__.py  ── A2AStarletteApplication (uvicorn)
        │
        ▼
executor.py  ── InvoiceAgentExecutor
        │
        ▼
agent.py     ── LangGraph two-node graph
        ├── node "agent"   : System prompt + mock data → GLM-4-Flash
        └── node "respond" : Classify status (completed / input_required / error)
```

**Key dependencies:**
- [`a2a-sdk`](https://github.com/google/a2a-sdk) — A2A HTTP server, compatible with SAP Joule
- `langgraph` + `langchain-openai` — Agent graph, calls Zhipu GLM via OpenAI-compatible API
- `uvicorn` + `fastapi` — ASGI server

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.13 | [python.org](https://www.python.org/downloads/) or `brew install python@3.13` |
| pip | any | bundled with Python |
| CF CLI | v8 | [docs](https://docs.cloudfoundry.org/cf-cli/install-go-cli.html) or `brew install cloudfoundry/tap/cf-cli@8` |
| Zhipu API key | — | [open.bigmodel.cn](https://open.bigmodel.cn/) — GLM-4-Flash is **free tier** |

> `uv` is **not required**. All steps below use plain `pip`. If you prefer `uv`, see [Using uv](#optional-using-uv).

---

## Local Development

### 1. Clone

```bash
git clone https://github.com/heathcliff-liu/byoa-demo-case-via-apitool.git
cd byoa-demo-case-via-apitool
```

### 2. Create virtual environment & install dependencies

```bash
python3.13 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Set environment variables

```bash
export ZHIPU_API_KEY=<your-zhipu-api-key>
export USE_MOCK_DATA=true
```

> On Windows (PowerShell):
> ```powershell
> $env:ZHIPU_API_KEY = "<your-zhipu-api-key>"
> $env:USE_MOCK_DATA = "true"
> ```

### 4. Run

```bash
python -m src
# Agent starts at http://localhost:8080
```

### 5. Verify

```bash
curl http://localhost:8080/.well-known/agent.json
```

Expected response:
```json
{
  "name": "Billing Validator Demo Agent",
  "version": "1.0.0",
  "url": "http://localhost:8080/",
  "capabilities": {"streaming": true, "pushNotifications": true},
  "skills": [{"id": "billing_validate", "name": "Billing Validator & Summary"}]
}
```

---

## Deploy to SAP BTP Cloud Foundry

### 1. Login to CF

```bash
cf login -a <your-cf-api-endpoint> --sso
```

Find your CF API endpoint in **SAP BTP Cockpit → Cloud Foundry → Overview**. Common examples:
- `https://api.cf.us10-001.hana.ondemand.com` (US10 Trial)
- `https://api.cf.eu10.hana.ondemand.com` (EU10)
- `https://api.cf.ap10.hana.ondemand.com` (AP10)

### 2. Fill in your API key

Edit `manifest.yml` and replace `YOUR_ZHIPU_API_KEY`:

```yaml
env:
  ZHIPU_API_KEY: <your-zhipu-api-key>
  USE_MOCK_DATA: "true"
  LOG_LEVEL: INFO
```

> **Security tip:** Avoid committing real keys. Use CF env instead:
> ```bash
> cf set-env byoa-coach-demo ZHIPU_API_KEY <your-key>
> cf restage byoa-coach-demo
> ```

### 3. Push

```bash
cf push
```

CF will automatically:
1. Detect `python_buildpack` from `manifest.yml`
2. Install all packages from `requirements.txt`
3. Start the app with `python -m src` (from `Procfile`)

Expected output:
```
name:              byoa-coach-demo
requested state:   started
routes:            byoa-coach-demo.cfapps.<region>.hana.ondemand.com
```

### 4. Verify on CF

Open in browser:
```
https://byoa-coach-demo.cfapps.<region>.hana.ondemand.com/.well-known/agent.json
```

---

## Testing the Agent (A2A JSON-RPC)

### Round 1 — First message (no contextId)

```bash
curl -X POST https://<app-url>/ \
  -H "Content-Type: application/json" \
  -d '{
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
  }'
```

From the response, copy `result.contextId` — you need it for follow-up turns.

### Round 2 — Follow-up (pass contextId to maintain conversation)

```bash
curl -X POST https://<app-url>/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "哪些账单有问题？详细说明原因"}],
        "messageId": "msg-002",
        "contextId": "<paste-contextId-from-round-1>"
      }
    }
  }'
```

### Round 3 — Rate card query

```bash
curl -X POST https://<app-url>/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "当前有哪些费率卡，列出服务项目和单价"}],
        "messageId": "msg-003",
        "contextId": "<same-contextId>"
      }
    }
  }'
```

> Replace `https://<app-url>/` with `http://localhost:8080/` for local testing.

---

## Mock Data

The agent has 3 pre-loaded billing uploads and 2 rate cards baked into `agent.py`:

| ID | File | Status | Total | Result |
|----|------|--------|-------|--------|
| upload-001 | CEVA-HKG-TPE-2026-06.pdf | VALIDATED | $48,500 | ⚠️ 2 warnings |
| upload-002 | CEVA-HKG-TPE-2026-05.pdf | PENDING_APPROVAL | $51,200 | ⚠️ 1 error + 2 warnings |
| upload-003 | KERRY-SHA-TPE-2026-06.pdf | APPROVED | $32,800 | ✅ Pass |

Rate cards: CEVA Air Freight HKG-TPE 2026, Kerry Sea Freight SHA-TPE 2026.

---

## File Structure

```
byoa-demo-case-via-apitool/
├── src/
│   ├── __init__.py
│   ├── agent.py         # LangGraph agent + mock data + system prompt
│   ├── executor.py      # A2A AgentExecutor
│   └── __main__.py      # A2A server startup + AgentCard definition
├── manifest.yml         # CF deployment config (set ZHIPU_API_KEY here)
├── Procfile             # CF start command: python -m src
├── pyproject.toml       # Project metadata + direct dependencies
├── requirements.txt     # Pinned full dependency tree (pip-installable)
├── runtime.txt          # python-3.13.x (for CF buildpack)
└── .gitignore
```

---

## Optional: Using uv

If you prefer [uv](https://github.com/astral-sh/uv) over plain pip:

```bash
pip install uv
uv venv && source .venv/bin/activate
uv sync                  # installs from pyproject.toml
```

To regenerate `requirements.txt` after changing `pyproject.toml`:
```bash
uv export --format requirements-txt --no-hashes -o requirements.txt
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `ZHIPU_API_KEY is not set` | Env var missing | Set `ZHIPU_API_KEY` before running |
| `GLM API error 401` | Wrong or expired key | Re-check key at [open.bigmodel.cn](https://open.bigmodel.cn/) |
| `ModuleNotFoundError` | venv not activated or deps not installed | `source .venv/bin/activate && pip install -r requirements.txt` |
| CF: `Buildpack not found` | Wrong buildpack name | Run `cf buildpacks` to verify the exact name |
| CF: `Env cannot set PORT` | PORT set in manifest.yml | Remove `PORT` from env — CF injects it automatically |
| CF: App crashes (out of memory) | Default memory too low | Set `memory: 512M` in manifest.yml |
| `Extra data` JSON error (Bruno) | Trailing characters in request body | Ensure the body ends with exactly `}` |
| Multi-turn not working | Missing `contextId` in follow-up | Copy `result.contextId` from Round 1 response |
