"""Vercel Function: POST /api/eval — Self-eval gate."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from samsara_loop.core import LoopEngine

AGENT_ID = os.environ.get("SAMSARA_AGENT_ID", "vercel-agent")
DB_PATH = os.environ.get("SAMSARA_DB", "/tmp/samsara_loop_vercel.db")
os.environ["SAMSARA_DB"] = DB_PATH


def handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS, "body": ""}

    try:
        body = json.loads(event.get("body", "{}"))
    except Exception:
        return api_response(400, {"error": "invalid JSON body"})

    capability = body.get("capability")
    if not capability:
        return api_response(400, {"error": "capability is required"})

    engine = LoopEngine(AGENT_ID)
    result = engine.run_self_eval(capability)
    return api_response(200, result)


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
