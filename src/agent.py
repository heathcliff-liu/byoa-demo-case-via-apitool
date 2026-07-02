"""BYOA Coach Demo Agent — GLM-4-Flash + Mock Data.

简化版 BYOA Agent，沿用 billing-validator-agent 的 LangGraph 框架，
去掉 SAP AI Core / XSUAA / OData，换成智谱 GLM-4-Flash + 硬编码 mock 数据。
"""

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, AsyncIterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, get_buffer_string, trim_messages
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph, add_messages
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "true").lower() in {"1", "true", "yes"}


# ── Mock 数据 ──────────────────────────────────────────────────────────────────

MOCK_BILLING_UPLOADS: list[dict[str, Any]] = [
    {
        "ID": "upload-001",
        "fileName": "CEVA-HKG-TPE-2026-06.pdf",
        "status": "VALIDATED",
        "approvalStatus": "pending",
        "createdAt": "2026-06-20T10:12:00Z",
        "rateCard_ID": "rc-001",
        "header": {
            "vendorName": "CEVA Freight (Taiwan)",
            "vendorId": "V-CEVA-TW",
            "invoiceNumber": "INV-2026-0620",
            "invoiceDate": "2026-06-20",
            "dueDate": "2026-07-20",
            "contractNumber": "CT-2026-001",
            "costCenter": "CC-1001",
            "totalAmount": 48500.00,
            "taxAmount": 2425.00,
            "currency": "USD",
            "isConfirmed": False,
            "lineItems": [
                {
                    "lineNumber": 1,
                    "serviceCode": "AIR-KG",
                    "description": "Air freight HKG-TPE per kg",
                    "quantity": 1200.0,
                    "unit": "kg",
                    "unitPrice": 2.75,
                    "exchangeRate": 31.5,
                    "lineAmount": 103950.0,
                    "currency": "TWD",
                    "confidenceScore": 0.96,
                },
                {
                    "lineNumber": 2,
                    "serviceCode": "FUEL-SUR",
                    "description": "Fuel surcharge",
                    "quantity": 1.0,
                    "unit": "lot",
                    "unitPrice": 2950.0,
                    "exchangeRate": 31.5,
                    "lineAmount": 92925.0,
                    "currency": "TWD",
                    "confidenceScore": 0.91,
                },
            ],
        },
        "validationResult": {
            "upload_ID": "upload-001",
            "overallStatus": "warning",
            "totalBilled": 48500.00,
            "totalExpected": 46200.00,
            "totalVariance": 2300.00,
            "findingCount": 2,
            "errorCount": 0,
            "warningCount": 2,
            "summary": "2 warnings: fuel surcharge exceeds rate card by 5%; exchange rate deviation 0.3%.",
            "findings": [
                {
                    "type": "RATE_DEVIATION",
                    "severity": "warning",
                    "field": "FUEL-SUR unitPrice",
                    "billedValue": 2950.00,
                    "expectedValue": 2809.52,
                    "variance": 140.48,
                    "variancePct": 5.00,
                    "explanation": "Fuel surcharge unit price 5% above contracted rate card.",
                    "aiReasoning": "Rate card item FUEL-SUR specifies max unitPrice 2809.52 USD. Billed 2950.00 USD exceeds by 5%.",
                },
                {
                    "type": "FX_DEVIATION",
                    "severity": "warning",
                    "field": "exchangeRate",
                    "billedValue": 31.5,
                    "expectedValue": 31.4,
                    "variance": 0.1,
                    "variancePct": 0.32,
                    "explanation": "Exchange rate slightly above reference rate.",
                    "aiReasoning": "TWD/USD reference rate 31.4; billed 31.5 — within tolerance but flagged.",
                },
            ],
        },
    },
    {
        "ID": "upload-002",
        "fileName": "CEVA-HKG-TPE-2026-05.pdf",
        "status": "PENDING_APPROVAL",
        "approvalStatus": "pending",
        "createdAt": "2026-06-18T08:45:00Z",
        "rateCard_ID": "rc-001",
        "header": {
            "vendorName": "CEVA Freight (Taiwan)",
            "vendorId": "V-CEVA-TW",
            "invoiceNumber": "INV-2026-0518",
            "invoiceDate": "2026-05-18",
            "dueDate": "2026-06-18",
            "contractNumber": "CT-2026-001",
            "costCenter": "CC-1001",
            "totalAmount": 51200.00,
            "taxAmount": 2560.00,
            "currency": "USD",
            "isConfirmed": False,
            "lineItems": [
                {
                    "lineNumber": 1,
                    "serviceCode": "AIR-KG",
                    "description": "Air freight HKG-TPE per kg",
                    "quantity": 1450.0,
                    "unit": "kg",
                    "unitPrice": 2.75,
                    "exchangeRate": 31.4,
                    "lineAmount": 125307.5,
                    "currency": "TWD",
                    "confidenceScore": 0.98,
                },
                {
                    "lineNumber": 2,
                    "serviceCode": "FUEL-SUR",
                    "description": "Fuel surcharge",
                    "quantity": 1.0,
                    "unit": "lot",
                    "unitPrice": 5900.00,
                    "exchangeRate": 31.4,
                    "lineAmount": 185260.0,
                    "currency": "TWD",
                    "confidenceScore": 0.87,
                },
                {
                    "lineNumber": 3,
                    "serviceCode": "HANDLING",
                    "description": "Ground handling fee",
                    "quantity": 1.0,
                    "unit": "lot",
                    "unitPrice": 800.00,
                    "exchangeRate": 31.4,
                    "lineAmount": 25120.0,
                    "currency": "TWD",
                    "confidenceScore": 0.93,
                },
            ],
        },
        "validationResult": {
            "upload_ID": "upload-002",
            "overallStatus": "error",
            "totalBilled": 51200.00,
            "totalExpected": 44100.00,
            "totalVariance": 7100.00,
            "findingCount": 3,
            "errorCount": 1,
            "warningCount": 2,
            "summary": "1 error: fuel surcharge 110% above rate card — requires manual review before approval.",
            "findings": [
                {
                    "type": "RATE_DEVIATION",
                    "severity": "error",
                    "field": "FUEL-SUR unitPrice",
                    "billedValue": 5900.00,
                    "expectedValue": 2809.52,
                    "variance": 3090.48,
                    "variancePct": 110.0,
                    "explanation": "Fuel surcharge more than double the contracted rate — possible billing error.",
                    "aiReasoning": "Rate card FUEL-SUR max 2809.52 USD. Billed 5900 USD is 110% over. Likely data entry error or wrong rate period applied.",
                },
                {
                    "type": "UNLISTED_SERVICE",
                    "severity": "warning",
                    "field": "serviceCode",
                    "billedValue": 800.00,
                    "expectedValue": 0,
                    "variance": 800.00,
                    "variancePct": 100.0,
                    "explanation": "HANDLING fee not present in active rate card CT-2026-001.",
                    "aiReasoning": "No matching serviceCode HANDLING in rate card rc-001. Needs contract amendment or rejection.",
                },
                {
                    "type": "FX_DEVIATION",
                    "severity": "warning",
                    "field": "exchangeRate",
                    "billedValue": 31.4,
                    "expectedValue": 31.4,
                    "variance": 0.0,
                    "variancePct": 0.0,
                    "explanation": "Exchange rate matches reference rate.",
                    "aiReasoning": "No deviation.",
                },
            ],
        },
    },
    {
        "ID": "upload-003",
        "fileName": "KERRY-SHA-TPE-2026-06.pdf",
        "status": "APPROVED",
        "approvalStatus": "approved",
        "createdAt": "2026-06-15T14:30:00Z",
        "rateCard_ID": "rc-002",
        "header": {
            "vendorName": "Kerry Logistics (Shanghai)",
            "vendorId": "V-KERRY-SH",
            "invoiceNumber": "KL-2026-0615",
            "invoiceDate": "2026-06-15",
            "dueDate": "2026-07-15",
            "contractNumber": "CT-2026-002",
            "costCenter": "CC-1002",
            "totalAmount": 32800.00,
            "taxAmount": 0.00,
            "currency": "USD",
            "isConfirmed": True,
            "lineItems": [
                {
                    "lineNumber": 1,
                    "serviceCode": "SEA-CBM",
                    "description": "Sea freight SHA-TPE per CBM",
                    "quantity": 45.0,
                    "unit": "cbm",
                    "unitPrice": 680.00,
                    "exchangeRate": 31.4,
                    "lineAmount": 960120.0,
                    "currency": "TWD",
                    "confidenceScore": 0.99,
                },
                {
                    "lineNumber": 2,
                    "serviceCode": "DOCS",
                    "description": "Documentation fee",
                    "quantity": 1.0,
                    "unit": "lot",
                    "unitPrice": 200.00,
                    "exchangeRate": 31.4,
                    "lineAmount": 6280.0,
                    "currency": "TWD",
                    "confidenceScore": 0.97,
                },
            ],
        },
        "validationResult": {
            "upload_ID": "upload-003",
            "overallStatus": "pass",
            "totalBilled": 32800.00,
            "totalExpected": 32800.00,
            "totalVariance": 0.00,
            "findingCount": 0,
            "errorCount": 0,
            "warningCount": 0,
            "summary": "All line items match rate card. No findings.",
            "findings": [],
        },
    },
]

