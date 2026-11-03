#!/usr/bin/env python3
"""Fail if anything in the tree looks like private or event-specific data. Run before publishing.

  python3 -I tools/scrub_check.py [--deny FILE ...] [--root DIR]

Built-in checks (generic, safe to keep in a public repo):
  * IPv4 addresses other than loopback and documentation ranges
  * http(s) URLs other than placeholders (<...>), localhost/127.0.0.1 and example.* / *.invalid
  * home directory paths and e-mail addresses (LICENSE is exempt for the copyright line)
  * long token-like strings (40+ chars of base64/hex) and private key headers
--deny FILE: extra patterns, one regular expression per line (case-insensitive; # comments). Keep that file
OUTSIDE the repository; it is where event names, challenge ids and field names go, so the check itself never
repeats them.
Exit code 1 when anything matches.
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "__pycache__", "run", ".venv"}
TEXT_EXT = {".py", ".md", ".toml", ".txt", ".json", ".sh", ".cfg", ".ini", ".yml", ".yaml", ".svg", ""}

IPV4 = re.compile(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?![\d.])")
URL = re.compile(r"https?://[^\s'\"<>)]+")
OK_URL = re.compile(r"https?://(localhost|127\.0\.0\.1|(?:[\w-]+\.)*example\.(?:com|org|net)|[\w.-]*\.invalid)"
                    r"([:/]|$)|https?://\{|https?://www\.w3\.org/2000/svg$", re.I)   # SVG namespace
HOME = re.compile(r"/home/[A-Za-z0-9_.-]+|/Users/[A-Za-z0-9_.-]+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/=_-])")
KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


def ip_ok(ip):
    parts = [int(x) for x in ip.split(".")]
    if any(p > 255 for p in parts):
        return True                                   # not an address (version strings etc.)
    return parts[0] == 127 or parts[:3] in ([192, 0, 2], [198, 51, 100], [203, 0, 113]) or parts == [0, 0, 0, 0]


def scan_line(line, rel, deny):
    hits = []
    for m in IPV4.finditer(line):
        if not ip_ok(m.group(1)):
            hits.append(("ipv4", m.group(1)))
    for m in URL.finditer(line):
        if not OK_URL.match(m.group(0)) and "<" not in m.group(0):
            hits.append(("url", m.group(0)))
    if os.path.basename(rel) != "LICENSE":
        hits += [("home path", m.group(0)) for m in HOME.finditer(line)]
        hits += [("email", m.group(0)) for m in EMAIL.finditer(line) if not m.group(0).endswith(".invalid")]
    hits += [("token-like", m.group(0)[:24] + "...") for m in TOKEN.finditer(line)
             if not re.fullmatch(r"[a-z_]+", m.group(0)) and len(re.findall(r"[A-Za-z0-9]", m.group(0))) >= 32]
    hits += [("private key", "header")] if KEY.search(line) else []
    for rx in deny:
        m = rx.search(line)
        if m:
            hits.append(("denylist", m.group(0)))
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deny", action="append", default=[])
    ap.add_argument("--root", default=ROOT)
    a = ap.parse_args()
    deny = []
    for p in a.deny:
        with open(p) as f:
            for raw in f:
                raw = raw.strip()
                if raw and not raw.startswith("#"):
                    deny.append(re.compile(raw, re.I))
    total = 0
    for base, dirs, files in os.walk(a.root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for n in sorted(files):
            p = os.path.join(base, n)
            rel = os.path.relpath(p, a.root)
            if os.path.splitext(n)[1] not in TEXT_EXT:
                print(f"{rel}: binary or unexpected file type (review by hand)")
                total += 1
                continue
            with open(p, errors="replace") as f:
                for i, line in enumerate(f, 1):
                    for kind, what in scan_line(line, rel, deny):
                        print(f"{rel}:{i}: {kind}: {what}")
                        total += 1
            for rx in deny:                           # file names too
                if rx.search(rel):
                    print(f"{rel}: denylist match in the file name")
                    total += 1
    print(f"scrub_check: {total} finding(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
