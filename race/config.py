"""race.config: every knob in one place.

Values come from, highest priority first:
  1. environment variables (RACE_<NAME>, e.g. RACE_GM_URL)
  2. config.toml at the repository root (gitignored; copy config.example.toml)
  3. the defaults below

Nothing event-specific has a default. The Game Master URL must be configured. Without it, anything that talks
to the Game Master stops with a clear message instead of guessing.
"""
import datetime
import os
import sys
import tomllib
from dataclasses import dataclass, field, fields

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.environ.get("RACE_CONFIG") or os.path.join(ROOT, "config.toml")
MODES = ("single", "time_trial", "mastery")


@dataclass
class Settings:
    # Game Master
    gm_url: str = ""                       # base URL, no trailing query; required for live work
    token_file: str = ""                   # bearer token file (chmod 600); empty -> RACE_GM_TOKEN env or no auth
    mode_suffix: dict = field(default_factory=lambda: {"single": "", "time_trial": "/time_trial",
                                                       "mastery": "/mastery"})
    ranked: bool = False                   # timed modes on the ranked clock; off = regular pool (same points)
    pace_rate: float = 3.5                 # requests per second, shared by every process on this machine
    pace_burst: float = 60.0
    http_timeout_s: float = 30.0

    # lanes: name -> weight (how much fixer help the lane usually needs) and how to find its challenges
    lanes: dict = field(default_factory=lambda: {"warm": 1, "meta": 2, "script": 1, "mobile": 1, "bin": 3, "web": 3})
    lane_match: dict = field(default_factory=dict)      # lane -> regex over the challenge id (default: lane name)
    day_pattern: str = r"day-?0*{day}(\D|$)"   # regex over the challenge id when the list has no "day" field
    target_lanes: list = field(default_factory=lambda: ["web"])   # lanes with live targets: straight to a fixer
    lane_solver: dict = field(default_factory=dict)     # lane -> module in race/lanes/ (default: same name, or
                                                        # the generic lane that leaves everything to plugins)
    archive_passwords: list = field(default_factory=list)   # tried in order on encrypted ZIP artifacts
    max_extract_mb: int = 512              # per attempt; artifacts are untrusted

    # schedule (local time, HH:MM:SS)
    arm_at: str = "08:50:00"               # fixer sessions start
    unlock_poll_at: str = "08:59:50"       # runner starts 1 s polls for the new day

    # runner
    park_s: int = 3600                     # how long a failed lane waits for a fix before giving up
    timed_tries: int = 2
    early_escalate_blank: bool = True      # escalate before submitting when the build has blank keys

    # fixer sessions
    session_split: str = "core_target"     # "core_target": one session for every non-target lane, one for the
                                           # target lanes (web); "weight": balance lanes over `sessions` by weight
    sessions: int = 2                      # used by session_split = "weight" only
    steal_after_s: int = 45                # an idle session may take a row left unclaimed this long
    claude_bin: str = "claude"
    claude_mode: str = "auto"
    claude_model: str = ""

    # paths
    run_dir: str = os.path.join(ROOT, "run")
    plugin_dir: str = os.path.join(ROOT, "plugins")

    def day_dir(self, day):
        return os.path.join(self.run_dir, f"day{int(day):02d}")

    def require_gm(self):
        if not self.gm_url:
            sys.exit("race: no Game Master URL configured. Set RACE_GM_URL or gm_url in config.toml "
                     "(see config.example.toml).")
        return self.gm_url


def _coerce(cur, raw):
    """Convert an environment string to the type of the default."""
    if isinstance(cur, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(cur, int):
        return int(raw)
    if isinstance(cur, float):
        return float(raw)
    if isinstance(cur, list):
        return [x.strip() for x in raw.split(",") if x.strip()]
    if isinstance(cur, dict):                 # "a=1,b=2"
        out = {}
        for part in raw.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                v = v.strip()
                out[k.strip()] = int(v) if v.lstrip("-").isdigit() else v
        return out
    return raw


def load(path=None):
    s = Settings()
    path = path or CONFIG_FILE
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = tomllib.load(f)
        known = {f.name for f in fields(Settings)}
        unknown = sorted(set(data) - known)
        if unknown:
            sys.exit(f"race: unknown key(s) in {os.path.basename(path)}: {unknown}")
        for k, v in data.items():
            setattr(s, k, v)
    for f in fields(Settings):
        raw = os.environ.get("RACE_" + f.name.upper())
        if raw is not None:
            setattr(s, f.name, _coerce(getattr(s, f.name), raw))
    if s.sessions < 1:
        sys.exit("race: sessions must be >= 1")
    if s.session_split not in ("core_target", "weight"):
        sys.exit(f"race: session_split must be 'core_target' or 'weight', not {s.session_split!r}")
    bad = [m for m in s.mode_suffix if m not in MODES]
    if bad:
        sys.exit(f"race: unknown mode(s) in mode_suffix: {bad}")
    return s


def token(s):
    """Bearer token from RACE_GM_TOKEN or the token file. Never printed or logged by anything in this repo."""
    t = os.environ.get("RACE_GM_TOKEN")
    if t:
        return t.strip()
    if s.token_file:
        p = os.path.expanduser(s.token_file)
        try:
            if os.stat(p).st_mode & 0o077:
                print("race: warning: token file is readable by others; chmod 600 it", file=sys.stderr)
            with open(p) as f:
                return f.read().strip() or None
        except FileNotFoundError:
            sys.exit(f"race: token_file {s.token_file!r} not found")
    return None


def seconds_until(hhmmss, day=None, now=None):
    """Seconds until HH:MM:SS on the next date whose day of month is `day` (today if day is None or today).
    0 when that moment has passed today. Launching the evening before therefore waits for tomorrow morning."""
    now = now or datetime.datetime.now()
    hh, mm, ss = map(int, hhmmss.split(":"))
    for ahead in range(0, 32):
        d = now + datetime.timedelta(days=ahead)
        if day is None or d.day == int(day):
            at = d.replace(hour=hh, minute=mm, second=ss, microsecond=0)
            return max(0, int((at - now).total_seconds()))
    return 0
