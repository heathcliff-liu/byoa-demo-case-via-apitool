import logging
import os
import sys

import httpx
import uvicorn
from dotenv import load_dotenv

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    MessageSendParams,
    TaskState,
)

from .agent import InvoiceAgent
from .executor import InvoiceAgentExecutor

_TERMINAL = {TaskState.completed, TaskState.canceled, TaskState.failed, TaskState.rejected}

if not os.getenv("VCAP_SERVICES"):
    load_dotenv()


class ContinuationAwareRequestHandler(DefaultRequestHandler):
    """Resets task_id when previous task reached terminal state, enabling multi-turn."""

    async def _setup_message_execution(self, params: MessageSendParams, context=None):
        if params.message.task_id:
            task = await self.task_store.get(params.message.task_id, context)
            if task and task.status.state in _TERMINAL:
                params = params.model_copy(
                    update={"message": params.message.model_copy(update={"task_id": None})}
                )
        return await super()._setup_message_execution(params, context)


def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    logging.info("=== BYOA Coach Demo Agent starting ===")

    try:
        port = int(os.getenv("PORT", "8080"))
        host = "0.0.0.0"

        skill = AgentSkill(
            id="billing_validate",
            name="Billing Validator & Summary",
            description=(
                "Summarise and validate 3PL billing uploads. "
                "Returns totals, status breakdown, validation findings, and risk observations."
            ),
            tags=["billing", "3pl", "validation", "demo"],
        )

        # CF 上取真实 URL；本地开发用 localhost
        if os.getenv("VCAP_APPLICATION"):
            import json
            vcap = json.loads(os.getenv("VCAP_APPLICATION", "{}"))
            uris = vcap.get("application_uris", [])
            agent_url = f"https://{uris[0]}/" if uris else f"http://{host}:{port}/"
        else:
            agent_url = f"http://localhost:{port}/"

        agent_card = AgentCard(
            name="Billing Validator Demo Agent",
            description=(
                "Demo BYOA Agent — summarises 3PL billing data (mock), "
                "validates against rate cards, and answers ad-hoc questions."
            ),
            url=agent_url,
            version="1.0.0",
            default_input_modes=list(InvoiceAgent.SUPPORTED_CONTENT_TYPES),
            default_output_modes=list(InvoiceAgent.SUPPORTED_CONTENT_TYPES),
            capabilities=AgentCapabilities(streaming=True, push_notifications=True),
            skills=[skill],
        )

        httpx_client = httpx.AsyncClient(timeout=60.0)
        push_config_store = InMemoryPushNotificationConfigStore()
        push_sender = BasePushNotificationSender(
            httpx_client=httpx_client,
            config_store=push_config_store,
        )
        request_handler = ContinuationAwareRequestHandler(
            agent_executor=InvoiceAgentExecutor(),
            task_store=InMemoryTaskStore(),
            push_config_store=push_config_store,
            push_sender=push_sender,
        )
        server = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
        app = server.build()
        uvicorn.run(app, host=host, port=port)

    except Exception:
        logging.exception("Startup failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
