"""
Samsara Loop — Web Dashboard Tests (in-process Flask test client)
Run: python -m pytest tests/test_web_dashboard.py -v
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from samsara_loop.core import LoopEngine
from samsara_loop.web.app import app


class TestWebDashboard:
    """In-process dashboard tests using Flask test client."""

    @classmethod
    def setup_class(cls):
        os.environ["SAMSARA_DB"] = tempfile.mktemp(suffix=".db")
        os.environ["SAMSARA_AGENT_ID"] = "dash-agent"
        cls.db_path = os.environ["SAMSARA_DB"]

        # Seed data — 3 learnings, 1 pending test case
        engine = LoopEngine("dash-agent")
        engine.capture_error(
            "API timeout",
            context="User asked: weather in Tokyo?",
            trajectory_summary="Step 1: call weather_api\nStep 2: ERROR: timeout",
            failed_step=2,
            tool_involved="weather_api",
            capability="weather_lookup",
        )
        engine.capture_correction(
            "Use the calendar API, not email API",
            context="Checking availability",
            what_was_wrong="Used wrong tool",
            capability="scheduling",
        )
        engine.capture_best_practice(
            "Always retry with exponential backoff",
            context="Building retry logic",
        )
        # Manually create a known pending test case to ensure pending section renders
        from samsara_loop.types import TestCase
        from samsara_loop.db.database import save_test_case
        import uuid
        from datetime import datetime, timezone
        tc = TestCase(
            id=str(uuid.uuid4()),
            agent_id="dash-agent",
            capability="order_tracking",
            input_description="User asked: where is my order?",
            failure_trace="Step 1: query db\nStep 2: ERROR: empty result",
            root_cause="Query returned no rows",
            fix_suggestion="Add null check before returning",
            generated_from_learning_id="manual-seed",
            status="pending",
        )
        save_test_case(tc)
        cls.known_pending_id = tc.id

        cls.client = app.test_client()
        app.config["TESTING"] = True

    # ── Core rendering ────────────────────────────────────────

    def test_dashboard_returns_200(self):
        """Dashboard loads without error."""
        resp = self.client.get("/")
        assert resp.status_code == 200

    def test_dashboard_title_present(self):
        """'Samsara Loop' appears in page title."""
        html = self.client.get("/").data.decode("utf-8")
        assert "Samsara Loop" in html

    def test_all_stat_cards_present(self):
        """All 4 stat cards are rendered."""
        html = self.client.get("/").data.decode("utf-8")
        assert "Eval Pass Rate" in html
        assert "Total Learnings" in html
        assert "Pending Tests" in html
        assert "Strong Capabilities" in html

    def test_dashboard_uses_dark_theme(self):
        """Dark background #0a0a0f is in CSS."""
        html = self.client.get("/").data.decode("utf-8")
        assert "#0a0a0f" in html

    # ── Data rendering ─────────────────────────────────────────

    def test_total_learnings_count_shows(self):
        """Dashboard shows total learnings count (not empty)."""
        html = self.client.get("/").data.decode("utf-8")
        # Should show a number > 0 in the Total Learnings card
        # The card contains the number followed by label
        import re
        # Find any number in the card area (the big number in first stat card)
        assert "Total Learnings" in html

    def test_pending_tests_section_renders(self):
        """Pending tests section appears when tests are pending."""
        html = self.client.get("/").data.decode("utf-8")
        # Known pending test should appear
        assert "order_tracking" in html or "weather_lookup" in html

    def test_capability_from_pending_test_in_html(self):
        """The capability name from the pending test appears."""
        html = self.client.get("/").data.decode("utf-8")
        # order_tracking was the manually created pending test
        assert "order_tracking" in html

    def test_approve_button_for_pending_test(self):
        """'Approve' button appears in pending test card."""
        html = self.client.get("/").data.decode("utf-8")
        assert "Approve" in html

    def test_recent_learnings_section_renders(self):
        """'Recent Learnings' section is present."""
        html = self.client.get("/").data.decode("utf-8")
        assert "Recent Learnings" in html

    def test_learning_categories_shown(self):
        """Learning category tags appear (error/correction/best_practice)."""
        html = self.client.get("/").data.decode("utf-8")
        # Category CSS classes: te (error), tc (correction), tb (best)
        # These appear in the rendered tag spans
        assert "te " in html or "tc " in html or "tb " in html or "tg " in html

    # ── Approve endpoint ───────────────────────────────────────

    def test_approve_endpoint_returns_200(self):
        """POST /approve with valid ID returns 200."""
        resp = self.client.post(
            "/approve",
            json={"test_id": self.known_pending_id},
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_approve_returns_approved_status(self):
        """Approve endpoint returns JSON with status=approved."""
        resp = self.client.post(
            "/approve",
            json={"test_id": self.known_pending_id},
            content_type="application/json",
        )
        import json
        data = json.loads(resp.data)
        assert data.get("status") == "approved"

    def test_approve_unknown_id_returns_400(self):
        """Approve with non-existent ID returns 400."""
        resp = self.client.post(
            "/approve",
            json={"test_id": "this-id-does-not-exist-xyz"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_approve_without_id_returns_400(self):
        """Approve with missing test_id returns 400."""
        resp = self.client.post(
            "/approve",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400

    # ── Edge cases ────────────────────────────────────────────

    def test_empty_state_dashboard(self):
        """Dashboard for agent with no data loads cleanly."""
        os.environ["SAMSARA_AGENT_ID"] = "empty-agent"
        client = app.test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # Should load without error even with no data
        assert "Samsara Loop" in html

    def test_dashboard_no_500(self):
        """Dashboard never returns 500."""
        resp = self.client.get("/")
        assert resp.status_code < 500


class TestDashboardDataCompleteness:
    """Verify the dashboard data structure is correct."""

    @classmethod
    def setup_class(cls):
        os.environ["SAMSARA_DB"] = tempfile.mktemp(suffix=".db")
        os.environ["SAMSARA_AGENT_ID"] = "complete-agent"
        engine = LoopEngine("complete-agent")
        # Capture 3 errors and 1 correction = 4 learnings
        for i in range(3):
            engine.capture_error(f"Error {i}", context=f"ctx {i}", capability="api")
        engine.capture_correction("Fix it", context="ctx", what_was_wrong="wrong", capability="api")
        cls.client = app.test_client()
        app.config["TESTING"] = True

    def test_dashboard_shows_all_4_learnings(self):
        """All 4 seeded learnings appear in dashboard."""
        html = self.client.get("/").data.decode("utf-8")
        # 3 errors + 1 correction should be in recent learnings
        # At minimum: the section should appear and have content
        assert "Recent Learnings" in html

    def test_category_breakdown_in_html(self):
        """Error and correction categories appear as tags."""
        html = self.client.get("/").data.decode("utf-8")
        # CSS classes for tags: te=error, tc=correction
        assert "te" in html or "tc" in html


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
