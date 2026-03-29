"""
Samsara Loop Database Layer — SQLite persistence.
Forked from self-improving-agent (file-based) → SQLite.
"""
import os
import sqlite3
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
from samsara_loop.types import Learning, TestCase, EvalResult, AgentProfile


DB_PATH = "~/.samsara_loop/samsara_loop.db"


def get_db():
    db_path = os.environ.get("SAMSARA_DB", DB_PATH)
    if isinstance(db_path, str):
        db_path = os.path.expanduser(os.path.expandvars(db_path))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables."""
    conn = get_db()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS learnings (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            context TEXT DEFAULT '',
            source TEXT DEFAULT 'agent',
            pattern_key TEXT,
            status TEXT DEFAULT 'active',
            priority INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            tags TEXT DEFAULT '[]',
            metadata TEXT DEFAULT '{}',
            trajectory_summary TEXT,
            failed_step INTEGER,
            tool_involved TEXT,
            test_case_id TEXT,
            promoted_to TEXT
        );
        CREATE TABLE IF NOT EXISTS test_cases (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            capability TEXT NOT NULL,
            input_description TEXT NOT NULL,
            failure_trace TEXT NOT NULL,
            root_cause TEXT NOT NULL,
            fix_suggestion TEXT NOT NULL,
            generated_from_learning_id TEXT,
            status TEXT DEFAULT 'pending',
            last_run_at TEXT,
            last_run_result TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS eval_results (
            id TEXT PRIMARY KEY,
            test_case_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            run_at TEXT NOT NULL,
            result TEXT NOT NULL,
            output TEXT DEFAULT '',
            failure_step INTEGER,
            failure_reason TEXT,
            latency_ms REAL,
            confidence_before REAL,
            confidence_after REAL,
            metadata TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS agent_profiles (
            agent_id TEXT PRIMARY KEY,
            total_learnings INTEGER DEFAULT 0,
            total_test_cases INTEGER DEFAULT 0,
            passing_tests INTEGER DEFAULT 0,
            failing_tests INTEGER DEFAULT 0,
            eval_suite_pass_rate REAL DEFAULT 0.0,
            top_categories TEXT DEFAULT '[]',
            recent_failures TEXT DEFAULT '[]',
            strong_capabilities TEXT DEFAULT '[]',
            weak_capabilities TEXT DEFAULT '[]',
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_learnings_agent ON learnings(agent_id);
        CREATE INDEX IF NOT EXISTS idx_learnings_category ON learnings(category);
        CREATE INDEX IF NOT EXISTS idx_test_cases_agent ON test_cases(agent_id);
        CREATE INDEX IF NOT EXISTS idx_test_cases_capability ON test_cases(capability);
        CREATE INDEX IF NOT EXISTS idx_eval_results_agent ON eval_results(agent_id);
    """)
    conn.commit()
    conn.close()


@contextmanager
def get_conn():
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


# ── Learnings ──────────────────────────────────────────────

def log_learning(learning: Learning) -> str:
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO learnings (
                id, agent_id, category, content, context, source,
                pattern_key, status, priority, created_at, tags, metadata,
                trajectory_summary, failed_step, tool_involved, test_case_id, promoted_to
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            learning.id, learning.agent_id, learning.category.value,
            learning.content, learning.context, learning.source,
            learning.pattern_key, learning.status.value, learning.priority,
            learning.created_at,
            json.dumps(learning.tags),
            json.dumps(learning.metadata),
            learning.trajectory_summary, learning.failed_step,
            learning.tool_involved, learning.test_case_id, learning.promoted_to
        ))
        conn.commit()
    return learning.id


def get_learnings(
    agent_id: str,
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()
        query = "SELECT * FROM learnings WHERE agent_id = ?"
        params = [agent_id]
        if category:
            query += " AND category = ?"
            params.append(category)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_row_to_learning(r) for r in rows]


def _row_to_learning(row: sqlite3.Row) -> Dict:
    from samsara_loop.types import Learning, LearningCategory, LearningStatus
    return {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "category": row["category"],
        "content": row["content"],
        "context": row["context"],
        "source": row["source"],
        "pattern_key": row["pattern_key"],
        "status": row["status"],
        "priority": row["priority"],
        "created_at": row["created_at"],
        "tags": json.loads(row["tags"]),
        "metadata": json.loads(row["metadata"]),
        "trajectory_summary": row["trajectory_summary"],
        "failed_step": row["failed_step"],
        "tool_involved": row["tool_involved"],
        "test_case_id": row["test_case_id"],
        "promoted_to": row["promoted_to"],
    }


def update_learning_status(learning_id: str, status: str, promoted_to: str = None) -> None:
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()
        if promoted_to:
            cur.execute(
                "UPDATE learnings SET status=?, promoted_to=?, updated_at=? WHERE id=?",
                (status, promoted_to, datetime.now(timezone.utc).isoformat(), learning_id)
            )
        else:
            cur.execute(
                "UPDATE learnings SET status=?, updated_at=? WHERE id=?",
                (status, datetime.now(timezone.utc).isoformat(), learning_id)
            )
        conn.commit()


def link_test_case_to_learning(learning_id: str, test_case_id: str) -> None:
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE learnings SET test_case_id=? WHERE id=?",
            (test_case_id, learning_id)
        )
        conn.commit()


# ── Test Cases ──────────────────────────────────────────────

