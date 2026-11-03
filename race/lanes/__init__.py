"""race.lanes: the lane interface. A lane knows how to get its artifacts and how to answer its questions.

To add a lane solver, create race/lanes/<name>.py with `LANE_CLASS = MyLane`, where MyLane subclasses Lane and
overrides solve() (and fetch() if the artifacts need special handling). A lane without a module uses Lane itself:
it fetches and unpacks the artifacts and answers nothing, so every answer comes from plugins or a fixer. That is
a valid way to start a lane: the first day's fixes become its plugins.

What plugins and solvers receive is a Members object:
    m.sets           [ {member name: bytes}, ... ]   one dict per delivery (mastery has several)
    m.files          all members of all deliveries
    m.for_qid(qid)   the delivery a question belongs to ("setK." prefix -> delivery K, else the first)
    m.dir            where the members were unpacked (read-only for fixers; never execute anything in it)
"""
import importlib
import io
import os
import re
import zipfile
import zlib

from .. import config, plugins


class Members:
    def __init__(self, root, sets):
        self.dir, self.sets = root, sets

    @property
    def files(self):
        out = {}
        for i, s in enumerate(self.sets):
            for n, b in s.items():
                out[n if n not in out else f"{i + 1}/{n}"] = b
        return out

    def for_qid(self, qid):
        m = re.match(r"set(\d+)\.", qid)
        k = int(m.group(1)) - 1 if m else 0
        return self.sets[k] if k < len(self.sets) else (self.sets[0] if self.sets else {})

    @classmethod
    def from_dir(cls, root):
        sets = []
        dirs = [x for x in os.listdir(root) if re.fullmatch(r"delivery-\d+", x)]
        for d in sorted(dirs, key=lambda x: int(x.split("-")[1])):     # numeric: delivery-10 after delivery-9
            p, s = os.path.join(root, d), {}
            for base, _, names in os.walk(p):
                for n in sorted(names):
                    full = os.path.join(base, n)
                    with open(full, "rb") as f:
                        s[os.path.relpath(full, p)] = f.read()
            sets.append(s)
        return cls(root, sets)


def safe_extract(data, dest, passwords=(), budget=None):
    """Unpack a ZIP without trusting it: no absolute paths, no '..', a total size budget. Returns bytes written."""
    z = zipfile.ZipFile(io.BytesIO(data))
    written, budget = 0, budget if budget is not None else 512 << 20
    for info in z.infolist():
        name = info.filename.replace("\\", "/")
        if info.is_dir() or name.startswith("/") or ".." in name.split("/"):
            continue
        if written + info.file_size > budget:
            raise ValueError("archive larger than the extract budget")
        blob = None
        for pw in [None] + [p.encode() for p in passwords]:
            try:
                blob = z.read(info, pwd=pw)
                break
            except (RuntimeError, zipfile.BadZipFile, zlib.error):   # a wrong ZipCrypto password can pass the
                continue                                              # check byte and fail later on CRC/inflate
        if blob is None:
            continue
        out = os.path.join(dest, name)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(blob)
        written += len(blob)
    return written


class Lane:
    weight = 1
    has_targets = False            # live targets (web-style): the runner hands these straight to a fixer

    def __init__(self, name, s=None):
        self.name = name
        self.s = s or config.load()
        self.weight = self.s.lanes.get(name, self.weight)
        self.has_targets = name in self.s.target_lanes
        pat = self.s.lane_match.get(name)
        self.rx = re.compile(pat if pat else rf"(^|[-_/]){re.escape(name)}([-_/]|$)")

    def match(self, challenge):
        cid = challenge.get("challenge") or challenge.get("id") or ""
        return challenge.get("lane") == self.name or bool(self.rx.search(cid))

    def fetch(self, gm, cid, start, dest):
        """Download every artifact of the attempt into dest/delivery-K/ and unpack ZIPs. -> Members"""
        arts = start.get("artifacts") or []
        if not arts:
            r = gm.artifact(cid)
            arts = r.get("artifacts", []) if isinstance(r, dict) else []
        budget = self.s.max_extract_mb << 20
        for k, a in enumerate(arts, 1):
            d = os.path.join(dest, f"delivery-{k}")
            os.makedirs(d, exist_ok=True)
            data = gm.download(a.get("download") or a.get("url"), cid=f"{cid}#{k}")
            if isinstance(data, (bytes, bytearray)) and data[:2] == b"PK":
                budget -= safe_extract(data, d, self.s.archive_passwords, budget)
            else:
                name = os.path.basename(a.get("filename") or f"artifact-{k}.bin")
                with open(os.path.join(d, name), "wb") as f:
                    f.write(data if isinstance(data, (bytes, bytearray)) else str(data).encode())
        return Members.from_dir(dest)

    def solve(self, questions, members):
        """The lane's own solver. -> {qid: value}. The generic lane answers nothing."""
        return {}

    def build(self, questions, members, log=None):
        """Solver, then plugins (fill blanks; OVERRIDE plugins may replace). -> (answers, provenance)"""
        try:
            base = self.solve(questions, members) or {}
        except Exception as e:                       # a solver bug must not stop plugins or the escalation
            (log or print)(f"{self.name} solver raised {e.__class__.__name__}: {str(e)[:160]}")
            base = {}
        base = {q["id"]: base.get(q["id"], "") for q in questions}
        return plugins.apply(self.name, questions, members, base, self.s, log=log)


def get(name, s=None):
    s = s or config.load()
    mod = s.lane_solver.get(name, name)
    try:
        m = importlib.import_module(f"{__name__}.{mod}")
    except ModuleNotFoundError:
        return Lane(name, s)
    cls = getattr(m, "LANE_CLASS", None)
    return cls(name, s) if cls else Lane(name, s)


def all_lanes(s=None):
    s = s or config.load()
    return [get(n, s) for n in s.lanes]
