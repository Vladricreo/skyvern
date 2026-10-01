"""Local, versioned workflow learning. Suggestions never mutate production workflows."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import statistics
from collections import Counter
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

TERMINAL = {"completed", "failed", "terminated", "timed_out"}
ADVICE = {
    "verify": "Before declaring completion, verify the observable result required by the original goal. A click or page load alone is not evidence of completion. If evidence is missing, report the unmet condition instead of success.",
    "retry": "After an unsuccessful interaction, inspect the current page before retrying. Do not repeat an action that may already have produced a side effect. Retain the original stop conditions and permission limits.",
    "efficient": "Once the original goal and its required checks are satisfied, finish immediately. Avoid revisiting pages or repeating checks whose result is already confirmed and unchanged.",
}


def fingerprint(definition: dict) -> str:
    """Identify exact definitions without persisting prompt contents."""
    return hashlib.sha256(json.dumps(definition, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prompt_blocks(definition: dict) -> dict[str, dict]:
    """Collect actual workflow blocks, including nested loop and branch blocks."""
    found: dict[str, dict] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if (
                isinstance(value.get("label"), str)
                and value.get("block_type")
                and isinstance(value.get("navigation_goal"), str)
            ):
                found[value["label"]] = value
            if value.get("block_type") in {"for_loop", "while_loop"}:
                visit(value.get("loop_blocks", []))
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(definition.get("blocks", []))
    return found


def candidate(definition: dict, proposal: dict) -> dict:
    """Append reviewed advice without removing original instructions or placeholders."""
    if fingerprint(definition) != proposal["baseline"]:
        raise ValueError("Workflow changed since proposal; generate a new proposal")
    result = copy.deepcopy(definition)
    blocks = prompt_blocks(result)
    for patch in proposal["patches"]:
        block = blocks[patch["label"]]
        block["navigation_goal"] += (
            "\n\nExecution guidance (the original goal, constraints, and authorization above take priority):\n"
            + "\n".join(ADVICE[key] for key in patch["advice"])
        )
    return result


def summarize(rows: list[dict]) -> dict:
    """Keep declared completion distinct from independently verified outcome."""
    durations = [r["duration"] for r in rows if r.get("duration") is not None]
    checked = [r for r in rows if r.get("verified") is not None]
    return {
        "runs": len(rows),
        "statuses": dict(Counter(r["status"] for r in rows)),
        "median_seconds": statistics.median(durations) if durations else None,
        "verified_runs": len(checked),
        "verified_success_rate": sum(r["verified"] for r in checked) / len(checked) if checked else None,
        "credits": sum(r.get("credits", 0) for r in rows),
    }


class LearningStore:
    """SQLite evidence and immutable proposals, scoped by organization and workflow."""

    def __init__(self, directory: str):
        self.path = Path(directory) / "learning.sqlite3"

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs (org TEXT, workflow TEXT, run TEXT, revision TEXT, data TEXT, PRIMARY KEY(org, workflow, run))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS proposals (org TEXT, workflow TEXT, revision TEXT, data TEXT, PRIMARY KEY(org, workflow, revision))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS snapshots (org TEXT, workflow TEXT, run TEXT, data TEXT, PRIMARY KEY(org, workflow, run))"
            )
            yield db

    def snapshot(self, org: str, workflow: str, run: str, data: dict | None = None) -> dict | None:
        """Store the definition hash at execution time, including partial-run scope."""
        with self.connection() as db:
            if data is not None:
                db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)", (org, workflow, run, json.dumps(data)))
            row = db.execute(
                "SELECT data FROM snapshots WHERE org=? AND workflow=? AND run=?", (org, workflow, run)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def record(self, org: str, workflow: str, evidence: dict) -> None:
        """Idempotently record a final run; retries refresh telemetry but preserve verification."""
        if evidence["status"] not in TERMINAL:
            return
        with self.connection() as db:
            old = db.execute(
                "SELECT data FROM runs WHERE org=? AND workflow=? AND run=?", (org, workflow, evidence["run"])
            ).fetchone()
            data = dict(evidence)
            if old:
                previous = json.loads(old[0])
                if all(previous.get(key) == value for key, value in data.items()):
                    for key in ("verified", "case", "benchmark"):
                        if key in previous:
                            data[key] = previous[key]
            db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
                (org, workflow, data["run"], data["revision"], json.dumps(data)),
            )

    def rows(self, org: str, workflow: str, revision: str | None = None) -> list[dict]:
        """Read telemetry for one tenant and workflow, optionally one exact definition."""
        with self.connection() as db:
            sql = "SELECT data FROM runs WHERE org=? AND workflow=?"
            args = [org, workflow]
            if revision:
                sql += " AND revision=?"
                args.append(revision)
            return [json.loads(r[0]) for r in db.execute(sql, args)]

    def verify(self, org: str, workflow: str, run: str, success: bool, case: str, benchmark: str) -> None:
        """Record a human/external result check and a comparable test case/cohort."""
        with self.connection() as db:
            row = db.execute(
                "SELECT data FROM runs WHERE org=? AND workflow=? AND run=?", (org, workflow, run)
            ).fetchone()
            if not row:
                raise KeyError("Run not recorded")
            data = json.loads(row[0])
            data.update(verified=success, case=case, benchmark=benchmark)
            db.execute(
                "UPDATE runs SET data=? WHERE org=? AND workflow=? AND run=?", (json.dumps(data), org, workflow, run)
            )

    def propose(self, org: str, workflow: str, definition: dict, minimum: int = 3) -> dict | None:
        """Generate at most one immutable, rule-based proposal per exact baseline."""
        revision = fingerprint(definition)
        rows = [r for r in self.rows(org, workflow, revision) if r.get("eligible")]
        if len(rows) < minimum:
            return None
        patches = []
        for label, block in prompt_blocks(definition).items():
            if "Execution guidance (the original goal" in block["navigation_goal"]:
                continue
            if sum(any(b["label"] == label for b in r.get("blocks", [])) for r in rows) < minimum:
                continue
            observations = [b for r in rows for b in r.get("blocks", []) if b["label"] == label]
            if len(observations) < minimum:
                continue
            failures = sum(b["status"] in {"failed", "terminated", "timed_out"} for b in observations)
            advice = ["verify", "retry"] if failures else ["verify", "efficient"]
            patches.append({"label": label, "advice": advice, "observations": len(observations), "failures": failures})
        if not patches:
            return None
        proposal = {
            "baseline": revision,
            "state": "pending_review",
            "generator": "rules-v1",
            "evidence_run_ids": sorted(r["run"] for r in rows),
            "summary": summarize(rows),
            "patches": patches,
        }
        proposal["candidate"] = fingerprint(candidate(definition, proposal))
        with self.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO proposals VALUES (?,?,?,?)", (org, workflow, revision, json.dumps(proposal))
            )
            return json.loads(
                db.execute(
                    "SELECT data FROM proposals WHERE org=? AND workflow=? AND revision=?", (org, workflow, revision)
                ).fetchone()[0]
            )

    def proposals(self, org: str, workflow: str) -> list[dict]:
        """List saved proposals without exposing another tenant's evidence."""
        with self.connection() as db:
            return [
                json.loads(r[0])
                for r in db.execute("SELECT data FROM proposals WHERE org=? AND workflow=?", (org, workflow))
            ]

    def compare(self, org: str, workflow: str, baseline: str, candidate_revision: str, benchmark: str) -> dict:
        """Compare verified runs of equal test cases; never automatically promote."""
        if baseline == candidate_revision:
            raise ValueError("Baseline and candidate must differ")
        groups = []
        for revision in (baseline, candidate_revision):
            rows = [
                r
                for r in self.rows(org, workflow, revision)
                if r.get("eligible") and r.get("verified") is not None and r.get("benchmark") == benchmark
            ]
            groups.append(rows)
        counts = [Counter((r["case"], r.get("execution_config")) for r in rows) for rows in groups]
        comparable = (
            len(groups[0]) >= 3
            and counts[0] == counts[1]
            and all(r.get("duration") is not None for group in groups for r in group)
        )
        summaries = [summarize(rows) for rows in groups]
        recommendation = "insufficient_comparable_evidence"
        if comparable:
            old, new = summaries
            if new["verified_success_rate"] < old["verified_success_rate"]:
                recommendation = "reject_quality_regression"
            elif (
                new["verified_success_rate"] == 1.0
                and new["median_seconds"] < old["median_seconds"]
                and new["credits"] <= old["credits"]
            ):
                recommendation = "review_candidate_for_promotion"
            else:
                recommendation = "keep_baseline"
        return {
            "baseline": summaries[0],
            "candidate": summaries[1],
            "recommendation": recommendation,
            "automatic_promotion": False,
            "note": "Matched user-declared benchmark cases; not a statistical guarantee. Credits are not provider token costs.",
        }
