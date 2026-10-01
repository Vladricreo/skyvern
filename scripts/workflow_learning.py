"""Inspect local workflow learning via authenticated Skyvern APIs.

Set SKYVERN_API_KEY and optionally SKYVERN_API_BASE_URL (defaults to local API).
"""

import argparse
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def main() -> None:
    """Run a learning API operation without placing credentials in command arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", help="Workflow permanent ID (wpid_...)")
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("report")
    sub.add_parser("analyze")
    export = sub.add_parser("candidate")
    export.add_argument("revision")
    verify = sub.add_parser("verify")
    verify.add_argument("run")
    verify.add_argument("result", choices=["success", "failure"])
    verify.add_argument("--case", required=True, help="Non-sensitive test case ID")
    verify.add_argument("--benchmark", required=True, help="Same dataset/environment cohort for both versions")
    compare = sub.add_parser("compare")
    compare.add_argument("baseline")
    compare.add_argument("candidate_revision")
    compare.add_argument("--benchmark", required=True)
    args = parser.parse_args()
    key = os.environ.get("SKYVERN_API_KEY")
    if not key:
        parser.error("Set SKYVERN_API_KEY in the environment")
    base = os.environ.get("SKYVERN_API_BASE_URL", "http://localhost:8000/v1").rstrip("/")
    path = f"/workflows/{quote(args.workflow, safe='')}/learning"
    body = None
    method = "GET"
    if args.operation == "analyze":
        path += "/analyze"
        method = "POST"
    elif args.operation == "candidate":
        path += f"/proposals/{quote(args.revision, safe='')}/candidate"
    elif args.operation == "verify":
        path += f"/runs/{quote(args.run, safe='')}/verify"
        method = "POST"
        body = json.dumps(
            {"success": args.result == "success", "case": args.case, "benchmark": args.benchmark}
        ).encode()
    elif args.operation == "compare":
        path += "/compare?" + urlencode(
            {"baseline": args.baseline, "candidate_revision": args.candidate_revision, "benchmark": args.benchmark}
        )
    request = Request(
        base + path, data=body, method=method, headers={"x-api-key": key, "Content-Type": "application/json"}
    )
    try:
        with urlopen(request, timeout=330) as response:
            print(json.dumps(json.load(response), indent=2, ensure_ascii=False))
    except HTTPError as exc:
        parser.exit(1, f"API returned HTTP {exc.code}; check workflow ID, enabled flag and authorization.\n")


if __name__ == "__main__":
    main()
