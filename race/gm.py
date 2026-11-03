"""race.gm: Game Master client (stdlib only).

  gm = GM(settings, record_dir=..., replay_dir=None)
  gm.list() / gm.start(cid) / gm.status(cid) / gm.artifact(cid) / gm.download(path) / gm.submit(cid, answers)
  gm.retry(cid) / gm.pair()

Rules built in:
  * One request pacer for the whole machine: a file-locked token bucket in the run dir, shared by the runner, the
    fixer sessions and anything run by hand. Bursts past the server's limit cause a lockout that stalls every lane.
  * A 429 sets a shared lockout (honouring Retry-After) that every process waits out, instead of each one retrying.
  * Deadline-aware: a call that would wait past `deadline` (epoch seconds) raises DeadlineError at once.
  * Timed modes start on the regular pool unless settings.ranked is set, so a solver run by hand can never open a
    ranked clock by accident. start() always reconnects to the current attempt; nothing here restarts one.
  * Every response is recorded (record_dir) and can be replayed offline (replay_dir), which is how fixes get tested
    without touching the server.
  * The bearer token is never printed, logged or recorded.
"""
import fcntl
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config


class GMError(RuntimeError):
    pass


class DeadlineError(GMError):
    pass


def _locked(path, fn):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                st = json.loads(f.read() or "{}")
            except ValueError:
                st = {}
            out, new = fn(st)
            if new is not None:
                f.seek(0)
                f.truncate()
                f.write(json.dumps(new))
            return out
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class GM:
    def __init__(self, settings=None, record_dir=None, replay_dir=None, prio=False):
        self.s = settings or config.load()
        self.record_dir = record_dir
        self.replay_dir = replay_dir
        self.prio = prio                       # spends tokens but never sleeps for pacing (the runner's submits)
        self._token = None if replay_dir else config.token(self.s)
        self._pace_file = os.path.join(self.s.run_dir, ".pace")
        self._lock_file = os.path.join(self.s.run_dir, ".lockout")

    # ------------------------------------------------------------------ pacing and lockout
    def _pace(self, deadline=None):
        rate, cap = self.s.pace_rate, self.s.pace_burst
        if rate <= 0:
            return

        def take(st):
            now = time.time()
            tokens = min(cap, st.get("tokens", cap) + (now - st.get("t", now)) * rate)
            tokens -= 1
            return (0.0 if tokens >= 0 or self.prio else -tokens / rate), {"tokens": tokens, "t": now}

        wait = _locked(self._pace_file, take)
        self._sleep(wait, deadline)

    def _lockout_wait(self, deadline=None):
        until = _locked(self._lock_file, lambda st: (st.get("until", 0), None))
        self._sleep(until - time.time(), deadline)

    def _lockout_set(self, seconds):
        until = time.time() + seconds
        _locked(self._lock_file, lambda st: (None, {"until": max(until, st.get("until", 0))}))

    @staticmethod
    def _sleep(wait, deadline):
        if wait <= 0:
            return
        if deadline and time.time() + wait > deadline:
            raise DeadlineError(f"would wait {wait:.1f}s past the deadline")
        time.sleep(wait)

    # ------------------------------------------------------------------ recording
    def _record(self, op, cid, payload):
        if not self.record_dir or op == "pair":          # pairing responses carry the token: never written
            return
        os.makedirs(self.record_dir, exist_ok=True)
        # the counter lives in the record dir, so every client and process writing there continues the sequence
        # instead of starting over at 1 and overwriting earlier recordings
        seq = _locked(os.path.join(self.record_dir, ".seq"),
                      lambda st: (st.get("n", 0) + 1, {"n": st.get("n", 0) + 1}))
        name = f"{seq:05d}_{op}_{re.sub(r'[^A-Za-z0-9_.-]', '_', cid or '')[:80]}"
        if isinstance(payload, (bytes, bytearray)):
            fname = f"{name}_{hashlib.sha256(payload).hexdigest()[:16]}.bin"
            with open(os.path.join(self.record_dir, fname), "wb") as f:
                f.write(payload)
        else:
            fname = name + ".json"
            with open(os.path.join(self.record_dir, fname), "w") as f:
                json.dump(payload, f, indent=1)
        key = f"{op}:{cid or ''}"                       # replay index: last response per (op, cid)
        _locked(os.path.join(self.record_dir, "index.json"), lambda st: (None, {**st, key: fname}))

    def _replay(self, op, cid):
        try:
            idx = json.load(open(os.path.join(self.replay_dir, "index.json")))
        except (OSError, ValueError):
            raise GMError(f"replay: no index.json in {self.replay_dir}")
        key = f"{op}:{cid or ''}"
        if key not in idx:
            if op == "submit":
                return {"result": "replay", "note": "no recorded submit; offline build only"}
            raise GMError(f"replay: nothing recorded for {key}")
        path = os.path.join(self.replay_dir, idx[key])
        if path.endswith(".bin"):
            return open(path, "rb").read()
        return json.load(open(path))

    # ------------------------------------------------------------------ transport
    def _request(self, method, query=None, body=None, url=None, deadline=None, raw=False, op="", cid=""):
        if self.replay_dir:
            return self._replay(op, cid)
        base = url or self.s.require_gm()
        if query:
            base = base + ("&" if "?" in base else "?") + urllib.parse.urlencode(query)
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        for attempt in range(6):
            self._lockout_wait(deadline)
            self._pace(deadline)
            req = urllib.request.Request(base, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.s.http_timeout_s) as r:
                    payload = r.read()
                    ctype = r.headers.get("Content-Type", "")
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = float(e.headers.get("Retry-After") or 12)
                    self._lockout_set(wait)
                    continue
                if e.code >= 500 and attempt < 3:
                    self._sleep(1.5 * (attempt + 1), deadline)
                    continue
                payload, ctype = e.read(), e.headers.get("Content-Type", "")
                break
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 3:
                    self._sleep(1.0 * (attempt + 1), deadline)
                    continue
                raise GMError(f"{method} failed: {e.__class__.__name__}") from None
        else:
            raise GMError(f"{method} gave up after repeated 429/5xx")
        if raw or "json" not in ctype:
            out = payload
        else:
            try:
                out = json.loads(payload)
            except ValueError:
                out = payload
        self._record(op, cid, out)
        return out

    # ------------------------------------------------------------------ operations
    def cid_mode(self, cid, mode):
        return cid + self.s.mode_suffix.get(mode, "")

    def list(self, **extra):
        return self._request("GET", dict(op="list", **extra), op="list")

    def status(self, cid, deadline=None):
        return self._request("GET", {"op": "status", "challenge": cid}, deadline=deadline, op="status", cid=cid)

    def start(self, cid, timed=False, deadline=None):
        body = {"challenge": cid}
        if timed and self.s.ranked:
            body["run_for_time"] = True
        return self._request("POST", body=body, deadline=deadline, op="start", cid=cid)

    def retry(self, cid, timed=False, deadline=None):
        body = {"op": "retry", "challenge": cid}
        if timed and self.s.ranked:
            body["run_for_time"] = True
        return self._request("POST", body=body, deadline=deadline, op="retry", cid=cid)

    def artifact(self, cid, delivery=None, deadline=None):
        q = {"op": "artifact", "challenge": cid}
        if delivery is not None:
            q["delivery"] = delivery
        return self._request("GET", q, deadline=deadline, op="artifact", cid=cid)

    def download(self, path, cid="", deadline=None):
        """Bytes behind an artifact link. A root-relative path is resolved against the Game Master origin."""
        if self.replay_dir:
            return self._replay("download", cid)
        u = urllib.parse.urljoin(self.s.require_gm(), path)
        return self._request("GET", url=u, deadline=deadline, raw=True, op="download", cid=cid)

    def submit(self, cid, answers, deadline=None):
        r = self._request("POST", body={"challenge": cid, "answers": answers}, deadline=deadline,
                          op="submit", cid=cid)
        if not self.replay_dir:                          # what we sent, next to what the grader said:
            self._record("answers", cid, {"answers": answers, "response": r})   # replays grade against it
        return r

    def pair(self, token_out):
        """Create-only pairing. Writes the token to token_out (mode 600) and returns True; never prints it."""
        r = self._request("POST", {"op": "pair"}, op="pair")
        tok = r.get("token") if isinstance(r, dict) else None
        if not tok:
            return False
        fd = os.open(os.path.expanduser(token_out), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(tok)
        return True


def solved(r):
    """True when a submit/status response says the challenge or mode is done."""
    if not isinstance(r, dict):
        return False
    res = str(r.get("result") or r.get("status") or "")
    return res.upper() == "CORRECT" or res in ("already_solved", "solved")
