"""
Trajectory Scoring Engine — The Core Judgment Module.

Given an agent's execution trace (steps + outcomes), this engine answers:
    "Should I have tried this? How well did I do? What does this teach me?"

Outputs a multi-dimensional score (0-100) with:
  - Overall composite score
  - Per-dimension breakdown (quality, efficiency, recovery, tool_use)
  - Normalized percentile (how this compares to past attempts)
  - Recommendation: proceed | caution | decline
  - One-line explanation suitable for the agent's working memory

Design principles:
  - Heuristic-first (fast, interpretable) — LLM only for complex cases
  - Scores are additive, dimensions are independent
  - No external API required for baseline scoring
  - Outputs are stored in episodic memory alongside the trajectory
"""

from __future__ import annotations
import uuid
import re
from dataclasses import dataclass, field
from typing import Optional


# ─── Score card ────────────────────────────────────────────────────────────

@dataclass
class ScoreCard:
    """
    The complete scoring output for a single trajectory.
    All scores are 0-100 unless noted.
    """
    trajectory_id: str
    overall: float                          # 0-100 composite
    quality: float                           # 0-100 — did the right steps succeed?
    efficiency: float                        # 0-100 — how economically was this solved?
    recovery: float                          # 0-100 — did it recover from errors?
    tool_use: float                          # 0-100 — were the right tools used?
    safety: float                            # 0-100 — no catastrophic failures?
    # Raw inputs used
    total_steps: int
    successful_steps: int
    failed_steps: int
    total_latency_ms: float
    had_recovery: bool
    # Normalized
    percentile: float = 0.0                  # 0-100 — relative to past attempts
    # Recommendation
    recommendation: str = "proceed"          # proceed | caution | decline
    recommendation_reason: str = ""
    # Breakdown tags
    failure_patterns: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    # Formatted one-liner for working memory
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "trajectory_id": self.trajectory_id,
            "overall": round(self.overall, 1),
            "quality": round(self.quality, 1),
            "efficiency": round(self.efficiency, 1),
            "recovery": round(self.recovery, 1),
            "tool_use": round(self.tool_use, 1),
            "safety": round(self.safety, 1),
            "total_steps": self.total_steps,
            "successful_steps": self.successful_steps,
            "failed_steps": self.failed_steps,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "had_recovery": self.had_recovery,
            "percentile": round(self.percentile, 1),
            "recommendation": self.recommendation,
            "recommendation_reason": self.recommendation_reason,
            "failure_patterns": self.failure_patterns,
            "strengths": self.strengths,
            "summary": self.summary,
        }


@dataclass
class StepRecord:
    """A single step in an agent's execution trace."""
    step: int
    tool_name: str
    success: bool
    latency_ms: float
    error: Optional[str] = None
    input_summary: str = ""                  # brief description of tool input
    output_summary: str = ""                # brief description of tool output


# ─── Scoring weights ─────────────────────────────────────────────────────────

WEIGHTS = dict(quality=0.30, efficiency=0.20, recovery=0.20, tool_use=0.15, safety=0.15)


# ─── Main scorer ────────────────────────────────────────────────────────────