MOCK_RATE_CARDS: list[dict[str, Any]] = [
    {
        "name": "CEVA Air Freight HKG-TPE 2026",
        "status": "active",
        "validFrom": "2026-01-01",
        "validTo": "2026-12-31",
        "description": "Annual air freight contract CEVA Freight Taiwan — HKG to TPE route.",
        "items": [
            {
                "serviceCode": "AIR-KG",
                "serviceDesc": "Air freight per kg",
                "unit": "kg",
                "unitPrice": 2.75,
                "currency": "USD",
                "minQty": 100,
                "maxQty": None,
                "notes": "Min 100 kg per shipment.",
            },
            {
                "serviceCode": "FUEL-SUR",
                "serviceDesc": "Fuel surcharge (per lot)",
                "unit": "lot",
                "unitPrice": 2809.52,
                "currency": "USD",
                "minQty": 1,
                "maxQty": 1,
                "notes": "Fixed per-shipment surcharge; reviewed quarterly.",
            },
        ],
    },
    {
        "name": "Kerry Sea Freight SHA-TPE 2026",
        "status": "active",
        "validFrom": "2026-01-01",
        "validTo": "2026-12-31",
        "description": "Annual sea freight contract Kerry Logistics — SHA to TPE route.",
        "items": [
            {
                "serviceCode": "SEA-CBM",
                "serviceDesc": "Sea freight per CBM",
                "unit": "cbm",
                "unitPrice": 680.00,
                "currency": "USD",
                "minQty": 1,
                "maxQty": None,
                "notes": None,
            },
            {
                "serviceCode": "DOCS",
                "serviceDesc": "Documentation fee",
                "unit": "lot",
                "unitPrice": 200.00,
                "currency": "USD",
                "minQty": 1,
                "maxQty": 1,
                "notes": "Per Bill of Lading.",
            },
        ],
    },
]


