"""
Vercel Python app — serves both the dashboard and all API routes.
Vercel detects this as a Flask app via the 'app' variable.
See: https://vercel.com/docs/frameworks/backend/flask
"""
import os, sys

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, jsonify, request, send_file, Response
from samsara_loop.core import LoopEngine
from samsara_loop.trajectory_scorer import TrajectoryScorer, StepRecord
import uuid


AGENT_ID = os.environ.get("SAMSARA_AGENT_ID", "vercel-agent")
DB_PATH = os.environ.get("SAMSARA_DB", "/tmp/samsara_loop_vercel.db")
os.environ["SAMSARA_DB"] = DB_PATH

scorer = TrajectoryScorer()

TASK_SCENARIOS = {
    "refund": {
        "capability": "refund_processing",
        "steps": [
            StepRecord(step=1, tool_name="read", success=True, latency_ms=80, input_summary="Read customer order"),
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

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)


# ── CORS helper ──────────────────────────────────────────────────────────────

def cors_json(data, status=200):
    return jsonify(data), status, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/profile", methods=["GET", "OPTIONS"])
def api_profile():
    if request.method == "OPTIONS":
        return "", 200, {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    engine = LoopEngine(AGENT_ID)
    profile = engine.get_profile()
    pending = engine.get_pending_tests()
    learnings = engine.get_recent_learnings(limit=20)
    return cors_json({
        "profile": profile,
        "pending_tests": pending[:10],
        "recent_learnings": learnings[:10],
    })


@app.route("/api/run", methods=["POST", "OPTIONS"])
def api_run():
    if request.method == "OPTIONS":
        return "", 200, {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    body = request.get_json(force=True, silent=True) or {}
    scenario_name = body.get("scenario")
    if scenario_name not in TASK_SCENARIOS:
        return cors_json({"error": f"Unknown scenario. Options: {list(TASK_SCENARIOS.keys())}"}, 400)
    scenario = TASK_SCENARIOS[scenario_name]
    steps = scenario["steps"]
    capability = scenario["capability"]
    trajectory_id = str(uuid.uuid4())[:8]
    scorecard = scorer.score(trajectory_id, steps, capability)
    engine = LoopEngine(AGENT_ID)
    if scorecard.overall < 80 and scorecard.failed_steps > 0:
        error_step = next((s for s in reversed(steps) if not s.success), None)
        learning_id = engine.capture_error(
            error_message=error_step.error if error_step else "Task failed",
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
    engine.record_attempt(
        capability=capability,
        success=scorecard.overall >= 80,
        failure_reason=", ".join(scorecard.failure_patterns) if scorecard.failed_steps else None,
    )
    return cors_json({
        "scenario": scenario_name,
        "capability": capability,
        "trajectory_id": trajectory_id,
        "result": scorecard.to_dict(),
        "learning_id": learning_id,
        "agent_id": AGENT_ID,
    })


@app.route("/api/eval", methods=["POST", "OPTIONS"])
def api_eval():
    if request.method == "OPTIONS":
        return "", 200, {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    body = request.get_json(force=True, silent=True) or {}
    capability = body.get("capability")
    if not capability:
        return cors_json({"error": "capability is required"}, 400)
    engine = LoopEngine(AGENT_ID)
    result = engine.run_self_eval(capability)
    return cors_json(result)


@app.route("/api/approve", methods=["POST", "OPTIONS"])
def api_approve():
    if request.method == "OPTIONS":
        return "", 200, {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    body = request.get_json(force=True, silent=True) or {}
    tid = body.get("test_id")
    if not tid:
        return cors_json({"error": "test_id is required"}, 400)
    from samsara_loop.db import database as db
    test = db.get_test_case(tid)
    if not test:
        return cors_json({"error": f"test_id '{tid}' not found"}, 404)
    LoopEngine(AGENT_ID).approve_test(tid)
    return cors_json({"status": "approved"})


# ── Dashboard (static HTML) ──────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Samsara Loop — Live Demo</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0a0a0f; color: #d0d0d0; min-height: 100vh; }
.c { max-width: 900px; margin: 0 auto; padding: 36px 20px; }
header { display: flex; align-items: center; gap: 16px; margin-bottom: 36px; padding-bottom: 24px; border-bottom: 1px solid #1e1e2e; }
h1 { font-size: 24px; font-weight: 700; color: #fff; }
.sub { font-size: 14px; color: #555; margin-top: 4px; }
.badge { display: inline-block; font-size: 11px; padding: 3px 10px; border-radius: 999px; font-weight: 600; margin-top: 6px; margin-right: 6px; }
.bg { background: #0a2a10; color: #22c55e; border: 1px solid #16a34a; }
.bg2 { background: #111118; color: #555; border: 1px solid #222; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 14px; margin-bottom: 28px; }
.card { background: #111118; border: 1px solid #1e1e2e; border-radius: 12px; padding: 18px; }
h3 { font-size: 10px; color: #555; text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 8px; }
.big { font-size: 38px; font-weight: 800; line-height: 1; }
.lbl { font-size: 11px; color: #555; margin-top: 5px; }
.section { font-size: 10px; color: #444; text-transform: uppercase; letter-spacing: 0.07em; margin: 28px 0 12px; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 10px 18px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; }
.btn:hover { opacity: 0.8; }
.bng { background: #22c55e; color: #000; }
.bnr { background: #1a0808; color: #ef4444; border: 1px solid #7f1d1d; }
.bnb { background: #0a1a2a; color: #38bdf8; border: 1px solid #1e3a5f; }
.weights { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-bottom: 4px; }
.wc { background: #111118; border: 1px solid #1e1e2e; border-radius: 6px; padding: 10px 12px; text-align: center; font-size: 11px; color: #666; }
.wc strong { color: #fff; display: block; font-size: 18px; }
.rec-card { background: #111118; border: 1px solid #1e1e2e; border-radius: 12px; padding: 20px; margin-bottom: 14px; }
.rate { display: inline-block; font-size: 11px; padding: 4px 12px; border-radius: 999px; font-weight: 700; margin-bottom: 8px; }
.rp { background: #0a2a10; color: #22c55e; border: 1px solid #16a34a; }
.rc { background: #1a1408; color: #f59e0b; border: 1px solid #92670a; }
.rd { background: #2a0a0a; color: #ef4444; border: 1px solid #7f1d1d; }
.score-big { font-size: 52px; font-weight: 800; line-height: 1; margin: 8px 0; }
.ptags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.ptag { font-size: 10px; padding: 2px 8px; border-radius: 4px; background: #1e1e2e; color: #888; }
.lcard { background: #111118; border: 1px solid #1e1e2e; border-radius: 8px; padding: 14px; margin-bottom: 8px; }
.ltag { display: inline-block; font-size: 10px; padding: 2px 8px; border-radius: 3px; font-weight: 600; text-transform: uppercase; margin-bottom: 6px; }
.te { background: #1a0808; color: #ef4444; }
.tb { background: #081808; color: #22c55e; }
.tc { background: #0a0a1a; color: #818cf8; }
.tg { background: #1a1408; color: #f59e0b; }
.lc { font-size: 13px; color: #aaa; margin-top: 5px; }
.lm { font-size: 11px; color: #444; margin-top: 4px; }
.empty { color: #333; font-size: 13px; padding: 16px 0; }
.loading { color: #555; font-size: 13px; padding: 12px; }
.err { color: #ef4444; font-size: 13px; padding: 12px; }
.ev { background: #111118; border: 1px solid #1e1e2e; border-radius: 10px; padding: 16px; margin-top: 16px; }
.evline { font-size: 12px; color: #888; margin: 4px 0; }
</style>
</head>
<body>
<div class="c">

<header>
  <div style="width:48px;height:48px;background:linear-gradient(135deg,#22c55e,#16a34a);border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:24px;flex-shrink:0;">⚡</div>
  <div>
    <h1>Samsara Loop</h1>
    <div class="sub">Trajectory Scoring Engine + Self-Improving Feedback Loop · Live Demo</div>
    <span class="badge bg">✅ 71/71 Tests Passing</span>
    <span class="badge bg2">Vercel Deploy</span>
  </div>
</header>

<div class="grid" id="stats">
  <div class="card"><h3>Eval Pass Rate</h3><div class="big" id="pr">—</div><div class="lbl" id="prsub">loading...</div></div>
  <div class="card"><h3>Total Learnings</h3><div class="big" id="tl">—</div><div class="lbl">captured</div></div>
  <div class="card"><h3>Pending Tests</h3><div class="big" id="pc" style="color:#f59e0b">—</div><div class="lbl">awaiting review</div></div>
  <div class="card"><h3>Capabilities</h3><div class="big" id="cap" style="color:#22c55e">—</div><div class="lbl">in self-model</div></div>
</div>

<div class="section">⚡ Run a Scenario — Live Scoring</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px;">
  <button class="btn bng" onclick="run('refund')">✅ Refund Success</button>
  <button class="btn bnr" onclick="run('refund_fail')">❌ Refund Failure</button>
  <button class="btn bng" onclick="run('code')">✅ Code Generation</button>
  <button class="btn bnr" onclick="run('code_fail')">❌ Code Timeout</button>
</div>
<div id="results"><div class="loading">Run a scenario above to see the scoring engine in action...</div></div>

<div class="section">📊 How Scoring Works — 5 Dimensions</div>
<div class="weights">
  <div class="wc"><strong>30%</strong>Quality<br><span style="font-size:10px">Did the right steps succeed?</span></div>
  <div class="wc"><strong>20%</strong>Efficiency<br><span style="font-size:10px">Minimum steps + time?</span></div>
  <div class="wc"><strong>20%</strong>Recovery<br><span style="font-size:10px">Did it recover from failure?</span></div>
  <div class="wc"><strong>15%</strong>Tool Use<br><span style="font-size:10px">Right tools for the job?</span></div>
  <div class="wc"><strong>15%</strong>Safety<br><span style="font-size:10px">No catastrophic failures?</span></div>
</div>

<div class="section">🚦 Recommendation Gate</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:16px;">
  <div style="background:#0a2a10;border:1px solid #16a34a;border-radius:8px;padding:14px;text-align:center;">
    <div style="font-size:18px;font-weight:700;color:#22c55e;">PROCEED</div>
    <div style="font-size:11px;color:#555;margin-top:4px">≥65 overall</div>
  </div>
  <div style="background:#1a1408;border:1px solid #92670a;border-radius:8px;padding:14px;text-align:center;">
    <div style="font-size:18px;font-weight:700;color:#f59e0b;">CAUTION</div>
    <div style="font-size:11px;color:#555;margin-top:4px">50–64 overall</div>
  </div>
  <div style="background:#2a0a0a;border:1px solid #7f1d1d;border-radius:8px;padding:14px;text-align:center;">
    <div style="font-size:18px;font-weight:700;color:#ef4444;">DECLINE</div>
    <div style="font-size:11px;color:#555;margin-top:4px">&lt;50 overall</div>
  </div>
</div>

<div class="section">🔍 Self-Eval Gate — Should I Attempt This?</div>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">
  <button class="btn bnb" onclick="eval('refund_processing')">refund_processing</button>
  <button class="btn bnb" onclick="eval('code_generation')">code_generation</button>
  <button class="btn bnb" onclick="eval('email_composition')">email_composition</button>
</div>
<div id="evresult" style="display:none"></div>

<div class="section">🧠 Recent Learnings</div>
<div id="learnings"><div class="loading">Loading...</div></div>

</div>

<script>
async function load() {
  try {
    const r = await fetch('/api/profile');
    const d = await r.json();
    const p = d.profile || {};
    const pr = p.eval_suite_pass_rate || 0;
    document.getElementById('pr').textContent = pr ? (pr*100).toFixed(0)+'%' : 'N/A';
    document.getElementById('pr').style.color = pr>=0.85?'#22c55e':pr>=0.6?'#f59e0b':'#ef4444';
    document.getElementById('prsub').textContent = (p.test_suite||{}).total+' tests';
    document.getElementById('tl').textContent = p.total_learnings || 0;
    document.getElementById('pc').textContent = (d.pending_tests||[]).length;
    document.getElementById('cap').textContent = (p.strong_capabilities||[]).length;
    const lrns = d.recent_learnings||[];
    const el = document.getElementById('learnings');
    if (!lrns.length) { el.innerHTML='<div class="empty">No learnings yet — run a scenario to start</div>'; return; }
    el.innerHTML = lrns.map(l => {
      const c = l.category||'';
      const tc = c==='error'?'te':c==='correction'?'tc':c==='best_practice'?'tb':'tg';
      const content = (l.content||'').replace(/</g,'&lt;').substring(0,140);
      return '<div class="lcard"><span class="ltag '+tc+'">'+c+'</span><div class="lc">'+content+'</div><div class="lm">'+(l.created_at||'').substring(0,16)+'</div></div>';
    }).join('');
  } catch(e) {
    document.getElementById('stats').innerHTML = '<div class="err">⚠ Could not load profile. Refresh in a moment.</div>';
  }
}

async function run(name) {
  const el = document.getElementById('results');
  el.innerHTML = '<div class="loading">⏳ Running '+name+'...</div>';
  try {
    const r = await fetch('/api/run', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({scenario:name}) });
    const d = await r.json();
    if (d.error) { el.innerHTML='<div class="err">Error: '+d.error+'</div>'; return; }
    const s = d.result;
    const rec = s.recommendation;
    const rclass = rec==='proceed'?'rp':rec==='caution'?'rc':'rd';
    const color = s.overall>=80?'#22c55e':s.overall>=60?'#f59e0b':'#ef4444';
    const pt = (s.failure_patterns||[]).map(p=>'<span class="ptag">'+p+'</span>').join('')||'<span class="ptag">no failures</span>';
    el.innerHTML = '<div class="rec-card">'+
      '<span class="rate '+rclass+'">'+rec.toUpperCase()+'</span>'+
      '<div class="score-big" style="color:'+color+'">'+s.overall+'/100</div>'+
      '<div style="font-size:13px;color:#777;margin-bottom:10px">'+s.successful_steps+'/'+s.total_steps+' steps succeeded</div>'+
      '<div style="font-size:13px;color:#888;margin-bottom:10px">'+s.recommendation_reason+'</div>'+
      '<div class="ptags">'+pt+'</div>'+
      (d.learning_id?'<div style="font-size:11px;color:#555;margin-top:10px">📝 Learning: <code style="color:#888">'+d.learning_id+'</code></div>':'')+
      '</div>';
    setTimeout(load, 500);
  } catch(e) { el.innerHTML='<div class="err">⚠ Network error: '+e.message+'</div>'; }
}

async function eval(cap) {
  const el = document.getElementById('evresult');
  el.style.display='block';
  el.innerHTML='<div class="ev"><div style="font-size:13px;color:#888">Evaluating...</div></div>';
  try {
    const r = await fetch('/api/eval', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({capability:cap}) });
    const d = await r.json();
    const can = d.can_attempt;
    el.innerHTML = '<div class="ev">'+
      '<div style="font-size:15px;font-weight:700;color:'+(can?'#22c55e':'#ef4444')+'">'+(can?'✅ PROCEED':'🚫 DECLINE')+'</div>'+
      '<div class="evline">Confidence: <strong style="color:#fff">'+((d.confidence||0)*100).toFixed(0)+'%</strong></div>'+
      '<div class="evline" style="color:#888;font-size:12px;margin-top:6px">'+(d.reason||'')+'</div>'+
      (d.missing_tests?'<div class="evline" style="color:#f59e0b;font-size:12px">⚠ No eval cases yet — first attempt builds baseline</div>':'')+
      '</div>';
  } catch(e) { el.innerHTML='<div class="err">Error: '+e.message+'</div>'; }
}

load();
</script>
</body>
</html>"""


@app.route("/", methods=["GET"])
def dashboard():
    return Response(DASHBOARD_HTML, content_type="text/html")


@app.route("/<path:path>", methods=["GET"])
def fallback(path):
    return Response("Not found: /" + path, status=404)
