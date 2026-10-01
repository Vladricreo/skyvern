"""API and capture integration tests with real FastAPI and isolated repository fakes."""

import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Organization(BaseModel):
    organization_id: str


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.core = load("learning_core", "skyvern/services/workflow_learning.py")
        self.settings = SimpleNamespace(
            ENABLE_WORKFLOW_LEARNING=True,
            WORKFLOW_LEARNING_DIRECTORY=self.directory.name,
            WORKFLOW_LEARNING_MIN_RUNS=3,
            LLM_KEY="test",
            GPT5_REASONING_EFFORT="low",
            GPT6_ASTRA_REASONING_EFFORT="low",
            GPT6_LUNA_REASONING_EFFORT="low",
            ENABLE_JEV_CLICK=False,
        )
        self.definition = {
            "blocks": [
                {"label": "test", "block_type": "task", "navigation_goal": "Preserve {{ secret_ref }}; do not submit."}
            ]
        }
        self.workflow = SimpleNamespace(
            organization_id="org",
            workflow_permanent_id="wpid",
            version=1,
            model=None,
            run_with="agent",
            workflow_definition=SimpleNamespace(model_dump=lambda **kw: self.definition),
        )

        async def find(workflow_id, organization_id):
            return self.workflow if workflow_id == "wpid" and organization_id == "org" else None

        self.app = SimpleNamespace(
            DATABASE=SimpleNamespace(
                workflows=SimpleNamespace(
                    get_workflow_by_permanent_id=AsyncMock(side_effect=find),
                    get_workflow=AsyncMock(return_value=self.workflow),
                ),
                workflow_runs=SimpleNamespace(get_workflow_runs_for_workflow_permanent_id=AsyncMock(return_value=[])),
                observer=SimpleNamespace(
                    get_workflow_run_blocks=AsyncMock(return_value=[SimpleNamespace(label="test", status="completed")])
                ),
            )
        )

        async def auth(x_test_org: str | None = Header(default=None)):
            if x_test_org is None:
                raise HTTPException(401)
            return Organization(organization_id=x_test_org)

        modules = {}
        for name in (
            "skyvern",
            "skyvern.config",
            "skyvern.forge",
            "skyvern.forge.sdk",
            "skyvern.forge.sdk.routes",
            "skyvern.forge.sdk.routes.routers",
            "skyvern.forge.sdk.schemas",
            "skyvern.forge.sdk.schemas.organizations",
            "skyvern.forge.sdk.services",
            "skyvern.services",
        ):
            modules[name] = types.ModuleType(name)
            modules[name].__path__ = []
        modules["skyvern.config"].settings = self.settings
        modules["skyvern.forge"].app = self.app
        modules["skyvern.forge.sdk.routes.routers"].base_router = APIRouter()
        modules["skyvern.forge.sdk.schemas.organizations"].Organization = Organization
        modules["skyvern.forge.sdk.services"].org_auth_service = SimpleNamespace(get_current_org=auth)
        modules["skyvern.services.workflow_learning"] = self.core
        with patch.dict(sys.modules, modules):
            self.capture = load("capture", "skyvern/services/workflow_learning_capture.py")
            with patch.dict(sys.modules, {"skyvern.services.workflow_learning_capture": self.capture}):
                self.routes = load("learning_routes", "skyvern/forge/sdk/routes/workflow_learning.py")
        api = FastAPI()
        api.include_router(modules["skyvern.forge.sdk.routes.routers"].base_router)
        self.client = TestClient(api)
        self.addCleanup(self.client.close)
        self.store = self.capture.learning_store()

    async def test_execution_snapshot_and_capture_keep_original_revision(self):
        now = datetime.now(UTC)
        run = SimpleNamespace(
            workflow_run_id="run",
            workflow_id="wf",
            organization_id="org",
            run_with="agent",
            ai_fallback=True,
            retry_pending=False,
            parent_workflow_run_id=None,
            started_at=now,
            finished_at=now + timedelta(seconds=4),
            status="completed",
            credits_used=1,
        )
        revision = self.core.fingerprint(self.definition)
        await self.capture.snapshot_run(self.workflow, run, partial=False)
        self.definition["blocks"][0]["navigation_goal"] = "Changed while running"
        await self.capture.capture_run(run)
        row = self.store.rows("org", "wpid")[0]
        self.assertEqual(row["revision"], revision)
        self.assertTrue(row["eligible"])
        self.assertEqual(row["duration"], 4)
        self.assertEqual(row["blocks"], [{"label": "test", "status": "completed"}])

    async def test_api_auth_and_tenant_lookup(self):
        self.assertEqual(self.client.get("/workflows/wpid/learning").status_code, 401)
        self.assertEqual(self.client.get("/workflows/wpid/learning", headers={"x-test-org": "other"}).status_code, 404)
        self.assertEqual(self.client.get("/workflows/wpid/learning", headers={"x-test-org": "org"}).status_code, 200)
        self.settings.ENABLE_WORKFLOW_LEARNING = False
        self.assertEqual(self.client.get("/workflows/wpid/learning", headers={"x-test-org": "org"}).status_code, 409)

    async def test_candidate_is_export_only_and_verification_is_strict(self):
        revision = self.core.fingerprint(self.definition)
        for i in range(3):
            self.store.record(
                "org",
                "wpid",
                {
                    "run": str(i),
                    "revision": revision,
                    "eligible": True,
                    "status": "completed",
                    "duration": 4,
                    "credits": 0,
                    "blocks": [{"label": "test", "status": "completed"}],
                },
            )
        self.store.propose("org", "wpid", self.definition)
        response = self.client.get(
            f"/workflows/wpid/learning/proposals/{revision}/candidate", headers={"x-test-org": "org"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["requires_review"])
        self.assertNotIn("Execution guidance", self.definition["blocks"][0]["navigation_goal"])
        result = self.client.post(
            "/workflows/wpid/learning/runs/0/verify",
            headers={"x-test-org": "org"},
            json={"success": "true", "case": "test", "benchmark": "v1"},
        )
        self.assertEqual(result.status_code, 422)
        self.definition["blocks"][0]["navigation_goal"] = "Edited"
        self.assertEqual(
            self.client.get(
                f"/workflows/wpid/learning/proposals/{revision}/candidate", headers={"x-test-org": "org"}
            ).status_code,
            409,
        )


if __name__ == "__main__":
    unittest.main()