# ── System Prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    uploads_block = f"## Billing Uploads\n```json\n{json.dumps(MOCK_BILLING_UPLOADS, indent=2, ensure_ascii=False, default=str)}\n```"
    ratecards_block = f"## Rate Cards\n```json\n{json.dumps(MOCK_RATE_CARDS, indent=2, ensure_ascii=False, default=str)}\n```"
    return f"""你是一个 3PL 账单校验助手（Billing Validator Assistant）。
你的任务是基于以下 Mock 数据回答用户关于账单上传、校验结果和费率卡的问题。

{uploads_block}

{ratecards_block}

## 回答规则
- 用结构化的 Markdown 表格或列表呈现汇总信息
- 有错误的账单用 ⚠️ 标注，待审批的用 ⏳ 标注，已通过的用 ✅ 标注
- 不要编造数据之外的内容
- 回答简洁，直接给结论
- 语言跟随用户（中文问题 → 中文回答）
"""


# ── Agent 类型 ────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    COMPLETED = "completed"
    INPUT_REQUIRED = "input_required"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class StreamResponse:
    is_task_complete: bool
    require_user_input: bool
    content: str

    @classmethod
    def completed(cls, msg: str) -> "StreamResponse":
        return cls(True, False, msg)

    @classmethod
    def input_required(cls, msg: str) -> "StreamResponse":
        return cls(False, True, msg)

    @classmethod
    def error(cls, msg: str = "Unable to process request.") -> "StreamResponse":
        return cls(False, True, msg)

    @classmethod
    def working(cls, msg: str = "Processing...") -> "StreamResponse":
        return cls(False, False, msg)


