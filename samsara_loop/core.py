"""
Samsara Loop Core — The Agent Feedback Loop Engine.
Forked from self-improving-agent (MIT) with major extensions.

The feedback loop:
1. Agent encounters failure → logs learning
2. System generates test case from failure
3. Human reviews (or agent auto-approves)
4. Test case enters eval suite
5. Agent runs self-eval before attempting similar tasks
6. Capability self-model updated
"""

import uuid
import json
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from samsara_loop.types import Learning, TestCase, LearningCategory, LearningStatus, EvalResult
from samsara_loop.db import database as db


class LoopEngine:
    """
    The core feedback loop engine.
    The agent calls these methods directly.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    # ── Step 1: Capture ──────────────────────────────────────

    def capture_error(
        self,
        error_message: str,
        context: str,
        trajectory_summary: Optional[str] = None,
        failed_step: Optional[int] = None,
        tool_involved: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> str:
        """
        Agent calls this when something goes wrong.
        Creates a learning entry + optionally generates a test case.
        """
        learning_id = self._log_learning(
            category=LearningCategory.ERROR,
            content=error_message,
            context=context,
            trajectory_summary=trajectory_summary,
            failed_step=failed_step,
            tool_involved=tool_involved,
            capability=capability,
            priority=2 if failed_step is not None else 1,
        )

        # Auto-generate test case for step-level failures
        if failed_step is not None:
            test_case_id = self._generate_test_case(
                learning_id, error_message, context, trajectory_summary,
                capability=capability
            )
            if test_case_id:
                db.link_test_case_to_learning(learning_id, test_case_id)

        return learning_id

    def capture_correction(
        self,
        content: str,
        context: str,
        what_was_wrong: str,
        capability: Optional[str] = None,
    ) -> str:
        """Agent calls this when a human corrected it."""
        return self._log_learning(
            category=LearningCategory.CORRECTION,
            content=f"Correction: {content}\nWhat was wrong: {what_was_wrong}",
            context=context,
            capability=capability,
            source="human",
            priority=2,
        )

    def capture_best_practice(
        self,
        discovery: str,
        context: str,
        pattern_key: Optional[str] = None,
    ) -> str:
        """Agent calls this when it discovers a better way."""
        return self._log_learning(
            category=LearningCategory.BEST_PRACTICE,
            content=discovery,
            context=context,
            pattern_key=pattern_key,
            priority=1,
        )

    def capture_knowledge_gap(
        self,
        what_was_missing: str,
        context: str,
    ) -> str:
        """Agent calls this when it realizes it didn't know something."""
        return self._log_learning(
            category=LearningCategory.KNOWLEDGE_GAP,
            content=what_was_missing,
            context=context,
            priority=1,
        )

    # ── Step 2: Generate ─────────────────────────────────────

    def _generate_test_case(
        self,
        learning_id: str,
        failure_message: str,
        context: str,
        trajectory_summary: Optional[str],
        capability: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate a test case from a failure learning.
        This is the production → test conversion.
        """
        if not trajectory_summary:
            return None

        # Use explicitly passed capability, or extract from context
        capability = capability or self._extract_capability(context)
        root_cause = self._extract_root_cause(trajectory_summary, failure_message)
        fix = self._suggest_fix(root_cause)

        tc = TestCase(
            id=str(uuid.uuid4()),
            agent_id=self.agent_id,
            capability=capability,
            input_description=context,
            failure_trace=trajectory_summary,
            root_cause=root_cause,
            fix_suggestion=fix,
            generated_from_learning_id=learning_id,
            status="pending",
        )
        db.save_test_case(tc)
        return tc.id

    def _extract_capability(self, context: str) -> str:
        """Extract the capability domain from context."""
        context_lower = context.lower()
        keywords = {
            "refund": "refund_processing",
            "customer support": "customer_support",
            "code": "code_generation",
            "git": "git_operations",
            "deploy": "deployment",
            "search": "search",
            "memory": "memory_operations",
            "file": "file_operations",
            "api": "api_calls",
            "database": "database_queries",
            "email": "email_composition",
        }
        for keyword, cap in keywords.items():
            if keyword in context_lower:
                return cap
        return "general_task"

    def _extract_root_cause(self, trajectory: str, error: str) -> str:
        """Extract root cause from trajectory + error message."""
        # Pattern: if "error" appears in trajectory, extract nearby text
        lines = trajectory.split("\n")
        for i, line in enumerate(lines):
            if "fail" in line.lower() or "error" in line.lower():
                # Get surrounding context
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                return "\n".join(lines[start:end])
        return error[:200]

    def _suggest_fix(self, root_cause: str) -> str:
        """Generate a fix suggestion from root cause analysis."""
        cause_lower = root_cause.lower()
        if "permission" in cause_lower:
            return "Check file/directory permissions before attempting operation."
        if "not found" in cause_lower:
            return "Verify resource exists before attempting to use it."
        if "timeout" in cause_lower:
            return "Add retry logic with exponential backoff."
        if "auth" in cause_lower or "token" in cause_lower:
            return "Verify authentication credentials before request."
        return "Review the failure step and add appropriate validation before retry."

    # ── Step 3: Promote ──────────────────────────────────────

    def get_learning(self, learning_id: str) -> Optional[Dict]:
        """Get a specific learning."""
        learnings = db.get_learnings(self.agent_id, limit=1000)
        for l in learnings:
            if l["id"] == learning_id:
                return l
        return None

    def get_recent_learnings(self, category: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """Get recent learnings."""
        return db.get_learnings(self.agent_id, category=category, limit=limit)

    def get_pending_tests(self) -> List[Dict]:
        """Get pending test cases for review."""
        return db.get_pending_test_cases(self.agent_id)

    def approve_test(self, test_case_id: str) -> None:
        """Human (or agent) approves a test case."""
        db.approve_test_case(test_case_id)

    def promote_learning(
        self,
        learning_id: str,
        target: str,
    ) -> None:
        """
        Promote a learning to a permanent location.
        target: 'memory', 'skill', or 'agent_file'
        """
        db.update_learning_status(learning_id, LearningStatus.PROMOTED.value, promoted_to=target)

    # ── Step 4: Eval ─────────────────────────────────────────

    def run_self_eval(self, capability: str) -> Dict[str, Any]:
        """
        Agent runs self-evaluation before attempting a task.
        Returns: { can_attempt, test_count, pass_rate, recommendations }
        """
        tests = db.get_test_cases(self.agent_id, status=None)
        cap_tests = [t for t in tests if t.get("capability") == capability]
        approved_tests = [t for t in cap_tests if t.get("status") == "approved"]

        if not approved_tests:
            return {
                "can_attempt": True,
                "test_count": 0,
                "pass_rate": None,
                "recommendation": "No prior test data — proceed with standard confidence.",
                "tests": [],
            }

        passing = [t for t in approved_tests if t.get("last_run_result") == "pass"]
        pass_rate = len(passing) / len(approved_tests) if approved_tests else 0.0

        recommendations = []
        if pass_rate >= 0.85:
            can_attempt = True
            recommendations.append(f"Strong track record ({pass_rate:.0%} pass rate) — proceed.")
        elif pass_rate >= 0.6:
            can_attempt = True
            recommendations.append(f"Moderate track record ({pass_rate:.0%} pass rate) — proceed with care.")
        else:
            can_attempt = False
            recommendations.append(f"Weak track record ({pass_rate:.0%} pass rate) — consider declining or escalating.")

        # List specific failing tests
        failing = [t for t in approved_tests if t.get("last_run_result") == "fail"]
        if failing:
            recommendations.append(f"{len(failing)} failing test(s) on record: {[t['capability'] for t in failing]}")

        return {
            "can_attempt": can_attempt,
            "test_count": len(approved_tests),
            "pass_rate": pass_rate,
            "passing_count": len(passing),
            "failing_count": len(failing),
            "recommendations": recommendations,
            "tests": approved_tests,
        }

    def get_profile(self) -> Dict[str, Any]:
        """Get the agent's learning profile."""
        profile = db.refresh_agent_profile(self.agent_id)
        return {
            "agent_id": profile.agent_id,
            "total_learnings": profile.total_learnings,
            "eval_suite_pass_rate": profile.eval_suite_pass_rate,
            "test_suite": {
                "total": profile.total_test_cases,
                "passing": profile.passing_tests,
                "failing": profile.failing_tests,
            },
            "top_categories": profile.top_categories,
            "strong_capabilities": profile.strong_capabilities,
            "weak_capabilities": profile.weak_capabilities,
            "recent_failures": profile.recent_failures,
        }

    # ── Step 5: Log ──────────────────────────────────────────

    def _log_learning(
        self,
        category: LearningCategory,
        content: str,
        context: str,
        trajectory_summary: Optional[str] = None,
        failed_step: Optional[int] = None,
        tool_involved: Optional[str] = None,
        capability: Optional[str] = None,
        pattern_key: Optional[str] = None,
        source: str = "agent",
        priority: int = 0,
    ) -> str:
        """Internal: write a learning to the database."""
        # Generate deduplication key from content
        dedup_key = re.sub(r'\s+', ' ', content.lower())[:100]
        pattern_key = pattern_key or f"auto-{dedup_key[:30].replace(' ', '-')}"

        learning = Learning(
            agent_id=self.agent_id,
            category=category,
            content=content,
            context=context,
            source=source,
            pattern_key=pattern_key,
            priority=priority,
            trajectory_summary=trajectory_summary,
            failed_step=failed_step,
            tool_involved=tool_involved,
            tags=[capability] if capability else [],
        )
        db.log_learning(learning)
        return learning.id

    # ── Dashboard Data ───────────────────────────────────────

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get all data needed for the dashboard."""
        learnings = db.get_learnings(self.agent_id, limit=100)
        test_cases = db.get_test_cases(self.agent_id)
        profile = db.refresh_agent_profile(self.agent_id)

        return {
            "agent_id": self.agent_id,
            "profile": {
                "agent_id": profile.agent_id,
                "total_learnings": profile.total_learnings,
                "eval_suite_pass_rate": profile.eval_suite_pass_rate,
                "total_tests": profile.total_test_cases,
                "strong_capabilities": profile.strong_capabilities,
                "weak_capabilities": profile.weak_capabilities,
                "test_suite": {
                    "total": profile.total_test_cases,
                    "passing": profile.passing_tests,
                    "failing": profile.failing_tests,
                },
            },
            "learnings_today": len([l for l in learnings if datetime.now().strftime("%Y-%m-%d") in l.get("created_at", "")]),
            "pending_tests": [t for t in test_cases if t.get("status") == "pending"],
            "recent_learnings": learnings[:10],
            "category_breakdown": self._category_breakdown(learnings),
        }

    def _category_breakdown(self, learnings: List[Dict]) -> Dict[str, int]:
        breakdown = {}
        for l in learnings:
            cat = l.get("category", "unknown")
            breakdown[cat] = breakdown.get(cat, 0) + 1
        return breakdown
