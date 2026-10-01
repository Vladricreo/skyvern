"""Offline build check for the Copilot SDK usage contract (no API calls)."""

from dataclasses import asdict
from importlib.metadata import version

from agents.usage import InputTokensDetails, OutputTokensDetails, Usage, deserialize_usage


def check_usage_contract() -> None:
    """Exercise creation, accumulation and persisted usage deserialization."""
    total = Usage()
    sample = Usage(
        requests=1,
        input_tokens=10,
        output_tokens=2,
        total_tokens=12,
        input_tokens_details=InputTokensDetails(cached_tokens=3),
        output_tokens_details=OutputTokensDetails(reasoning_tokens=1),
    )
    total.add(sample)
    total.add(sample)
    restored = deserialize_usage(asdict(total))
    assert restored.total_tokens == 24
    assert restored.input_tokens_details.cached_tokens == 6
    assert restored.output_tokens_details.reasoning_tokens == 2
    assert len(restored.request_usage_entries) == 2
    assert deserialize_usage({}).total_tokens == 0


if __name__ == "__main__":
    check_usage_contract()
    print(f"Copilot SDK usage OK: agents={version('openai-agents')}, openai={version('openai')}")
