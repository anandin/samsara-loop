"""
Samsara Loop Demo App — Full Stack in One File.

Demonstrates the complete self-improving agent loop:
  1. Agent attempts a task
  2. TrajectoryScorer scores the attempt
  3. LoopEngine logs the learning
  4. Self-eval gate decides next action

Run:
  SAMSARA_DB=/tmp/samsara_demo.db python demo_app.py
  Then open http://localhost:8080/
"""

import os
import uuid
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from samsara_loop.core import LoopEngine
from samsara_loop.trajectory_scorer import TrajectoryScorer, StepRecord

app = Flask(__name__)

# Shared instances — in real use these are injected
DEMO_AGENT_ID = os.environ.get("SAMSARA_AGENT_ID", "demo-agent")
DEMO_DB = os.environ.get("SAMSARA_DB", "/tmp/samsara_demo.db")
os.environ["SAMSARA_DB"] = DEMO_DB

scorer = TrajectoryScorer()
engine = LoopEngine(DEMO_AGENT_ID)


# ─── Simulated task executor ────────────────────────────────────────────────

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


@app.route("/")
def dashboard():
    """Full HTML demo dashboard."""
    profile = engine.get_profile()
    pending = engine.get_pending_tests()
    learnings = engine.get_recent_learnings(limit=20)

    pass_rate = profile.get("eval_suite_pass_rate", 0)
    pr_str = f"{pass_rate:.0%}" if pass_rate else "N/A"
    pr_color = "#22c55e" if pass_rate >= 0.85 else "#f59e0b" if pass_rate >= 0.6 else "#ef4444" if pass_rate else "#555"

    html = """<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><title>Samsara Loop — Live Demo</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,system-ui,sans-serif;background:#0a0a0f;color:#d0d0d0;min-height:100vh}
.c{max-width:900px;margin:0 auto;padding:32px 20px}
h1{font-size:22px;font-weight:700;color:#fff;margin-bottom:4px}
.sub{font-size:13px;color:#666;margin-bottom:28px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:14px;margin-bottom:28px}
.card{background:#111118;border:1px solid #1e1e2e;border-radius:12px;padding:18px}
h3{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:.07em;margin-bottom:8px}
.big{font-size:38px;font-weight:800;line-height:1}
.lbl{font-size:11px;color:#555;margin-top:5px}
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border:none;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;transition:opacity:.2s}
.btn:hover{opacity:.8}
.green{background:#22c55e;color:#000}
.red{background:#1a0808;color:#ef4444;border:1px solid #7f1d1d}
.blue{background:#0a1a2a;color:#38bdf8;border:1px solid #1e3a5f}
.purple{background:#1a0a2a;color:#c084fc;border:1px solid #5b21b6}
.card-row{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
.section{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:.06em;margin:22px 0 10px}
.demo-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px}
.score-card{background:#111118;border:1px solid #1e1e2e;border-radius:10px;padding:16px}
.dim{font-size:11px;color:#555;margin-bottom:4px}
.dim-val{font-size:22px;font-weight:700;color:#fff;margin-bottom:8px}
.dim-bar{height:4px;background:#1e1e2e;border-radius:2px}
.dim-fill{height:4px;border-radius:2px;transition:width .3s}
.tag{display:inline-block;font-size:10px;padding:2px 8px;border-radius:3px;text-transform:uppercase;font-weight:600}
.te{background:#1a0808;color:#ef4444}.tc{background:#0a0a1a;color:#818cf8}
.tb{background:#081808;color:#22c55e}.tg{background:#1a1408;color:#f59e0b}
.listing{background:#111118;border:1px solid #1e1e2e;border-radius:8px;padding:12px;margin-bottom:8px}
.listing .cap{font-weight:600;font-size:13px;color:#fff;margin-bottom:4px}
.listing .meta{font-size:11px;color:#555}
.listing .content{font-size:12px;color:#aaa;margin-top:5px}
.empty{color:#333;font-size:13px;padding:16px}
.run-row{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.result-card{background:#111118;border:1px solid #1e1e2e;border-radius:10px;padding:16px;margin-bottom:10px}
.rec-badge{display:inline-block;font-size:11px;padding:3px 10px;border-radius:999px;font-weight:700}
.rec-proceed{background:#0a2a10;color:#22c55e;border:1px solid #16a34a}
.rec-caution{background:#1a1408;color:#f59e0b;border:1px solid #92670a}
.rec-decline{background:#2a0a0a;color:#ef4444;border:1px solid #7f1d1d}
.score-summary{font-size:28px;font-weight:800;margin:8px 0}
.patterns{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.pattern-tag{font-size:10px;padding:2px 8px;border-radius:4px;background:#1e1e2e;color:#888}
</style></head><body>
<div class="c">
<h1>⚡ Samsara Loop — Live Demo</h1>
<div class="sub">Trajectory Scoring Engine + Feedback Loop · """ + DEMO_AGENT_ID + """</div>
"""

    # Stat cards
    total_tests = profile.get("test_suite", {}).get("total", 0)
    pending_count = len(pending)
    strong = profile.get("strong_capabilities", [])
    weak = profile.get("weak_capabilities", [])

    html += f"""<div class="grid">
  <div class="card"><h3>Eval Pass Rate</h3><div class="big" style="color:{pr_color}">{pr_str}</div><div class="lbl">{total_tests} total tests</div></div>
  <div class="card"><h3>Total Learnings</h3><div class="big">{profile.get("total_learnings", 0)}</div><div class="lbl">captured</div></div>
  <div class="card"><h3>Pending Tests</h3><div class="big" style="color:#f59e0b">{pending_count}</div><div class="lbl">awaiting review</div></div>
  <div class="card"><h3>Capabilities</h3><div class="big" style="color:#22c55e">{len(strong)}</div><div class="lbl">{len(weak)} need work</div></div>
</div>
"""

    # Quick-run section
    html += """<div class="section">⚡ Try It — Run a Scenario</div>
<div class="demo-grid">
  <button class="btn green" onclick="runScenario('refund')">✅ Run: Refund Success</button>
  <button class="btn red" onclick="runScenario('refund_fail')">❌ Run: Refund Failure</button>
  <button class="btn green" onclick="runScenario('code')">✅ Run: Code Generation</button>
  <button class="btn red" onclick="runScenario('code_fail')">❌ Run: Code Timeout</button>
</div>
<div id="run-results"></div>
"""

    # Score explanation
    html += """
<div class="section">📊 Scoring Dimensions</div>
<div class="demo-grid">
  <div class="score-card"><div class="dim">Quality — 30%</div><div class="dim-val">Did the right steps succeed?</div>
    <div class="dim-bar"><div class="dim-fill" style="width:100%;background:#22c55e"></div></div></div>
  <div class="score-card"><div class="dim">Efficiency — 20%</div><div class="dim-val">Minimum steps + time?</div>
    <div class="dim-bar"><div class="dim-fill" style="width:80%;background:#38bdf8"></div></div></div>
  <div class="score-card"><div class="dim">Recovery — 20%</div><div class="dim-val">Did agent recover after failure?</div>
    <div class="dim-bar"><div class="dim-fill" style="width:75%;background:#c084fc"></div></div></div>
  <div class="score-card"><div class="dim">Tool Use — 15%</div><div class="dim-val">Right tools for the job?</div>
    <div class="dim-bar"><div class="dim-fill" style="width:85%;background:#f59e0b"></div></div></div>
  <div class="score-card"><div class="dim">Safety — 15%</div><div class="dim-val">No catastrophic failures?</div>
    <div class="dim-bar"><div class="dim-fill" style="width:95%;background:#22c55e"></div></div></div>
  <div class="score-card"><div class="dim">Overall — 100</div><div class="dim-val">Weighted composite score</div>
    <div class="dim-bar"><div class="dim-fill" style="width:88%;background:#22c55e"></div></div></div>
</div>
"""

    # Recent learnings
    if learnings:
        html += "<div class='section'>🧠 Recent Learnings</div>"
        for l in learnings[:8]:
            cat = l.get("category", "")
            tc = "te" if cat == "error" else "tc" if cat == "correction" else "tb" if cat == "best_practice" else "tg"
            content = str(l.get("content", ""))[:120].replace("<", "&lt;")
            ctx = str(l.get("context", ""))[:60]
            created = str(l.get("created_at", ""))[:16]
            html += f"""<div class="listing">
  <div><span class="tag {tc}">{cat}</span> <span class="meta">{created}</span></div>
  <div class="content">{content}</div>
  <div class="meta">{ctx}</div>
</div>"""
    else:
        html += "<div class='section'>🧠 Recent Learnings</div><div class='empty'>No learnings yet — run a scenario above to start</div>"

    html += """
<div class="section">⏳ Pending Tests</div>"""
    if pending:
        for t in pending[:5]:
            html += f"""<div class="listing">
  <div class="cap">{t.get("capability","")}</div>
  <div class="meta">{str(t.get("input_description",""))[:100]}</div>
  <div class="run-row">
    <button class="btn green" onclick="approveTest('{tid}')">✅ Approve</button>
  </div>
</div>""".format(tid=t.get("id", ""))
    else:
        html += "<div class='empty'>No pending tests</div>"

    html += """
</div>
<script>
async function runScenario(name) {
  const res = document.getElementById('run-results');
  res.innerHTML = '<div style="color:#888;padding:12px">⏳ Running ' + name + '...</div>';
  try {
    const r = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({scenario: name})
    });
    const d = await r.json();
    const rec = d.result.recommendation;
    const recClass = rec === 'proceed' ? 'rec-proceed' : rec === 'caution' ? 'rec-caution' : 'rec-decline';
    const overallColor = d.result.overall >= 80 ? '#22c55e' : d.result.overall >= 60 ? '#f59e0b' : '#ef4444';
    const patterns = (d.result.failure_patterns || []).map(p => '<span class="pattern-tag">' + p + '</span>').join('');
    res.innerHTML = `
      <div class="result-card">
        <span class="rec-badge ${recClass}">${rec.toUpperCase()}</span>
        <div class="score-summary" style="color:${overallColor}">${d.result.overall}/100</div>
        <div style="font-size:13px;color:#888;margin-bottom:8px">${d.result.recommendation_reason}</div>
        <div class="patterns">${patterns || '<span class="pattern-tag">no failures</span>'}</div>
        ${d.learning_id ? '<div style="font-size:11px;color:#555;margin-top:8px">📝 Learning logged: ' + d.learning_id + '</div>' : ''}
      </div>`;
  } catch(e) { res.innerHTML = '<div style="color:#ef4444;padding:12px">Error: ' + e.message + '</div>'; }
}
async function approveTest(id) {
  await fetch('/approve', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({test_id: id})});
  location.reload();
}
</script>
</body></html>"""
    return html


