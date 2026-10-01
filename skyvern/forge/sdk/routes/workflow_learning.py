"""Authenticated local workflow-learning reports and review-only candidates."""

import asyncio
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool

from skyvern.config import settings
from skyvern.forge import app
from skyvern.forge.sdk.routes.routers import base_router
from skyvern.forge.sdk.schemas.organizations import Organization
from skyvern.forge.sdk.services import org_auth_service
from skyvern.services.workflow_learning import candidate, fingerprint, summarize
from skyvern.services.workflow_learning_capture import capture_run, learning_store


class LearningVerification(BaseModel):
    success: StrictBool
    case: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    benchmark: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


async def _learning_workflow(workflow_id: str, current_org: Organization):
    if not settings.ENABLE_WORKFLOW_LEARNING:
        raise HTTPException(409, "Enable ENABLE_WORKFLOW_LEARNING first")
    workflow = await app.DATABASE.workflows.get_workflow_by_permanent_id(
        workflow_id, organization_id=current_org.organization_id
    )
    if workflow is None:
        raise HTTPException(404, "Workflow not found")
    return workflow


@base_router.get("/workflows/{workflow_id}/learning", tags=["Workflow learning"])
async def workflow_learning_report(
    workflow_id: str, current_org: Annotated[Organization, Depends(org_auth_service.get_current_org)]
) -> dict:
    """Show local evidence and immutable proposals for the authenticated organization."""
    workflow = await _learning_workflow(workflow_id, current_org)
    store = learning_store()
    rows = await asyncio.to_thread(store.rows, current_org.organization_id, workflow_id)
    proposals = await asyncio.to_thread(store.proposals, current_org.organization_id, workflow_id)
    return {
        "current_revision": fingerprint(workflow.workflow_definition.model_dump(mode="json")),
        "revisions": {
            revision: summarize([r for r in rows if r["revision"] == revision])
            for revision in sorted({r["revision"] for r in rows})
        },
        "runs": rows,
        "proposals": proposals,
        "automatic_promotion": False,
    }


@base_router.post("/workflows/{workflow_id}/learning/analyze", tags=["Workflow learning"])
async def analyze_workflow_learning(
    workflow_id: str, current_org: Annotated[Organization, Depends(org_auth_service.get_current_org)]
) -> dict:
    """Backfill the latest 30 runs; future completions are captured automatically."""
    await _learning_workflow(workflow_id, current_org)
    runs = await app.DATABASE.workflow_runs.get_workflow_runs_for_workflow_permanent_id(
        workflow_permanent_id=workflow_id,
        organization_id=current_org.organization_id,
        page_size=30,
        exclude_child_runs=True,
    )
    for run in runs:
        await capture_run(run)
    return await workflow_learning_report(workflow_id, current_org)


@base_router.post("/workflows/{workflow_id}/learning/runs/{run_id}/verify", tags=["Workflow learning"])
async def verify_learning_run(
    workflow_id: str,
    run_id: str,
    request: LearningVerification,
    current_org: Annotated[Organization, Depends(org_auth_service.get_current_org)],
) -> dict:
    """Mark an independently checked outcome, not merely the run's Completed status."""
    await _learning_workflow(workflow_id, current_org)
    try:
        await asyncio.to_thread(
            learning_store().verify,
            current_org.organization_id,
            workflow_id,
            run_id,
            request.success,
            request.case,
            request.benchmark,
        )
    except KeyError as exc:
        raise HTTPException(404, "Run not recorded for this workflow") from exc
    return {"recorded": True, "automatic_promotion": False}


@base_router.get("/workflows/{workflow_id}/learning/proposals/{revision}/candidate", tags=["Workflow learning"])
async def learning_candidate(
    workflow_id: str,
    revision: str,
    current_org: Annotated[Organization, Depends(org_auth_service.get_current_org)],
) -> dict:
    """Export a candidate definition for review; the live workflow stays unchanged."""
    workflow = await _learning_workflow(workflow_id, current_org)
    proposals = await asyncio.to_thread(learning_store().proposals, current_org.organization_id, workflow_id)
    proposal = next((p for p in proposals if p["baseline"] == revision), None)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    try:
        definition = candidate(workflow.workflow_definition.model_dump(mode="json"), proposal)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"workflow_definition": definition, "proposal": proposal, "requires_review": True}


@base_router.get("/workflows/{workflow_id}/learning/compare", tags=["Workflow learning"])
async def compare_learning_versions(
    workflow_id: str,
    baseline: str,
    candidate_revision: str,
    benchmark: str,
    current_org: Annotated[Organization, Depends(org_auth_service.get_current_org)],
) -> dict:
    """Compare independently verified results from matched benchmark cases."""
    await _learning_workflow(workflow_id, current_org)
    try:
        return await asyncio.to_thread(
            learning_store().compare, current_org.organization_id, workflow_id, baseline, candidate_revision, benchmark
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
