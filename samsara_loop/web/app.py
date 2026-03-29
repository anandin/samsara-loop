"""Samsara Loop Web Dashboard"""
from flask import Flask, jsonify, request
from samsara_loop.core import LoopEngine

app = Flask(__name__)
AGENT_ID = "default"

@app.route("/")
def dashboard():
    engine = LoopEngine(AGENT_ID)
    data = engine.get_dashboard_summary()
    p = data["profile"]
    pr = p.get("eval_suite_pass_rate", 0)
    pr_str = f"{pr:.0%}" if pr else "N/A"
    rc = "rh" if pr >= 0.85 else "rm" if pr >= 0.6 else "rl" if pr > 0 else ""
    pending = data.get("pending_tests", [])
    strong = p.get("strong_capabilities", [])
    weak = p.get("weak_capabilities", [])
    learnings = data.get("recent_learnings", [])[:20]
    
    html = '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Samsara Loop</title>'
    html += '<style>'
    css = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,system-ui,sans-serif;background:#0a0a0f;color:#d0d0d0;min-height:100vh}
.c{max-width:1100px;margin:0 auto;padding:24px}
header{display:flex;align-items:center;gap:12px;margin-bottom:28px}
h1{font-size:22px;font-weight:700;color:#fff}
.b{font-size:12px;background:#1a1a2e;padding:4px 10px;border-radius:999px;color:#777}
.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px;margin-bottom:28px}
.card{background:#111118;border:1px solid #1e1e2e;border-radius:10px;padding:18px}
h3{font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
.big{font-size:40px;font-weight:700;color:#fff;line-height:1}
.sub{font-size:12px;color:#555;margin-top:4px}
.rh{color:#22c55e}.rm{color:#f59e0b}.rl{color:#ef4444}
.s{margin:24px 0 10px;font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.05em}
.t{background:#111118;border:1px solid #1e1e2e;border-radius:8px;padding:14px;margin-bottom:8px}
.t .cap{font-weight:600;color:#fff;margin-bottom:4px;font-size:14px}
.t .d{font-size:12px;color:#777;margin-bottom:7px}
.t .trace{font-size:11px;color:#ef4444;background:#130a0a;border-radius:4px;padding:5px 8px;margin-bottom:6px;word-break:break-word}
.t .fix{font-size:11px;color:#22c55e;background:#081408;border-radius:4px;padding:5px 8px;margin-bottom:8px;word-break:break-word}
.btn{display:inline-block;padding:6px 14px;border-radius:6px;font-size:12px;cursor:pointer;border:none}
.bg{background:#22c55e;color:#000}
.l{padding:9px 0;border-bottom:1px solid #1a1a2a}
.l:last-child{border:none}
.tag{font-size:10px;padding:2px 7px;border-radius:3px;text-transform:uppercase;font-weight:600}
.te{background:#1a0808;color:#ef4444}.tc{background:#0a0a1a;color:#818cf8}
.tb{background:#081808;color:#22c55e}.tg{background:#1a1408;color:#f59e0b}
.lc{font-size:13px;color:#bbb;margin:5px 0 3px;word-break:break-word}
.lm{font-size:11px;color:#444}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{font-size:11px;padding:3px 10px;border-radius:999px}
.cg{background:#081808;color:#22c55e}.cr{background:#1a0808;color:#ef4444}
.empty{color:#333;font-size:13px;padding:20px}
"""
    html += css.replace("{","{{").replace("}","}}") + '</style></head><body>'
    html += '<div class="c"><header><h1>Samsara Loop</h1><span class="b">' + AGENT_ID + '</span></header>'
    html += '<div class="g">'
    html += '<div class="card"><h3>Eval Pass Rate</h3><div class="big ' + rc + '">' + pr_str + '</div><div class="sub">' + str(p.get("test_suite",{}).get("total",0)) + ' tests</div></div>'
    html += '<div class="card"><h3>Total Learnings</h3><div class="big">' + str(p.get("total_learnings",0)) + '</div><div class="sub">' + str(data.get("learnings_today",0)) + ' today</div></div>'
    html += '<div class="card"><h3>Pending Tests</h3><div class="big rm">' + str(len(pending)) + '</div><div class="sub">awaiting review</div></div>'
    html += '<div class="card"><h3>Strong Capabilities</h3><div class="big rh">' + str(len(strong)) + '</div><div class="sub">' + str(len(weak)) + ' need work</div></div>'
    html += '</div>'

    if strong:
        chips = "".join('<span class="chip cg">'+c+'</span>' for c in strong)
        html += '<div class="s">Capabilities — Strong</div><div class="card"><div class="chips">'+chips+'</div></div>'
    if weak:
        chips = "".join('<span class="chip cr">'+c+'</span>' for c in weak)
        html += '<div class="s">Capabilities — Needs Work</div><div class="card"><div class="chips">'+chips+'</div></div>'
    if pending:
        tests_html = ""
        for t in pending[:10]:
            tid = t.get("id","")
            cap = t.get("capability","")
            desc = str(t.get("input_description",""))[:120].replace("<","&lt;")
            root = str(t.get("root_cause",""))[:200].replace("<","&lt;")
            fix = str(t.get("fix_suggestion",""))[:200].replace("<","&lt;")
            tests_html += '<div class="t"><div class="cap">'+cap+'</div><div class="d">'+desc+'</div><div class="trace">'+root+'</div><div class="fix">'+fix+'</div><button class="btn bg" onclick="approve(\''+tid+'\')">Approve Test</button></div>'
        html += '<div class="s">Pending Tests — Review Required</div>' + tests_html

    if learnings:
        lhtml = ""
        for l in learnings:
            cat = l.get("category","")
            tc = "te" if cat=="error" else "tc" if cat=="correction" else "tb" if cat=="best_practice" else "tg"
            content = str(l.get("content",""))[:150].replace("<","&lt;")
            ctx = str(l.get("context",""))[:70]
            created = str(l.get("created_at",""))[:16]
            lhtml += '<div class="l"><span class="tag '+tc+'">'+cat+'</span><div class="lc">'+content+'</div><div class="lm">'+created+' · '+ctx+'</div></div>'
        html += '<div class="s">Recent Learnings</div>' + lhtml
    else:
        html += '<div class="s">Recent Learnings</div><div class="empty">No learnings yet</div>'

    html += '</div><script>function approve(id){fetch("/approve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({test_id:id})}).then(r=>r.json()).then(()=>location.reload())}</script></body></html>'
    return html

@app.route("/approve", methods=["POST"])
def approve_test():
    tid = request.json.get("test_id")
    if tid:
        LoopEngine(AGENT_ID).approve_test(tid)
        return jsonify({"status":"approved"})
    return jsonify({"error":"no test_id"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