@app.route("/api/run", methods=["POST"])
def run_scenario():
    """Run a simulated scenario and score it."""
    scenario_name = request.json.get("scenario")
    scenario = TASK_SCENARIOS.get(scenario_name)

    if not scenario:
        return jsonify({"error": f"Unknown scenario: {scenario_name}"}), 400

    steps = scenario["steps"]
    capability = scenario["capability"]
    trajectory_id = str(uuid.uuid4())[:8]

    # Score the trajectory
    scorecard = scorer.score(trajectory_id, steps, capability)

    # Capture to LoopEngine
    if scorecard.overall < 80:
        # Record as learning
        if scorecard.failed_steps > 0:
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
    else:
        engine.capture_best_practice(
            discovery=f"Successful {capability} execution — {scorecard.summary()}",
            context=f"Scenario: {scenario_name}",
        )
        learning_id = None

    # Record attempt
    engine.record_attempt(
        capability=capability,
        success=scorecard.overall >= 80,
        failure_reason=", ".join(scorecard.failure_patterns) if scorecard.failed_steps else None,
    )

    return jsonify({
        "scenario": scenario_name,
        "capability": capability,
        "trajectory_id": trajectory_id,
        "result": scorecard.to_dict(),
        "learning_id": learning_id,
    })


@app.route("/api/eval", methods=["POST"])
def eval_capability():
    """Self-eval gate — should I attempt this?"""
    capability = request.json.get("capability")
    if not capability:
        return jsonify({"error": "capability required"}), 400
    result = engine.run_self_eval(capability)
    return jsonify(result)


@app.route("/approve", methods=["POST"])
def approve_test():
    tid = request.json.get("test_id")
    if not tid:
        return jsonify({"error": "no test_id"}), 400
    from samsara_loop.db import database as db
    test = db.get_test_case(tid)
    if not test:
        return jsonify({"error": f"test_id '{tid}' not found"}), 404
    engine.approve_test(tid)
    return jsonify({"status": "approved"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"\n⚡ Samsara Loop Demo")
    print(f"   Agent: {DEMO_AGENT_ID}")
    print(f"   DB: {DEMO_DB}")
    print(f"   URL: http://localhost:{port}/\n")
    app.run(host="0.0.0.0", port=port, debug=False)