def save_test_case(tc: TestCase) -> str:
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO test_cases
            (id, agent_id, capability, input_description, failure_trace,
             root_cause, fix_suggestion, generated_from_learning_id,
             status, last_run_at, last_run_result, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tc.id, tc.agent_id, tc.capability, tc.input_description,
            tc.failure_trace, tc.root_cause, tc.fix_suggestion,
            tc.generated_from_learning_id, tc.status, tc.last_run_at, tc.last_run_result,
            getattr(tc, 'created_at', None) or now
        ))
        conn.commit()
    return tc.id


def get_test_cases(agent_id: str, status: Optional[str] = None) -> List[Dict]:
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()
        if status:
            cur.execute(
                "SELECT * FROM test_cases WHERE agent_id=? AND status=? ORDER BY created_at DESC",
                (agent_id, status)
            )
        else:
            cur.execute(
                "SELECT * FROM test_cases WHERE agent_id=? ORDER BY created_at DESC",
                (agent_id,)
            )
        return [dict(r) for r in cur.fetchall()]


def approve_test_case(test_case_id: str) -> None:
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE test_cases SET status='approved' WHERE id=?", (test_case_id,))
        conn.commit()


def get_pending_test_cases(agent_id: str) -> List[Dict]:
    return get_test_cases(agent_id, status="pending")


# ── Eval Results ────────────────────────────────────────────

def save_eval_result(result: EvalResult) -> str:
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO eval_results
            (id, test_case_id, agent_id, run_at, result, output,
             failure_step, failure_reason, latency_ms,
             confidence_before, confidence_after, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.id, result.test_case_id, result.agent_id, result.run_at,
            result.result, result.output, result.failure_step, result.failure_reason,
            result.latency_ms, result.confidence_before, result.confidence_after,
            json.dumps(result.metadata)
        ))
        conn.commit()
    return result.id


# ── Agent Profile ───────────────────────────────────────────

def get_agent_profile(agent_id: str) -> AgentProfile:
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM agent_profiles WHERE agent_id=?", (agent_id,))
        row = cur.fetchone()
    if not row:
        return AgentProfile(agent_id=agent_id)
    return AgentProfile(
        agent_id=row["agent_id"],
        total_learnings=row["total_learnings"],
        total_test_cases=row["total_test_cases"],
        passing_tests=row["passing_tests"],
        failing_tests=row["failing_tests"],
        eval_suite_pass_rate=row["eval_suite_pass_rate"],
        top_categories=json.loads(row["top_categories"]),
        recent_failures=json.loads(row["recent_failures"]),
        strong_capabilities=json.loads(row["strong_capabilities"]),
        weak_capabilities=json.loads(row["weak_capabilities"]),
        updated_at=row["updated_at"],
    )


def refresh_agent_profile(agent_id: str) -> AgentProfile:
    """Recalculate profile stats from learnings and test_cases tables."""
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()
        # Learnings count by category
        cur.execute(
            "SELECT category, COUNT(*) as cnt FROM learnings WHERE agent_id=? GROUP BY category",
            (agent_id,)
        )
        cat_counts = {r["category"]: r["cnt"] for r in cur.fetchall()}
        top_cats = sorted(cat_counts, key=cat_counts.get, reverse=True)[:3]

        # Test case stats
        cur.execute(
            "SELECT status, COUNT(*) as cnt FROM test_cases WHERE agent_id=? GROUP BY status",
            (agent_id,)
        )
        tc_stats = {r["status"]: r["cnt"] for r in cur.fetchall()}
        passing = tc_stats.get("passing", 0)
        failing = tc_stats.get("failing", 0) + tc_stats.get("pending", 0)
        total_tc = passing + failing
        pass_rate = passing / total_tc if total_tc > 0 else 0.0

        # Recent failures
        cur.execute(
            """SELECT DISTINCT capability FROM test_cases
               WHERE agent_id=? AND status='failing'
               ORDER BY last_run_at DESC LIMIT 5""",
            (agent_id,)
        )
        recent_failures = [r["capability"] for r in cur.fetchall()]

        # Strong/weak capabilities (based on pass rate per capability)
        cur.execute(
            """SELECT capability,
                      SUM(CASE WHEN last_run_result='pass' THEN 1 ELSE 0 END) as passes,
                      COUNT(*) as total
               FROM test_cases
               WHERE agent_id=? AND last_run_result IS NOT NULL
               GROUP BY capability""",
            (agent_id,)
        )
        strong, weak = [], []
        for r in cur.fetchall():
            rate = r["passes"] / r["total"] if r["total"] > 0 else 0
            if rate >= 0.8:
                strong.append(r["capability"])
            elif rate < 0.6:
                weak.append(r["capability"])

    profile = AgentProfile(
        agent_id=agent_id,
        total_learnings=sum(cat_counts.values()),
        total_test_cases=total_tc,
        passing_tests=passing,
        failing_tests=failing,
        eval_suite_pass_rate=pass_rate,
        top_categories=top_cats,
        recent_failures=recent_failures,
        strong_capabilities=strong,
        weak_capabilities=weak,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT OR REPLACE INTO agent_profiles
            (agent_id, total_learnings, total_test_cases, passing_tests,
             failing_tests, eval_suite_pass_rate, top_categories,
             recent_failures, strong_capabilities, weak_capabilities, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, profile.total_learnings, profile.total_test_cases,
             profile.passing_tests, profile.failing_tests, profile.eval_suite_pass_rate,
             json.dumps(profile.top_categories), json.dumps(profile.recent_failures),
             json.dumps(profile.strong_capabilities), json.dumps(profile.weak_capabilities),
             profile.updated_at)
        )
        conn.commit()
    return profile
