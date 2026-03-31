"""Vercel Function: GET /api/profile — Agent profile + learnings."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from samsara_loop.core import LoopEngine

AGENT_ID = os.environ.get("SAMSARA_AGENT_ID", "vercel-agent")
DB_PATH = os.environ.get("SAMSARA_DB", "/tmp/samsara_loop_vercel.db")
os.environ["SAMSARA_DB"] = DB_PATH


def handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS, "body": ""}

    engine = LoopEngine(AGENT_ID)
    profile = engine.get_profile()
    pending = engine.get_pending_tests()
    learnings = engine.get_recent_learnings(limit=20)

    return api_response(200, {
        "profile": profile,
        "pending_tests": pending[:10],
        "recent_learnings": learnings[:10],
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