class TrajectoryScorer:
    """
    Scores agent execution trajectories across 5 dimensions.

    Usage:
        scorer = TrajectoryScorer()
        steps = [
            StepRecord(step=1, tool_name="browser.navigate", success=True, latency_ms=1200),
            StepRecord(step=2, tool_name="browser.click", success=False, latency_ms=400, error="Element not found"),
        ]
        scorecard = scorer.score(trajectory_id="abc123", steps=steps, capability="web_navigation")
    """

    def __init__(self):
        self._past_scores: dict[str, list[float]] = {}  # capability -> list of overall scores

    # ── Public API ──────────────────────────────────────────────────────────

    def score(
        self,
        trajectory_id: str,
        steps: list[StepRecord],
        capability: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ScoreCard:
        """
        Score a trajectory and return a full ScoreCard.
        """
        total = len(steps)
        successes = sum(1 for s in steps if s.success)
        failures = total - successes
        failed_steps = [s for s in steps if not s.success]
        total_ms = sum(s.latency_ms for s in steps)

        # Dimension scores (0-100 each)
        quality = self._score_quality(successes, failures, total)
        efficiency = self._score_efficiency(total, total_ms, capability)
        recovery_score, recovery_found = self._score_recovery(failed_steps, steps)
        tool_use = self._score_tool_use(steps)
        safety = self._score_safety(failed_steps, steps)

        # Composite
        overall = (
            WEIGHTS["quality"] * quality
            + WEIGHTS["efficiency"] * efficiency
            + WEIGHTS["recovery"] * recovery_score
            + WEIGHTS["tool_use"] * tool_use
            + WEIGHTS["safety"] * safety
        )

        # Percentile vs past attempts
        percentile = self._compute_percentile(capability, overall)

        # Recommendation
        recommendation, reason = self._derive_recommendation(overall, quality, recovery_score, capability)
        failure_patterns = self._extract_patterns(failed_steps)
        strengths = self._extract_strengths(steps, quality, recovery_score)

        # Summary one-liner for working memory
        summary = self._make_summary(overall, recommendation, capability, failures)

        # had_recovery: True only if there were failures AND recovery was found
        had_recovery_flag = failures > 0 and recovery_found

        card = ScoreCard(
            trajectory_id=trajectory_id,
            overall=round(overall, 1),
            quality=round(quality, 1),
            efficiency=round(efficiency, 1),
            recovery=round(recovery_score, 1),
            tool_use=round(tool_use, 1),
            safety=round(safety, 1),
            total_steps=total,
            successful_steps=successes,
            failed_steps=failures,
            total_latency_ms=total_ms,
            had_recovery=had_recovery_flag,
            percentile=round(percentile, 1),
            recommendation=recommendation,
            recommendation_reason=reason,
            failure_patterns=failure_patterns,
            strengths=strengths,
            summary=summary,
        )

        # Record for percentile calc on future attempts
        if capability:
            if capability not in self._past_scores:
                self._past_scores[capability] = []
            self._past_scores[capability].append(overall)

        return card

    # ─── Dimension scorers ─────────────────────────────────────────────────

    def _score_quality(self, successes: int, failures: int, total: int) -> float:
        """
        Quality: did the task succeed, and were the right steps taken?
        Perfect success = 100. Every failure drops the score.
        """
        if total == 0:
            return 50.0  # no steps = ambiguous
        base = (successes / total) * 100
        # Penalise completely wrong outcomes more
        if failures > 0 and successes == 0:
            base = max(0, base - 20)
        return max(0, min(100, base))

    def _score_efficiency(
        self,
        total_steps: int,
        total_ms: float,
        capability: Optional[str],
    ) -> float:
        """
        Efficiency: was this solved with minimum steps and time?
        Penalise unnecessary steps and excessive latency.
        """
        # Baseline: most tasks should be done in ≤10 steps
        step_score = max(0, 100 - (total_steps - 3) * 5)  # -5 per step after step 3
        step_score = min(100, step_score)

        # Latency: baseline 100ms/step
        expected_ms = total_steps * 100
        if expected_ms > 0:
            latency_ratio = min(2.0, total_ms / expected_ms)
            latency_score = max(0, 100 - (latency_ratio - 1) * 50)
        else:
            latency_score = 100

        return (step_score * 0.5) + (latency_score * 0.5)

    def _score_recovery(self, failed_steps: list[StepRecord], all_steps: list[StepRecord]) -> tuple[float, bool]:
        """
        Recovery: did the agent recover from failures?
        If failures occurred but were followed by corrective steps = high recovery.
        If agent gave up or repeated the same error = low recovery.
        Returns (score, recovery_found).
        """
        if not failed_steps:
            return 100.0, False

        # Did any failure get followed by a different tool trying to fix it?
        recovery_found = False
        same_error_repeated = False

        for failed in failed_steps:
            subsequent_steps = [s for s in all_steps if s.step > failed.step]
            # Check if a later step uses a different tool (recovery attempt)
            if any(s.tool_name != failed.tool_name for s in subsequent_steps):
                recovery_found = True
            # Check for repetition of same error
            if any(
                s.tool_name == failed.tool_name
                and not s.success
                and abs(s.step - failed.step) > 0
                for s in all_steps
            ):
                same_error_repeated = True

        if not recovery_found:
            return 15.0, False
        if same_error_repeated:
            return 40.0, True
        # Recovery found + no repetition = good
        return 75.0, True

    def _score_tool_use(self, steps: list[StepRecord]) -> float:
        """
        Tool use: were the right tools selected?
        Penalise: tool errors, wrong tool for the task, unnecessary tools.
        """
        if not steps:
            return 50.0

        scores = []
        for s in steps:
            if s.success:
                # Penalise known-broad tools used for simple tasks
                broad = ["browser", "exec", "search"]
                narrow = ["read", "write", "memory"]
                if any(b in s.tool_name.lower() for b in broad):
                    scores.append(85)  # broad tool = minor penalty
                else:
                    scores.append(100)
            else:
                # Failure — was the tool wrong, or was the tool right but execution failed?
                # Tool-related errors get a lower score than execution errors
                if s.error and any(err in s.error.lower() for err in ["not found", "invalid", "wrong"]):
                    scores.append(30)  # wrong tool = significant penalty
                else:
                    scores.append(50)  # execution failure = partial penalty

        return sum(scores) / len(scores)

    def _score_safety(self, failed_steps: list[StepRecord], all_steps: list[StepRecord]) -> float:
        """
        Safety: did anything catastrophic happen?
        - Destructive operations that failed safely = mild penalty
        - Operations that succeeded but were destructive = larger penalty
        - Operations that partially succeeded before failing = mild penalty
        """
        if not failed_steps:
            return 100.0

        dangerous = {"delete", "drop", "remove", "truncate", "rm", "destroy", "exec", "sudo"}
        penalties = []

        for s in all_steps:
            if not s.success:
                is_dangerous = any(d in s.tool_name.lower() for d in dangerous)
                if is_dangerous:
                    penalties.append(25)  # dangerous operation that failed = notable risk
                else:
                    penalties.append(5)   # routine operation failed = minor
            elif s.success and any(d in s.tool_name.lower() for d in dangerous):
                penalties.append(15)  # dangerous operation succeeded = check if intended

        if not penalties:
            return 100.0
        # Max penalty capped at losing 60 points
        return max(0, 100 - min(60, sum(penalties)))

    # ─── Recommendation engine ─────────────────────────────────────────────

    def _derive_recommendation(
        self,
        overall: float,
        quality: float,
        recovery: float,
        capability: Optional[str],
    ) -> tuple[str, str]:
        """
        Derive the Samsara Loop gate recommendation from the scorecard.
        """
        if overall >= 80 and quality >= 80:
            return (
                "proceed",
                f"Strong execution ({overall:.0f}/100). High success rate. Confident."
            )
        elif overall >= 65 and quality >= 60:
            if recovery < 50:
                return (
                    "caution",
                    f"Capable but recovery was poor ({recovery:.0f}/100). "
                    f"Proceed with verification steps. Score: {overall:.0f}/100."
                )
            return (
                "proceed",
                f"Good execution ({overall:.0f}/100). Proceed with normal caution."
            )
        elif overall >= 50:
            return (
                "caution",
                f"Below-average execution ({overall:.0f}/100). "
                f"Review failure patterns before attempting similar tasks."
            )
        else:
            return (
                "decline",
                f"Weak execution ({overall:.0f}/100). Recommend declining or escalating. "
                f"Review failures and address root cause before retry."
            )

    # ─── Percentile ─────────────────────────────────────────────────────────

    def _compute_percentile(self, capability: Optional[str], score: float) -> float:
        """Percentile of this attempt vs. past attempts for this capability."""
        if not capability or capability not in self._past_scores:
            return 50.0  # no history = median
        past = sorted(self._past_scores[capability])
        if not past:
            return 50.0
        below = sum(1 for s in past if s <= score)
        return round((below / len(past)) * 100, 1)

    # ─── Pattern extraction ─────────────────────────────────────────────────

    FAILURE_KEYWORDS = {
        "not_found": ["not found", "doesn't exist", "does not exist", "404", "no such file"],
        "permission": ["permission denied", "access denied", "unauthorized", "forbidden"],
        "timeout": ["timeout", "timed out", "took too long", "deadline exceeded"],
        "invalid_input": ["invalid", "malformed", "wrong format", "bad request", "400"],
        "network": ["connection refused", "network error", "connection reset", "no internet"],
        "rate_limit": ["rate limit", "too many requests", "429", "quota exceeded"],
        "auth": ["auth", "token", "credential", "unauthorized", "401"],
        "type_error": ["type error", "undefined is not", "cannot read", "is not a function"],
        "unknown": ["unknown error", "internal error", "crash", "panic"],
    }

    def _extract_patterns(self, failed_steps: list[StepRecord]) -> list[str]:
        """Tag each failure with its root-cause pattern."""
        patterns = []
        for s in failed_steps:
            err = (s.error or "").lower()
            for pattern, keywords in self.FAILURE_KEYWORDS.items():
                if any(kw in err for kw in keywords):
                    patterns.append(pattern)
                    break
            else:
                patterns.append("unknown")
        return list(set(patterns))  # dedupe

    def _extract_strengths(self, steps: list[StepRecord], quality: float, recovery: float) -> list[str]:
        """Identify what went well."""
        strengths = []
        if quality >= 90:
            strengths.append("high_step_success_rate")
        if recovery >= 80:
            strengths.append("strong_recovery")
        if all(s.success for s in steps):
            strengths.append("fully_successful")
        if len(steps) <= 4:
            strengths.append("minimal_steps")
        tool_names = [s.tool_name for s in steps if s.success]
        if tool_names:
            strengths.append(f"tools_used:{len(set(tool_names))}")
        return strengths

    # ─── Summary formatter ──────────────────────────────────────────────────

    def _make_summary(
        self,
        overall: float,
        recommendation: str,
        capability: Optional[str],
        failures: int,
    ) -> str:
        cap_str = f"[{capability}] " if capability else ""
        rec_emoji = {"proceed": "✅", "caution": "⚠️", "decline": "🚫"}
        emoji = rec_emoji.get(recommendation, "?")
        fail_str = f" | {failures} step(s) failed" if failures else " | all steps succeeded"
        return (
            f"{emoji} {cap_str}Score {overall:.0f}/100{fail_str} "
            f"— {recommendation.upper()}"
        )
