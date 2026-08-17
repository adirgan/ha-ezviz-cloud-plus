"""Tests for durable repository agent instructions."""

from pathlib import Path


def test_agent_instructions_capture_coordinator_invariants() -> None:
    """Keep transient-state rules in the canonical agent instructions."""
    instructions = Path("AGENTS.md").read_text()

    assert "coordinator.ezviz_client" in instructions
    assert "two failures or 75 seconds" in instructions
    assert "two equal complete snapshots" in instructions
    assert "must not issue another cloud request" in instructions


def test_agent_entry_point_links_transient_regression() -> None:
    """Keep the derived entry point short and linked to canonical context."""
    entry_point = Path("AGENT.md").read_text()

    assert "AGENTS.md" in entry_point
    assert "docs/ARCHITECTURE.md" in entry_point
    assert "test_coordinator_transient.py" in entry_point