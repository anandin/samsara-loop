"""
Samsara Loop CLI — Command-line interface.
Usage:
    samsara-loop capture --error "message" --context "what was happening"
    samsara-loop profile --agent agent-1
    samsara-loop tests --agent agent-1 --pending
    samsara-loop dashboard --port 8080
    samsara-loop eval --agent agent-1 --capability refund_processing
"""

import argparse
import json
import sys
from samsara_loop.core import LoopEngine
from samsara_loop.db import database as db


def main():
    parser = argparse.ArgumentParser(prog="samsara-loop", description="Samsara Loop CLI")
    sub = parser.add_subparsers(dest="command")

    # capture error
    cap = sub.add_parser("capture", help="Capture a learning")
    cap.add_argument("--agent", default="default", help="Agent ID")
    cap.add_argument("--type", default="error", choices=["error", "correction", "best", "gap"])
    cap.add_argument("--content", required=True)
    cap.add_argument("--context", default="")
    cap.add_argument("--trajectory", help="Step-by-step trajectory")
    cap.add_argument("--failed-step", type=int, help="Which step failed")
    cap.add_argument("--tool", help="Tool involved in failure")
    cap.add_argument("--capability", help="Capability domain")
    cap.add_argument("--what-was-wrong", dest="wrong", help="For corrections: what was wrong")

    # profile
    prof = sub.add_parser("profile", help="Show agent profile")
    prof.add_argument("--agent", default="default")
    prof.add_argument("--json", dest="as_json", action="store_true")

    # tests
    tests = sub.add_parser("tests", help="Show test suite")
    tests.add_argument("--agent", default="default")
    tests.add_argument("--pending", action="store_true")
    tests.add_argument("--json", dest="as_json", action="store_true")

    # dashboard
    dash = sub.add_parser("dashboard", help="Start web dashboard")
    dash.add_argument("--agent", default="default")
    dash.add_argument("--port", type=int, default=8080)

    # eval
    ev = sub.add_parser("eval", help="Run self-eval for a capability")
    ev.add_argument("--agent", default="default")
    ev.add_argument("--capability", required=True)
    ev.add_argument("--json", dest="as_json", action="store_true")

    # approve
    appr = sub.add_parser("approve", help="Approve a test case")
    appr.add_argument("--test-id", required=True)
    appr.add_argument("--agent", default="default")

    args = parser.parse_args()
    engine = LoopEngine(args.agent)

    if args.command == "capture":
        if args.type == "error":
            lid = engine.capture_error(
                error_message=args.content,
                context=args.context,
                trajectory_summary=args.trajectory,
                failed_step=args.failed_step,
                tool_involved=args.tool,
                capability=args.capability,
            )
            print(f"Learning logged: {lid}")
            if args.failed_step is not None:
                tests = engine.get_pending_tests()
                if tests:
                    print(f"Test case generated: {tests[-1]['id']}")

        elif args.type == "correction":
            lid = engine.capture_correction(
                content=args.content,
                context=args.context,
                what_was_wrong=args.wrong or "",
                capability=args.capability,
            )
            print(f"Correction logged: {lid}")

        elif args.type == "best":
            lid = engine.capture_best_practice(
                discovery=args.content,
                context=args.context,
            )
            print(f"Best practice logged: {lid}")

        elif args.type == "gap":
            lid = engine.capture_knowledge_gap(
                what_was_missing=args.content,
                context=args.context,
            )
            print(f"Knowledge gap logged: {lid}")

    elif args.command == "profile":
        profile = engine.get_profile()
        if args.as_json:
            print(json.dumps(profile, indent=2))
        else:
            print(f"\n=== {profile['agent_id']} Profile ===")
            print(f"Total learnings: {profile['total_learnings']}")
            print(f"Eval suite: {profile['eval_suite_pass_rate']:.0%} pass rate")
            print(f"Test suite: {profile['test_suite']['passing']}/{profile['test_suite']['total']} passing")
            if profile['strong_capabilities']:
                print(f"Strong: {', '.join(profile['strong_capabilities'])}")
            if profile['weak_capabilities']:
                print(f"Needs work: {', '.join(profile['weak_capabilities'])}")

    elif args.command == "tests":
        tests = engine.get_pending_tests() if args.pending else engine.get_pending_tests()
        all_tests = db.get_test_cases(args.agent)
        if args.as_json:
            print(json.dumps(all_tests, indent=2))
        else:
            print(f"\n=== Test Suite ({len(all_tests)} total) ===")
            pending = [t for t in all_tests if t.get("status") == "pending"]
            print(f"Pending review: {len(pending)}")
            for t in all_tests[:20]:
                status_icon = {"pending": "⏳", "approved": "✅", "passing": "✅", "failing": "❌"}.get(t.get("status", ""), "?")
                print(f"  {status_icon} [{t.get('capability')}] {t.get('input_description','')[:60]}")

    elif args.command == "eval":
        result = engine.run_self_eval(args.capability)
        if args.as_json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\n=== Self-Eval: {args.capability} ===")
            print(f"Can attempt: {result['can_attempt']}")
            print(f"Pass rate: {result['pass_rate']:.0%}" if result['pass_rate'] else "No test data")
            print(f"Tests: {result['test_count']}")
            for rec in result['recommendations']:
                print(f"  → {rec}")

    elif args.command == "dashboard":
        print(f"Dashboard starting on port {args.port}...")
        from samsara_loop.web.app import app
        app.run(host="0.0.0.0", port=args.port)

    elif args.command == "approve":
        engine.approve_test(args.test_id)
        print(f"Test approved: {args.test_id}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
