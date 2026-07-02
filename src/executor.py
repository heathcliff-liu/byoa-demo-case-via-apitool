import logging
import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, TextPart, UnsupportedOperationError
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError

from .agent import InvoiceAgent

logger = logging.getLogger(__name__)

_MAX_QUERY_CHARS = 4000


class InvoiceAgentExecutor(AgentExecutor):

    def __init__(self) -> None:
        self._agent = InvoiceAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = context.get_user_input()
        if query and len(query) > _MAX_QUERY_CHARS:
            raise ValueError(f"Query too long ({len(query)} chars).")

        task = context.current_task or await self._create_task(context, event_queue)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        correlation_id = str(uuid.uuid4())[:8]
        logger.info("[%s] execute start session=%s task=%s", correlation_id, task.context_id, task.id)

        try:
            async for item in self._agent.astream(query, task.context_id):
                if item.require_user_input:
                    msg = new_agent_text_message(item.content, task.context_id, task.id)
                    await updater.update_status(TaskState.input_required, msg, final=True)
                    break
                elif item.is_task_complete:
                    msg = new_agent_text_message(item.content, task.context_id, task.id)
                    await updater.update_status(TaskState.completed, msg, final=True)
                    await updater.add_artifact(
                        [Part(root=TextPart(text=item.content))],
                        name="billing_summary",
                    )
                    break
                else:
                    await updater.update_status(TaskState.working)
        except Exception as e:
            logger.exception("[%s] agent execution failed: %s", correlation_id, e)
            msg = new_agent_text_message("An internal error occurred.", task.context_id, task.id)
            await updater.update_status(TaskState.failed, msg, final=True)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise ServerError(error=UnsupportedOperationError())

    async def _create_task(self, context: RequestContext, event_queue: EventQueue):
        if not context.message:
            raise RuntimeError("No message received")
        task = new_task(context.message)
        await event_queue.enqueue_event(task)
        return task
