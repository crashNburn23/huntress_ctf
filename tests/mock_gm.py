#!/usr/bin/env python3
"""Toy Game Master for offline tests and rehearsals. Implements the operations race.gm uses with made-up
challenges: each artifact is a ZIP holding numbers.txt, and the questions ask for the sum, count and max of those
numbers. Lanes listed in hard_lanes also ask for the product mod 97, which the example solver cannot answer, so
that key escalates to a fixer.

  python3 -I tests/mock_gm.py --port 8765 [--unlock-in 5] [--hard bin,web] [--rate-limit 0] [--day 1]

In-process:  srv = serve(port=0, unlock_in=0, hard_lanes={"bin"}); srv.url ... srv.shutdown()
"""
import argparse
import hashlib
import io
import json
import random
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MODES = {"single": "", "time_trial": "/time_trial", "mastery": "/mastery"}


def _numbers(seed):
    r = random.Random(seed)
    return [r.randint(1, 999) for _ in range(r.randint(5, 12))]


def _zip(nums):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("numbers.txt", "\n".join(map(str, nums)) + "\n")
    return b.getvalue()


class World:
    def __init__(self, lanes, day, unlock_in, hard_lanes, rate_limit, token):
        self.lanes, self.day, self.hard = lanes, day, set(hard_lanes)
        self.t_unlock = time.time() + unlock_in
        self.rate_limit, self.token = rate_limit, token
        self.calls, self.lock = 0, threading.Lock()
        self.attempts, self.solved, self.downloads = {}, set(), {}
        self.submits = []

    def cid(self, lane):
        return f"toy-{lane}-{self.day:02d}"

    def challenges(self):
        if time.time() < self.t_unlock:
            return []
        return [{"challenge": self.cid(l), "lane": l, "day": self.day, "modes": list(MODES)} for l in self.lanes]

    def attempt(self, cidm, timed):
        with self.lock:
            if cidm not in self.attempts:                     # start reconnects: same attempt every time
                base, mode = cidm, "single"
                for m, suf in MODES.items():
                    if suf and cidm.endswith(suf):
                        base, mode = cidm[: -len(suf)], m
                lane = base.split("-")[1]
                sets = 3 if mode == "mastery" else 1
                nums = [_numbers(hash((cidm, k)) & 0xFFFF) for k in range(sets)]
                qs = []
                for k in range(sets):
                    pre = f"set{k + 1}." if mode == "mastery" else ""
                    for f in ("sum", "count", "max") + (("product_mod_97",) if lane in self.hard else ()):
                        qs.append({"id": f"{pre}{lane}-{f}", "question": f"In delivery {k + 1}: what is the "
                                   f"{f.replace('_', ' ')} of the numbers in numbers.txt?",
                                   "answer_format": {"kind": "integer"}})
                arts = []
                for k, n in enumerate(nums):
                    data = _zip(n)
                    cap = hashlib.sha256(f"{cidm}{k}".encode()).hexdigest()[:24]
                    self.downloads[cap] = data
                    arts.append({"filename": f"delivery-{k + 1}.zip", "download": f"/download/{cap}",
                                 "sha256": hashlib.sha256(data).hexdigest()})
                self.attempts[cidm] = {"attempt_id": cap, "questions": qs, "artifacts": arts, "nums": nums,
                                       "deadline": time.time() + 120 if timed else None, "mode": mode}
            return self.attempts[cidm]

    def grade(self, cidm, answers):
        a = self.attempts.get(cidm)
        if not a:
            return {"error": "no attempt; start first"}, 400
        want = {}
        for q in a["questions"]:
            k = int(q["id"].split(".")[0][3:]) - 1 if q["id"].startswith("set") else 0
            n, f = a["nums"][k], q["id"].rsplit("-", 1)[1]
            prod = 1
            for x in n:
                prod = prod * x % 97
            want[q["id"]] = str({"sum": sum(n), "count": len(n), "max": max(n), "product_mod_97": prod}[f])
        self.submits.append((cidm, dict(answers)))
        if all(str(answers.get(k, "")).strip() == v for k, v in want.items()):
            self.solved.add(cidm)
            return {"result": "CORRECT", "flag": "toy{%s}" % hashlib.md5(cidm.encode()).hexdigest()[:8]}, 200
        return {"result": "incorrect"}, 200


class Handler(BaseHTTPRequestHandler):
    world = None

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/zip" if raw is not None else "application/json")
        if code == 429:
            self.send_header("Retry-After", "1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _gate(self):
        w = self.world
        with w.lock:
            w.calls += 1
            n = w.calls
        if w.rate_limit and n % w.rate_limit == 0:
            self._send({"error": "rate limited"}, 429)
            return False
        if w.token and self.headers.get("Authorization") != "Bearer " + w.token:
            self._send({"error": "unauthorized"}, 401)
            return False
        return True

    def do_GET(self):
        if not self._gate():
            return
        u = urlparse(self.path)
        if u.path.startswith("/download/"):
            data = self.world.downloads.get(u.path.rsplit("/", 1)[1])
            return self._send(None, 200 if data else 404, raw=data or b"")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        op, cid = q.get("op"), q.get("challenge", "")
        if op == "list":
            return self._send({"challenges": self.world.challenges()})
        a = self.world.attempts.get(cid)
        if op == "status":
            return self._send({"challenge": cid, "solved": cid in self.world.solved,
                               "deadline": a and a["deadline"]})
        if op == "artifact":
            if not a:
                return self._send({"error": "start first"}, 400)
            return self._send({"artifacts": [{k: v for k, v in x.items()} for x in a["artifacts"]]})
        return self._send({"error": "unknown op"}, 400)

    def do_POST(self):
        if not self._gate():
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if q.get("op") == "pair":
            return self._send({"token": "paired-test-token"})
        cid = body.get("challenge", "")
        if "answers" in body:
            r, code = self.world.grade(cid, body["answers"])
            return self._send(r, code)
        if body.get("op") in (None, "retry"):
            if body.get("op") == "retry":
                self.world.attempts.pop(cid, None)
            a = self.world.attempt(cid, bool(body.get("run_for_time")))
            return self._send({"challenge": cid, "attempt_id": a["attempt_id"], "questions": a["questions"],
                               "artifacts": a["artifacts"], "deadline": a["deadline"],
                               "answer_ids": [x["id"] for x in a["questions"]]})
        return self._send({"error": "unknown op"}, 400)


def serve(port=0, lanes=("warm", "meta", "script", "mobile", "bin", "web"), day=1, unlock_in=0.0,
          hard_lanes=(), rate_limit=0, token=None):
    world = World(list(lanes), day, unlock_in, hard_lanes, rate_limit, token)
    handler = type("H", (Handler,), {"world": world})
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    srv.world = world
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    stop = srv.shutdown

    def shutdown():
        stop()
        srv.server_close()
    srv.shutdown = shutdown
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Toy Game Master for offline rehearsals.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--day", type=int, default=1)
    ap.add_argument("--unlock-in", type=float, default=0.0)
    ap.add_argument("--hard", default="bin", help="comma-separated lanes that get one unsolvable key")
    ap.add_argument("--rate-limit", type=int, default=0, help="answer every Nth call with 429")
    ap.add_argument("--lanes", default="warm,meta,script,mobile,bin,web")
    a = ap.parse_args()
    s = serve(a.port, a.lanes.split(","), a.day, a.unlock_in, [x for x in a.hard.split(",") if x], a.rate_limit)
    print("mock Game Master at", s.url, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        s.shutdown()
