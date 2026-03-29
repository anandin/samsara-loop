"""
Samsara Loop — The Agent Feedback Loop Engine
Forked from self-improving-agent (MIT) with major extensions.

What it does: Converts agent failures into permanent test coverage.
The agent captures its own failures, generates test cases automatically,
and updates its eval suite — no human in the loop for the capture.

Extensions from original:
- SQLite persistence (not file-based)
- MCP server interface (any MCP-speaking agent can use it)
- Trajectory capture (step-level failure, not just summary)
- Automatic test case generation from failures
- Web dashboard for human review/approval
- Cross-agent learning transfer

License: MIT (same as original)
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import uuid


class LearningCategory(str, Enum):
    CORRECTION = "correction"          # Human corrected the agent
    ERROR = "error"                    # Command/API/tool failed
    KNOWLEDGE_GAP = "knowledge_gap"   # Agent's knowledge was wrong
    BEST_PRACTICE = "best_practice"   # Better approach found
    CAPABILITY = "capability"          # New capability discovered
    SIMPLIFY = "simplify"             # Pattern to harden


class LearningStatus(str, Enum):
    ACTIVE = "active"                  # Currently valid
    PROMOTED = "promoted"              # Moved to memory/skill
    SUPERSEDED = "superseded"          # Replaced by newer learning
    DISCARDED = "discarded"            # Not useful


class TestCase(BaseModel):
    """A regression test case generated from a failure."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    capability: str                          # What type of task this tests
    input_description: str                    # What the agent was asked to do
    failure_trace: str                        # What went wrong (step-level)
    root_cause: str                          # Why it went wrong
    fix_suggestion: str                      # How to fix it
    generated_from_learning_id: str           # Which learning triggered this
    status: str = "pending"                  # pending | approved | failing | passing
    last_run_at: Optional[str] = None
    last_run_result: Optional[str] = None    # pass | fail | error


class Learning(BaseModel):
    """
    A single learning captured by the agent.
    Captured when: error, correction, discovery, capability gap.
    """
    id: str = Field(default_factory=lambda: f"LRN-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}")
    agent_id: str
    category: LearningCategory
    content: str                              # What was learned
    context: str                              # When/where it happened
    source: str = "agent"                     # agent | human | system
    pattern_key: Optional[str] = None         # For SIMPLIFY-HARDEN patterns
    status: LearningStatus = LearningStatus.ACTIVE
    priority: int = 0                         # 0=low, 1=medium, 2=high
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Trajectory capture (step-level)
    trajectory_summary: Optional[str] = None  # Step-by-step of what happened
    failed_step: Optional[int] = None          # Which step failed
    tool_involved: Optional[str] = None        # Which tool was involved
    test_case_id: Optional[str] = None        # Generated test case, if any
    promoted_to: Optional[str] = None         # memory/skill/agent file it was promoted to


class EvalResult(BaseModel):
    """Result of running an agent against a test case."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    test_case_id: str
    agent_id: str
    run_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: str                               # pass | fail | error
    output: str                               # What the agent returned
    failure_step: Optional[int] = None
    failure_reason: Optional[str] = None
    latency_ms: float
    confidence_before: Optional[float] = None
    confidence_after: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentProfile(BaseModel):
    """Profile of what an agent has learned to do."""
    agent_id: str
    total_learnings: int = 0
    total_test_cases: int = 0
    passing_tests: int = 0
    failing_tests: int = 0
    eval_suite_pass_rate: float = 0.0        # 0-1
    top_categories: List[str] = []            # Most common learning types
    recent_failures: List[str] = []           # Last 5 failure pattern keys
    strong_capabilities: List[str] = []        # Capabilities with >80% test pass rate
    weak_capabilities: List[str] = []          # Capabilities with <60% test pass rate
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