class ResponseFormat(BaseModel):
    status: TaskStatus = TaskStatus.COMPLETED
    message: str


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    structured_response: ResponseFormat | None


# ── Agent ─────────────────────────────────────────────────────────────────────

class InvoiceAgent:

    SUPPORTED_CONTENT_TYPES = frozenset({"TEXT", "TEXT/PLAIN"})

    def __init__(self) -> None:
        api_key = os.getenv("ZHIPU_API_KEY", "")
        if not api_key:
            raise RuntimeError("ZHIPU_API_KEY is not set")
        self._model = ChatOpenAI(
            model="glm-4-flash",
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            max_tokens=4096,
        )
        self._checkpointer = MemorySaver()
        self._graph: CompiledStateGraph | None = None
        self._build_graph()

    def _build_graph(self) -> None:
        model = self._model

        async def agent_node(state: AgentState) -> dict:
            messages = trim_messages(
                state["messages"],
                max_tokens=16_000,
                token_counter=lambda msgs: len(get_buffer_string(msgs)) // 4,
                strategy="last",
                start_on="human",
                include_system=False,
                allow_partial=False,
            )
            response = await model.ainvoke([
                SystemMessage(content=_build_system_prompt()),
                *messages,
            ])
            return {"messages": [response], "structured_response": None}

        async def response_node(state: AgentState) -> dict:
            last_content = ""
            for msg in reversed(state["messages"]):
                if msg.type == "ai" and msg.content:
                    raw = msg.content
                    last_content = raw if isinstance(raw, str) else str(raw)
                    break

            # Infer status from content: if AI ends with a question, it needs more input
            input_required_signals = ["？", "?", "请提供", "请告诉", "能否告知", "需要您"]
            status = TaskStatus.INPUT_REQUIRED if any(
                s in last_content for s in input_required_signals
            ) else TaskStatus.COMPLETED

            result = ResponseFormat(status=status, message=last_content or "Unable to process.")
            return {"structured_response": result}

        graph = StateGraph(AgentState)
        graph.add_node("agent", agent_node)
        graph.add_node("respond", response_node)
        graph.set_entry_point("agent")
        graph.add_edge("agent", "respond")
        graph.add_edge("respond", END)
        self._graph = graph.compile(checkpointer=self._checkpointer)

    async def astream(self, query: str, session_id: str) -> AsyncIterator[StreamResponse]:
        inputs = {"messages": [("user", query)]}
        config = {"configurable": {"thread_id": session_id}, "recursion_limit": 10}

        async for chunk in self._graph.astream(inputs, config, stream_mode="updates"):
            for node_name in chunk:
                if node_name == "agent":
                    yield StreamResponse.working("Processing billing data...")

        state = self._graph.get_state(config)
        response = state.values.get("structured_response")

        if not isinstance(response, ResponseFormat):
            yield StreamResponse.error()
            return

        match response.status:
            case TaskStatus.COMPLETED:
                yield StreamResponse.completed(response.message)
            case TaskStatus.INPUT_REQUIRED:
                yield StreamResponse.input_required(response.message)
            case _:
                yield StreamResponse.error(response.message)
