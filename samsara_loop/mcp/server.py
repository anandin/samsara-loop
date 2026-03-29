"""
Samsara Loop MCP Server — Model Context Protocol interface.
Any agent that speaks MCP can use the feedback loop.

This is the key extension from the original self-improving-agent:
the agent doesn't need to be OpenClaw-specific. Any MCP-speaking agent
(LangGraph, CrewAI, custom) can plug in and use the feedback loop.

MCP Resources:
- samsara://learnings/{agent_id} — recent learnings
- samsara://tests/{agent_id} — test suite
- samsara://profile/{agent_id} — agent profile

MCP Tools:
- loop_capture_error — log a failure
- loop_capture_correction — log a human correction
- loop_run_self_eval — check readiness for a capability
- loop_get_profile — get agent's learning profile
- loop_approve_test — approve a pending test
- loop_get_pending_tests — get tests awaiting review
"""

import json
from samsara_loop.core import LoopEngine

AGENT_ID = "default"


def handle_tool_call(tool_name: str, arguments: dict) -> str:
    """Route MCP tool calls to the loop engine."""
    engine = LoopEngine(AGENT_ID)

    if tool_name == "loop_capture_error":
        result = engine.capture_error(
            error_message=arguments.get("error_message", ""),
            context=arguments.get("context", ""),
            trajectory_summary=arguments.get("trajectory_summary"),
            failed_step=arguments.get("failed_step"),
            tool_involved=arguments.get("tool_involved"),
            capability=arguments.get("capability"),
        )
        return json.dumps({"learning_id": result})

    elif tool_name == "loop_capture_correction":
        result = engine.capture_correction(
            content=arguments.get("content", ""),
            context=arguments.get("context", ""),
            what_was_wrong=arguments.get("what_was_wrong", ""),
            capability=arguments.get("capability"),
        )
        return json.dumps({"learning_id": result})

    elif tool_name == "loop_capture_best_practice":
        result = engine.capture_best_practice(
            discovery=arguments.get("discovery", ""),
            context=arguments.get("context", ""),
            pattern_key=arguments.get("pattern_key"),
        )
        return json.dumps({"learning_id": result})

    elif tool_name == "loop_run_self_eval":
        result = engine.run_self_eval(arguments.get("capability", "general_task"))
        return json.dumps(result)

    elif tool_name == "loop_get_profile":
        result = engine.get_profile()
        return json.dumps(result)

    elif tool_name == "loop_approve_test":
        engine.approve_test(arguments.get("test_case_id", ""))
        return json.dumps({"status": "approved"})

    elif tool_name == "loop_get_pending_tests":
        tests = engine.get_pending_tests()
        return json.dumps({"pending_tests": tests})

    elif tool_name == "loop_get_dashboard":
        result = engine.get_dashboard_summary()
        return json.dumps(result)

    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})


# MCP manifest
MANIFEST = {
    "name": "Samsara Loop",
    "version": "0.1.0",
    "description": "Agent feedback loop — capture failures, generate tests, self-evaluate",
    "resources": [
        {"uri": "samsara://profile/{agent_id}", "type": "AgentProfile"},
        {"uri": "samsara://learnings/{agent_id}", "type": "Learning[]"},
        {"uri": "samsara://tests/{agent_id}", "type": "TestCase[]"},
    ],
    "tools": [
        {
            "name": "loop_capture_error",
            "description": "Agent logs a failure or error. Generates a test case if step-level.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "error_message": {"type": "string"},
                    "context": {"type": "string"},
                    "trajectory_summary": {"type": "string"},
                    "failed_step": {"type": "integer"},
                    "tool_involved": {"type": "string"},
                    "capability": {"type": "string"},
                },
            },
        },
        {
            "name": "loop_capture_correction",
            "description": "Agent logs a human correction.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "context": {"type": "string"},
                    "what_was_wrong": {"type": "string"},
                    "capability": {"type": "string"},
                },
            },
        },
        {
            "name": "loop_run_self_eval",
            "description": "Agent checks its own readiness for a capability before attempting a task.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "capability": {"type": "string"},
                },
            },
        },
        {
            "name": "loop_get_profile",
            "description": "Get the agent's learning profile.",
        },
        {
            "name": "loop_approve_test",
            "description": "Approve a pending test case.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "test_case_id": {"type": "string"},
                },
            },
        },
        {
            "name": "loop_get_pending_tests",
            "description": "Get test cases awaiting review.",
        },
        {
            "name": "loop_get_dashboard",
            "description": "Get full dashboard summary.",
        },
    ],
}
