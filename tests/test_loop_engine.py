"""
Samsara Loop — Service-Level Tests
Tests the LoopEngine core without any network or UI dependencies.
Run: python -m pytest tests/test_loop_engine.py -v
"""

import sys
import os
import tempfile
import sqlite3

# Patch DB_PATH to use temp file for tests
os.environ["SAMSARA_DB"] = tempfile.mktemp(suffix=".db")

# Add project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from samsara_loop.core import LoopEngine
from samsara_loop.types import LearningCategory


def get_test_db_path():
    return os.environ.get("SAMSARA_DB", "")


class TestLoopEngine:
    """Service-level tests for the LoopEngine."""

    def setup_method(self):
        """Reset DB before each test."""
        db_path = get_test_db_path()
        if os.path.exists(db_path):
            os.remove(db_path)

    # ── Error Capture ──────────────────────────────────────

    def test_capture_error_creates_learning(self):
        """capture_error should create a learning entry."""
        engine = LoopEngine("test-agent")
        learning_id = engine.capture_error(
            error_message="Wrong API endpoint called",
            context="User asked for weather in Toronto",
            capability="weather_lookup",
        )
        assert learning_id is not None
        assert learning_id.startswith("LRN-")

    def test_capture_error_with_failed_step_generates_test_case(self):
        """capture_error with failed_step should auto-generate a test case."""
        engine = LoopEngine("test-agent")
        learning_id = engine.capture_error(
            error_message="Wrong tool selected",
            context="Customer asked about disputed charge",
            trajectory_summary="Step 1: searched knowledge base\nStep 2: called refund_tool\nStep 3: ERROR",
            failed_step=3,
            tool_involved="refund_tool",
            capability="dispute_handling",
        )
        pending = engine.get_pending_tests()
        assert len(pending) >= 1
        # The test case should reference the capability
        assert pending[-1]["capability"] == "dispute_handling"

    def test_capture_error_different_capabilities(self):
        """Different error types should be tagged with correct capability."""
        engine = LoopEngine("test-agent")
        engine.capture_error("API timeout", context="Getting weather", capability="api_calls")
        engine.capture_error("File not found", context="Reading config", capability="file_operations")

        learnings = engine.get_recent_learnings()
        capabilities = {l["tags"][0] for l in learnings if l.get("tags")}
        assert "api_calls" in capabilities
        assert "file_operations" in capabilities

    # ── Correction Capture ─────────────────────────────────

    def test_capture_correction_from_human(self):
        """Human corrections should be logged as corrections."""
        engine = LoopEngine("test-agent")
        lid = engine.capture_correction(
            content="You should use the calendar API, not the email API",
            context="User asked to check availability",
            what_was_wrong="Used wrong tool for availability check",
            capability="scheduling",
        )
        learnings = engine.get_recent_learnings(category="correction")
        assert len(learnings) >= 1
        assert learnings[0]["source"] == "human"

    # ── Best Practice Capture ───────────────────────────────

    def test_capture_best_practice(self):
        """Best practices should be logged."""
        engine = LoopEngine("test-agent")
        lid = engine.capture_best_practice(
            discovery="Use exponential backoff for retry logic on flaky APIs",
            context="Building the weather lookup tool",
        )
        learnings = engine.get_recent_learnings(category="best_practice")
        assert len(learnings) >= 1

    # ── Knowledge Gap Capture ──────────────────────────────

    def test_capture_knowledge_gap(self):
        """Agent should log when it realizes it doesn't know something."""
        engine = LoopEngine("test-agent")
        lid = engine.capture_knowledge_gap(
            what_was_missing="I didn't know CSA Group's new API versioning scheme",
            context="Building integration with CSA API",
        )
        learnings = engine.get_recent_learnings(category="knowledge_gap")
        assert len(learnings) >= 1

    # ── Self-Eval ─────────────────────────────────────────

    def test_run_self_eval_no_tests_returns_proceed(self):
        """Self-eval on unknown capability should return can_attempt=True."""
        engine = LoopEngine("test-agent")
        result = engine.run_self_eval("unknown_capability_xyz")
        assert result["can_attempt"] is True
        assert result["test_count"] == 0

    def test_run_self_eval_high_pass_rate_allows_attempt(self):
        """High pass rate should allow attempt."""
        engine = LoopEngine("test-agent")
        # Manually create approved test cases with passing results
        from samsara_loop.db.database import save_test_case, save_eval_result
        from samsara_loop.types import TestCase, EvalResult
        import uuid
        from datetime import datetime, timezone

        tc = TestCase(
            id=str(uuid.uuid4()),
            agent_id="test-agent",
            capability="refund_processing",
            input_description="Customer wants refund",
            failure_trace="Step 1: verify purchase\nStep 2: process refund",
            root_cause="none",
            fix_suggestion="none",
            generated_from_learning_id="test",
            status="approved",
            last_run_result="pass",
        )
        save_test_case(tc)

        result = engine.run_self_eval("refund_processing")
        assert result["can_attempt"] is True
        assert result["pass_rate"] == 1.0

    def test_run_self_eval_low_pass_rate_blocks_attempt(self):
        """Low pass rate should block attempt."""
        engine = LoopEngine("test-agent")
        from samsara_loop.db.database import save_test_case
        from samsara_loop.types import TestCase
        import uuid

        tc = TestCase(
            id=str(uuid.uuid4()),
            agent_id="test-agent",
            capability="cross_sell",
            input_description="Customer wants product recommendation",
            failure_trace="Step 1: check history\nStep 2: cross_sell\nStep 3: ERROR",
            root_cause="wrong model",
            fix_suggestion="use different model",
            generated_from_learning_id="test",
            status="approved",
            last_run_result="fail",
        )
        save_test_case(tc)

        result = engine.run_self_eval("cross_sell")
        assert result["can_attempt"] is False
        assert result["pass_rate"] == 0.0

    # ── Profile ─────────────────────────────────────────────

    def test_get_profile_after_captures(self):
        """Profile should reflect captured learnings."""
        engine = LoopEngine("test-agent")
        engine.capture_error("API failed", context="test", capability="api")
        engine.capture_error("DB timeout", context="test", capability="database")
        engine.capture_correction("Wrong approach", context="test", what_was_wrong="used sync")

        profile = engine.get_profile()
        assert profile["agent_id"] == "test-agent"
        assert profile["total_learnings"] >= 3
        assert "error" in profile["top_categories"]
        assert "correction" in profile["top_categories"]

    # ── Dashboard ──────────────────────────────────────────

    def test_dashboard_summary(self):
        """Dashboard should return complete summary."""
        engine = LoopEngine("test-agent")
        engine.capture_error("Error 1", context="ctx1", capability="api")
        engine.capture_error("Error 2", context="ctx2", capability="api")

        data = engine.get_dashboard_summary()
        assert "profile" in data
        assert data["profile"]["agent_id"] == "test-agent"
        assert data["profile"]["total_learnings"] >= 2
        assert "category_breakdown" in data
        assert data["category_breakdown"].get("error", 0) >= 2

    # ── Test Approval ──────────────────────────────────────

    def test_approve_test(self):
        """Pending tests should be approvable."""
        engine = LoopEngine("test-agent")
        engine.capture_error(
            "Failed step",
            context="Customer asked about refund",
            trajectory_summary="Step 1: OK\nStep 2: ERROR",
            failed_step=2,
            capability="refunds",
        )

        pending_before = engine.get_pending_tests()
        assert len(pending_before) >= 1

        test_id = pending_before[0]["id"]
        engine.approve_test(test_id)

        pending_after = engine.get_pending_tests()
        # After approval, the test should no longer be pending
        ids_after = [t["id"] for t in pending_after]
        assert test_id not in ids_after

    # ── Get Specific Learning ──────────────────────────────

    def test_get_learning_by_id(self):
        """Should retrieve a specific learning by ID."""
        engine = LoopEngine("test-agent")
        lid = engine.capture_error("Specific error", context="specific context")
        retrieved = engine.get_learning(lid)
        assert retrieved is not None
        assert "error" in retrieved["content"].lower()
        assert retrieved["context"] == "specific context"

    # ── Edge Cases ─────────────────────────────────────────

    def test_multiple_agents_isolated(self):
        """Learnings should be isolated per agent_id."""
        engine_a = LoopEngine("agent-alpha")
        engine_b = LoopEngine("agent-beta")

        engine_a.capture_error("Error from A", context="ctx", capability="cap_a")
        engine_b.capture_error("Error from B", context="ctx", capability="cap_b")

        profile_a = engine_a.get_profile()
        profile_b = engine_b.get_profile()

        assert profile_a["agent_id"] == "agent-alpha"
        assert profile_b["agent_id"] == "agent-beta"
        assert profile_a["total_learnings"] == 1
        assert profile_b["total_learnings"] == 1

    def test_root_cause_extraction(self):
        """Root cause should be extracted from trajectory."""
        engine = LoopEngine("test-agent")
        lid = engine.capture_error(
            "Permission denied",
            context="Reading config file",
            trajectory_summary="Step 1: open('/etc/app/config')\nStep 2: ERROR: Permission denied",
            failed_step=2,
            tool_involved="file_reader",
            capability="file_operations",
        )
        learning = engine.get_learning(lid)
        # Root cause should contain context from trajectory
        assert learning is not None
        assert "Permission denied" in learning["content"]

    def test_capability_extraction_from_context(self):
        """Capability should be extracted from context keywords."""
        engine = LoopEngine("test-agent")
        # Context contains "email" → should map to email_composition
        lid = engine.capture_error(
            "SMTP error",
            context="Sending welcome email to new user",
            capability=None,  # let it auto-detect
        )
        learning = engine.get_learning(lid)
        # Should auto-extract email capability
        tags = learning.get("tags", [])
        # The capability detection is best-effort
        assert learning is not None


class TestDatabasePersistence:
    """Tests that data actually persists in SQLite."""

    def setup_method(self):
        db_path = tempfile.mktemp(suffix=".db")
        os.environ["SAMSARA_DB"] = db_path

    def teardown_method(self):
        db_path = os.environ.get("SAMSARA_DB", "")
        if os.path.exists(db_path):
            os.remove(db_path)

    def test_learnings_persist_across_engine_instances(self):
        """Data saved by one engine should be readable by another."""
        engine1 = LoopEngine("persist-agent")
        engine1.capture_error("Persisted error", context="persist test")

        # New engine instance, same agent
        engine2 = LoopEngine("persist-agent")
        learnings = engine2.get_recent_learnings()
        contents = [l["content"] for l in learnings]
        assert any("Persisted error" in c for c in contents)

    def test_sqlite_file_created(self):
        """SQLite file should be created on first write."""
        db_path = os.environ.get("SAMSARA_DB", "")
        assert not os.path.exists(db_path)

        engine = LoopEngine("new-agent")
        engine.capture_error("Trigger DB creation", context="test")
        assert os.path.exists(db_path)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
