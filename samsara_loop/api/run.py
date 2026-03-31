"""Vercel Function: POST /api/run — Run a scenario and score it."""
import json, uuid, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from samsara_loop.core import LoopEngine
from samsara_loop.trajectory_scorer import TrajectoryScorer, StepRecord

AGENT_ID = os.environ.get("SAMSARA_AGENT_ID", "vercel-agent")
DB_PATH = os.environ.get("SAMSARA_DB", "/tmp/samsara_loop_vercel.db")

os.environ["SAMSARA_DB"] = DB_PATH

scorer = TrajectoryScorer()

TASK_SCENARIOS = {
    "refund": {
        "capability": "refund_processing",
        "steps": [
            StepRecord(step=1, tool_name="read", success=True, latency_ms=80, input_summary="Read customer order record"),
            StepRecord(step=2, tool_name="browser.navigate", success=True, latency_ms=1200, input_summary="Open refund portal"),
            StepRecord(step=3, tool_name="browser.fill_form", success=True, latency_ms=300, input_summary="Fill refund amount"),
            StepRecord(step=4, tool_name="browser.click", success=True, latency_ms=200, input_summary="Submit refund"),
        ],
    },
    "refund_fail": {
        "capability": "refund_processing",
        "steps": [
            StepRecord(step=1, tool_name="read", success=True, latency_ms=80),
            StepRecord(step=2, tool_name="browser.navigate", success=True, latency_ms=1200),
            StepRecord(step=3, tool_name="browser.fill_form", success=False, latency_ms=150, error="Element not found: refund-amount"),
            StepRecord(step=4, tool_name="browser.click", success=False, latency_ms=100, error="Previous form error"),
        ],
    },
    "code": {
        "capability": "code_generation",
        "steps": [
            StepRecord(step=1, tool_name="read", success=True, latency_ms=60),
            StepRecord(step=2, tool_name="exec", success=True, latency_ms=3000, input_summary="Generate code with LLM"),
            StepRecord(step=3, tool_name="read", success=True, latency_ms=40),
        ],
    },
    "code_fail": {
        "capability": "code_generation",
        "steps": [
            StepRecord(step=1, tool_name="read", success=True, latency_ms=60),
            StepRecord(step=2, tool_name="exec", success=False, latency_ms=5000, error="Timeout: LLM request exceeded 30s"),
        ],
    },
}


def handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS, "body": ""}

    try:
        body = json.loads(event.get("body", "{}"))
    except Exception:
        return api_response(400, {"error": "invalid JSON body"})

    scenario_name = body.get("scenario")
    if scenario_name not in TASK_SCENARIOS:
        return api_response(400, {"error": f"Unknown scenario. Options: {list(TASK_SCENARIOS.keys())}"})

    scenario = TASK_SCENARIOS[scenario_name]
    steps = scenario["steps"]
    capability = scenario["capability"]
    trajectory_id = str(uuid.uuid4())[:8]

    # Score the trajectory
    scorecard = scorer.score(trajectory_id, steps, capability)

    # Initialize engine (creates/opens DB)
    engine = LoopEngine(AGENT_ID)

    # Capture learning if failed
    if scorecard.overall < 80 and scorecard.failed_steps > 0:
        error_step = next((s for s in reversed(steps) if not s.success), None)
        learning_id = engine.capture_error(
            error_message=error_step.error or "Task failed",
            context=f"Scenario: {scenario_name}",
            trajectory_summary="\n".join(
                f"  Step {s.step}: {s.tool_name} → {'✓' if s.success else '✗ ' + (s.error or '')}"
                for s in steps
            ),
            failed_step=error_step.step if error_step else None,
            capability=capability,
        )
    else:
        learning_id = None

    # Record attempt
    engine.record_attempt(
        capability=capability,
        success=scorecard.overall >= 80,
        failure_reason=", ".join(scorecard.failure_patterns) if scorecard.failed_steps else None,
    )

    return api_response(200, {
        "scenario": scenario_name,
        "capability": capability,
        "trajectory_id": trajectory_id,
        "result": scorecard.to_dict(),
        "learning_id": learning_id,
        "agent_id": AGENT_ID,
    })


CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def api_response(status, body):
    return {
        "statusCode": status,
        "headers": {**CORS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }
