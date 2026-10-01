"""Bridge final Skyvern runs to local learning with bounded best-effort collection."""

import asyncio
import logging

from skyvern.config import settings
from skyvern.forge import app
from skyvern.services.workflow_learning import LearningStore, fingerprint

LOG = logging.getLogger(__name__)


def learning_store() -> LearningStore:
    """Return the persistent local learning store."""
    return LearningStore(settings.WORKFLOW_LEARNING_DIRECTORY)


async def snapshot_run(workflow, workflow_run, partial: bool) -> None:
    """Record the actual execution definition before edits or a partial Studio run."""
    if not settings.ENABLE_WORKFLOW_LEARNING:
        return
    try:
        config = {
            "model": workflow.model,
            "llm": settings.LLM_KEY,
            "gpt5_effort": settings.GPT5_REASONING_EFFORT,
            "astra_effort": settings.GPT6_ASTRA_REASONING_EFFORT,
            "luna_effort": settings.GPT6_LUNA_REASONING_EFFORT,
            "run_with": workflow_run.run_with or workflow.run_with,
            "ai_fallback": workflow_run.ai_fallback,
            "jev": settings.ENABLE_JEV_CLICK,
        }
        data = {
            "revision": fingerprint(workflow.workflow_definition.model_dump(mode="json")),
            "eligible": not partial,
            "execution_config": fingerprint(config),
        }
        await asyncio.to_thread(
            learning_store().snapshot,
            workflow.organization_id,
            workflow.workflow_permanent_id,
            workflow_run.workflow_run_id,
            data,
        )
    except Exception as exc:  # noqa: BLE001 - optional telemetry must not fail execution
        LOG.warning("workflow_learning_snapshot_failed error_type=%s", type(exc).__name__)


async def capture_run(workflow_run) -> None:
    """Save bounded non-secret telemetry; errors cannot fail the completed workflow."""
    if not settings.ENABLE_WORKFLOW_LEARNING or workflow_run.retry_pending or workflow_run.parent_workflow_run_id:
        return
    try:
        async with asyncio.timeout(10):
            workflow = await app.DATABASE.workflows.get_workflow(
                workflow_run.workflow_id, organization_id=workflow_run.organization_id
            )
            if not workflow:
                return
            blocks = await app.DATABASE.observer.get_workflow_run_blocks(
                workflow_run_id=workflow_run.workflow_run_id,
                organization_id=workflow_run.organization_id,
            )
            definition = workflow.workflow_definition.model_dump(mode="json")
            duration = None
            if workflow_run.started_at and workflow_run.finished_at:
                duration = max(0, (workflow_run.finished_at - workflow_run.started_at).total_seconds())
            store = learning_store()
            snapshot = await asyncio.to_thread(
                store.snapshot, workflow.organization_id, workflow.workflow_permanent_id, workflow_run.workflow_run_id
            )
            evidence = {
                "run": workflow_run.workflow_run_id,
                "revision": snapshot["revision"] if snapshot else fingerprint(definition),
                "eligible": bool(snapshot and snapshot["eligible"]),
                "execution_config": snapshot.get("execution_config") if snapshot else None,
                "workflow_version": workflow.version,
                "status": str(workflow_run.status),
                "duration": duration,
                "credits": workflow_run.credits_used,
                "blocks": [{"label": b.label, "status": str(b.status)} for b in blocks if b.label],
            }
            await asyncio.to_thread(store.record, workflow.organization_id, workflow.workflow_permanent_id, evidence)
            await asyncio.to_thread(
                store.propose,
                workflow.organization_id,
                workflow.workflow_permanent_id,
                definition,
                settings.WORKFLOW_LEARNING_MIN_RUNS,
            )
    except Exception as exc:  # noqa: BLE001 - optional telemetry must not fail execution
        # Do not log run payloads, failure reasons, prompts, or database content.
        LOG.warning("workflow_learning_capture_failed error_type=%s", type(exc).__name__)
