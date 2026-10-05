"""Standalone transport tests: python -m unittest discover -s tests/jev."""

import asyncio
import importlib.util
import math
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

spec = importlib.util.spec_from_file_location(
    "jev_click", Path(__file__).resolve().parents[2] / "skyvern/forge/sdk/api/llm/jev_click.py"
)
jev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jev)
RealClient = httpx.AsyncClient


class JevClickTests(unittest.IsolatedAsyncioTestCase):
    def args(self):
        return {
            "url": "https://example.com/?private=value",
            "intention": "Click Help",
            "api_key": "test-key",
            "enabled": True,
            "allowed_hosts": ["example.com"],
            "elements": {
                "help": {
                    "tagName": "a",
                    "text": "Help",
                    "interactable": True,
                    "attributes": {"href": "https://example.com/secret", "value": "secret"},
                }
            },
        }

    async def invoke(self, handler, **overrides):
        args = self.args() | overrides
        with patch.object(
            jev.httpx, "AsyncClient", side_effect=lambda **kw: RealClient(transport=httpx.MockTransport(handler), **kw)
        ):
            return await jev.choose_click(**args)

    def response(self, confidence=0.98, choice="target_0"):
        return httpx.Response(
            200, json={"answers": {"target": {"type": "choice", "choice": choice, "confidence": confidence}}}
        )

    async def test_success_and_minimal_payload(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://api.typesafe.ai/v1/systemone")
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            self.assertNotIn(b"private", request.content)
            self.assertNotIn(b"secret", request.content)
            return self.response()

        result = await self.invoke(handler)
        self.assertEqual(result["actions"][0]["id"], "help")

    async def test_disabled_missing_key_and_host_never_call(self):
        def forbidden(request):
            self.fail("Unexpected provider call")

        for change in (
            {"enabled": False},
            {"api_key": None},
            {"url": "https://example.com.evil.test"},
        ):
            self.assertIsNone(await self.invoke(forbidden, **change))

    async def test_optional_host_list_allows_any_host(self):
        for hosts in (None, []):
            with self.subTest(hosts=hosts):
                result = await self.invoke(
                    lambda request: self.response(),
                    allowed_hosts=hosts,
                    url="https://another.example/path",
                )
                self.assertEqual(result["actions"][0]["id"], "help")

    async def test_omitted_host_argument_allows_any_host(self):
        args = self.args()
        args.pop("allowed_hosts")
        args["url"] = "https://another.example/path"
        with patch.object(
            jev.httpx, "AsyncClient",
            side_effect=lambda **kw: RealClient(
                transport=httpx.MockTransport(lambda request: self.response()), **kw
            ),
        ):
            result = await jev.choose_click(**args)
        self.assertEqual(result["actions"][0]["id"], "help")

    async def test_uncertain_invalid_and_abstain_fall_back(self):
        for value in (0.2, True, "0.99", float("nan"), 1.1):
            # NaN cannot be JSON encoded by httpx; return the raw provider body.
            response = (
                self.response(value)
                if not (isinstance(value, float) and math.isnan(value))
                else httpx.Response(
                    200, text='{"answers":{"target":{"type":"choice","choice":"target_0","confidence":NaN}}}'
                )
            )
            self.assertIsNone(await self.invoke(lambda request, response=response: response))
        for choice in ("fallback", "invented-id"):
            self.assertIsNone(await self.invoke(lambda request, choice=choice: self.response(choice=choice)))

    async def test_http_and_malformed_fall_back(self):
        for response in (
            httpx.Response(401),
            httpx.Response(429),
            httpx.Response(500),
            httpx.Response(200, json={}),
            httpx.Response(200, text="invalid"),
        ):
            self.assertIsNone(await self.invoke(lambda request, response=response: response))

    async def test_timeout_is_bounded(self):
        async def slow(request):
            await asyncio.sleep(1)
            return self.response()

        self.assertIsNone(await self.invoke(slow, timeout=0.01))

    async def test_toggles_disabled_and_downloads_are_excluded(self):
        for attrs in ({"aria-pressed": "false"}, {"disabled": ""}, {"download": "file"}, {"role": "checkbox"}):
            elements = {"x": {"tagName": "button", "text": "Help", "interactable": True, "attributes": attrs}}
            self.assertIsNone(await self.invoke(lambda request: self.fail("Unexpected call"), elements=elements))

    async def test_cancellation_propagates(self):
        async def cancelled(request):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await self.invoke(cancelled)


if __name__ == "__main__":
    unittest.main()
