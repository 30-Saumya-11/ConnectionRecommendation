"""Tiny web page for the demo (Python standard library only - no Flask/Streamlit needed).
    python blood_app.py web   ->  http://localhost:8000
Virtual clock: every new request advances the clock by 1 minute (so aging is easy to see)."""
import json
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sonetq.cache import SharedSnapshotStore
from . import rules
from .bdb import BloodDB
from .recommender import DonorRecommender
from .scheduler import effective_priority
from .world import CITIES, TODAY

AGING = 0.01
STATE = {"lock": threading.Lock(), "clock": 0, "store": None, "path": None, "latest": 12}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>SonetQ Blood Donor Recommender</title>
<style>body{font-family:system-ui,Arial;margin:24px;max-width:1100px}h1{color:#143769}h2{color:#143769;font-size:18px;margin-top:22px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd;padding:4px 8px;font-size:13px;text-align:left}th{background:#eef4fb}
input,select,button{padding:6px;margin:3px}button{background:#143769;color:#fff;border:0;border-radius:4px;cursor:pointer}
.box{background:#eef4fb;padding:10px 14px;border-radius:6px}.note{color:#666;font-size:12px}</style></head><body>
<h1>Blood Donor Recommender</h1><p class="note">Prototype on SYNTHETIC data - not a medical system.</p>
<h2>1. New blood request</h2><div class="box">
Requester person id <input id="rq" type="number" value="10" style="width:80px">
Blood group <select id="bg"></select> City <select id="ct"></select>
Units <input id="un" type="number" value="2" min="1" style="width:60px">
Priority <select id="pr"><option value="0">0 EMERGENCY</option><option value="1">1 URGENT</option><option value="2" selected>2 ROUTINE</option></select>
<button onclick="addReq()">Submit request</button></div>
<h2>2. Process next request (scheduler picks by priority + aging)</h2>
<button onclick="proc()">Process next</button> <span id="msg" class="note"></span><div id="res"></div>
<h2>Blood stock (available, not expired)</h2><div id="inv"></div>
<h2>Queue and recent requests</h2><div id="reqs"></div><p class="note" id="cache"></p>
<script>
const G=%s, C=%s; const $=id=>document.getElementById(id);
G.forEach(g=>$('bg').add(new Option(g,g))); C.forEach(c=>$('ct').add(new Option(c,c)));
async function api(u,b){const r=await fetch(u,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:{});return r.json()}
function tbl(rows,cols){return '<table><tr>'+cols.map(c=>'<th>'+c+'</th>').join('')+'</tr>'+rows.map(r=>'<tr>'+cols.map(c=>'<td>'+(r[c]??'')+'</td>').join('')+'</tr>').join('')+'</table>'}
async function refresh(){const s=await api('/api/state');
 $('inv').innerHTML=tbl([s.inventory],G); $('reqs').innerHTML=tbl(s.requests,['request_id','requester_id','blood_group','city','units_needed','units_allocated','priority','status']);
 $('cache').textContent='Snapshot cache: hits '+s.cache.hits+', misses '+s.cache.misses+', hit rate '+s.cache.hit_rate.toFixed(2)+' | pending: '+s.pending}
async function addReq(){const r=await api('/api/request',{requester_id:+$('rq').value,blood_group:$('bg').value,city:$('ct').value,units:+$('un').value,priority:+$('pr').value});
 $('msg').textContent=r.error?('Error: '+r.error):('Request '+r.request_id+' queued');refresh()}
async function proc(){const r=await api('/api/process',{});
 if(r.error){$('msg').textContent=r.error;$('res').innerHTML='';refresh();return}
 $('msg').textContent='Processed request '+r.request_id+' -> '+r.status+' (allocated '+r.allocated_now+', shortfall '+r.shortfall+')';
 $('res').innerHTML=r.donors.length?('<p>Shortfall: top donors recommended (ML link prediction):</p>'+tbl(r.donors,['rank','donor_id','name','blood_group','score'])):'<p>Fully served from stock - no donor call needed.</p>';refresh()}
refresh();
</script></body></html>"""


def _db():
    return BloodDB("sqlite", STATE["path"])


def _json(h, obj, code=200):
    data = json.dumps(obj).encode()
    h.send_response(code)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/":
            html = (PAGE % (json.dumps(list(rules.GROUPS)), json.dumps(CITIES))).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html))); self.end_headers(); self.wfile.write(html)
        elif self.path == "/api/state":
            db = _db()
            keys = ("request_id", "requester_id", "blood_group", "city", "units_needed", "units_allocated", "priority", "status")
            rows = db._run("SELECT request_id, requester_id, blood_group, city, units_needed, units_allocated, priority, status "
                           "FROM requests ORDER BY request_id DESC LIMIT 15")
            pend = db._run("SELECT COUNT(*) FROM requests WHERE status='PENDING'")[0][0]
            st = STATE["store"]
            out = {"inventory": db.inventory_summary(TODAY), "requests": [dict(zip(keys, r)) for r in rows], "pending": pend,
                   "cache": {"hits": st.hits, "misses": st.misses, "hit_rate": st.hit_rate}}
            db.close(); _json(self, out)
        else:
            _json(self, {"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        db = _db()
        try:
            if self.path == "/api/request":
                if body["blood_group"] not in rules.GROUPS or body["city"] not in CITIES:
                    return _json(self, {"error": "invalid blood group or city"}, 400)
                with STATE["lock"]:
                    STATE["clock"] += 1
                    now = STATE["clock"]
                rid = db.add_request(body["requester_id"], CITIES.index(body["city"]) + 1, body["blood_group"],
                                     body["city"], body["units"], body["priority"], now)
                _json(self, {"request_id": rid})
            elif self.path == "/api/process":
                with STATE["lock"]:
                    now = STATE["clock"]
                    pend = db.pending_requests()
                    if not pend:
                        return _json(self, {"error": "no pending requests"})
                    rid, pr, _ = min(pend, key=lambda r: (effective_priority(r[1], now - r[2], AGING), r[2], r[0]))
                out = db.allocate_units(rid, TODAY)                     # atomic transaction
                donors = []
                if out["shortfall"] > 0:
                    req = db.get_request(rid)
                    cands = db.eligible_donors(req["blood_group"], req["city"], TODAY, exclude_id=req["requester_id"])
                    rec = DonorRecommender(STATE["store"], STATE["latest"], 0.5, 9)
                    ranked = rec.rank(req["requester_id"], cands, 10, "recency")
                    db.save_notifications(rid, ranked, "recency")
                    for i, (d, sc) in enumerate(ranked):
                        p = db._run(f"SELECT name, blood_group FROM persons WHERE person_id={db.ph}", (d,))[0]
                        donors.append({"rank": i + 1, "donor_id": d, "name": p[0], "blood_group": p[1], "score": round(sc, 4)})
                _json(self, {**out, "donors": donors})
            else:
                _json(self, {"error": "not found"}, 404)
        except Exception as e:                                          # show a clean error in the page
            _json(self, {"error": f"{type(e).__name__}: {e}"}, 400)
        finally:
            db.close()


def serve(port=8000, db_path="results/blood/blood_web.db"):
    """Always starts with a FRESH demo database (full stock, empty queue)."""
    import blood_app
    from .world import build_world
    blood_app.make_db(build_world(), db_path, with_future_requests=False)
    STATE["path"] = db_path
    db = _db()
    STATE["latest"] = db._run("SELECT MAX(snapshot_id) FROM snapshots")[0][0]
    STATE["clock"] = db._run("SELECT COALESCE(MAX(created_at),0) FROM requests")[0][0]
    db.close()
    STATE["store"] = SharedSnapshotStore(lambda: _db(), capacity=9, policy="LRU")
    print(f"Open http://localhost:{port}   (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
