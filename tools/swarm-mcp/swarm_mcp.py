#!/usr/bin/env python3
# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: MIT OR GPL-2.0-only
"""swarm-mcp: a local, read-only MCP server over the org's scripts (docs/adr/0002).

Moved from swarm-routing/skills tools/swarm-mcp/swarm_mcp.py as of skills
commit 02e08bad8043a4cf128c7f87ec47faa3850cb8cf (swarm-routing/skills#187, the
file's last change; skills main was d060402560382d232b7b70d004abb3b3cc2272a3),
swarm-routing/skills#185. The one change: it no longer runs the skill
wrappers of that repository but `org-tool` beside it, which finds the same
swarm-routing/.github scripts the same way.

Each tool runs one read-only command of a swarm-routing/.github script through
`org-tool` (ORG_TOOLS_DIR, else a cached snapshot of swarm-routing/.github at
ORG_TOOLS_REF, by default the commit this repository's .github/org-sync.lock
pins) and returns the exit status and the script's summary, trimmed to a size
cap. The server itself opens no connection, reads no token and writes no file;
a script reaches the network only as it does when a person runs it (git, gh, public HTTPS reads).

Transport: JSON-RPC 2.0 over stdio, one message per line. Dual-era: a modern
request (protocol 2026-07-28) carries its version in
`params._meta["io.modelcontextprotocol/protocolVersion"]`; a legacy client
opens with `initialize` (2025-11-25, 2025-06-18, 2025-03-26). One message
is served at a time, in order; a `notifications/cancelled` for the running
tools/call kills it and drops its response (docs/adr/0002, "Protocol").

  python3 -I tools/swarm-mcp/swarm_mcp.py            serve on stdin/stdout
  python3 -I tools/swarm-mcp/swarm_mcp.py --list     print the tools, one per line
  python3 -I tools/swarm-mcp/swarm_mcp.py --self-test

Environment:
  CLAUDE_PROJECT_DIR   the directory relative paths resolve against (else the cwd)
  ORG_TOOLS_DIR        a swarm-routing/.github checkout (org-tool reads it)
  ORG_TOOLS_REF        the branch, tag or commit org-tool fetches otherwise (default: the
                       commit .github/org-sync.lock pins; none there is a tool error)
  SWARM_MCP_TIMEOUT    seconds per tool call (default 300)
  SWARM_MCP_MAX_CHARS  characters of stdout per result (default 6000; stderr gets a quarter)

Stdlib only.
"""

from __future__ import annotations

import collections
import json
import os
import queue
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time

NAME = "swarm-mcp"
VERSION = "0.1.0"  # Commitizen moves it with .cz.toml and CITATION.cff on a release
HERE = os.path.dirname(os.path.abspath(__file__))
ORG_TOOL = os.path.join(HERE, "org-tool")
MODERN = ["2026-07-28"]
LEGACY = ["2025-11-25", "2025-06-18", "2025-03-26"]
SUPPORTED = MODERN + LEGACY
META_VERSION = "io.modelcontextprotocol/protocolVersion"
UNSUPPORTED_VERSION = -32022
CACHE_TTL_MS = 3600000  # the tool list is fixed for a plugin version
INSTRUCTIONS = (
    "Read-only verdicts from the swarm-routing org's scripts: a fidelity sheet's check, row and "
    "locator verification, the golden-rule checks on a diff, a release's readiness and aftercare, "
    "a release lock's state. Each result is the script's own summary; exit 1 means findings."
)


# --- the tools -----------------------------------------------------------------------

SEMVER = r"^v?\d+\.\d+\.\d+$"
TAG = r"^v\d+\.\d+\.\d+$"
REPO = r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$"
REF = r"^[A-Za-z0-9][A-Za-z0-9._/@~^-]*$"
TEXT = r"^[A-Za-z0-9_-]+=.+$"


def _s(desc, pattern=None):
    d = {"type": "string", "description": desc}
    if pattern:
        d["pattern"] = pattern
    return d


def _schema(props, required=()):
    return {
        "type": "object",
        "properties": props,
        "required": list(required),
        "additionalProperties": False,
    }


# org-tool's names for the scripts (its case table)
FIDELITY = "fidelity"
REVIEW = "check-invariants"
RELEASE = "release-check"
LOCK = "release-lock"

# name -> (description, input schema, org-tool script, argv builder); listed in this order
TOOLS = {
    "fidelity_check": (
        "fidelity.py check: a fidelity sheet's shape and Source cells (a reference, a reasoned "
        "repo choice, or unknown), listing the unknowns and repo choices. Exit 1 on a problem.",
        _schema({"file": _s("the sheet, e.g. docs/fidelity.md")}, ["file"]),
        FIDELITY,
        lambda a: ["check", a["file"]],
    ),
    "fidelity_row": (
        "fidelity.py row: the sheet's one-line summary row (the review table's shape).",
        _schema(
            {
                "file": _s("the sheet, e.g. docs/fidelity.md"),
                "protocol": _s("the protocol's name; default: the sheet's H1"),
            },
            ["file"],
        ),
        FIDELITY,
        lambda a: ["row", a["file"]] + (["--protocol", a["protocol"]] if a.get("protocol") else []),
    ),
    "fidelity_verify": (
        "fidelity.py verify: each [KEY] locator of the sheet against the source's extracted text "
        "(the place exists; a Table N row's value is in that table). Exit 1 on a miss.",
        _schema(
            {
                "file": _s("the sheet, e.g. docs/fidelity.md"),
                "texts": {
                    "type": "array",
                    "minItems": 1,
                    "items": _s("KEY=PATH: a source key and its extracted text file", TEXT),
                    "description": "one KEY=PATH per source key",
                },
            },
            ["file", "texts"],
        ),
        FIDELITY,
        lambda a: ["verify", a["file"]] + [x for t in a["texts"] for x in ("--text", t)],
    ),
    "protocol_review": (
        "check_invariants.py: the org golden rules' mechanical checks on a repository's diff "
        "against a base. Exit 1 on a finding.",
        _schema(
            {
                "repo": _s("the repository checkout (default .)"),
                "base": _s("the base ref (default origin/main)", REF),
                "pr_body": _s("a file holding the PR text, for the rule 6 claims"),
            }
        ),
        REVIEW,
        lambda a: (
            [a.get("repo", "."), "--base", a.get("base", "origin/main")]
            + (["--pr-body", a["pr_body"]] if a.get("pr_body") else [])
        ),
    ),
    "release_ready": (
        "release_check.py ready: is a repository ready for a release dry-run or bump (caller "
        "workflow, Commitizen, make dist, the ladder row, open release issues). One OK/WARN/FAIL/"
        "NEXT line per check; exit 1 on a FAIL.",
        _schema(
            {
                "repo_dir": _s("the repository checkout"),
                "repo": _s("OWNER/NAME, for the issue scope and the bump PR", REPO),
                "version": _s("the version the dry-run computed, X.Y.Z", SEMVER),
            },
            ["repo_dir"],
        ),
        RELEASE,
        lambda a: (
            ["ready", a["repo_dir"]]
            + (["--repo", a["repo"]] if a.get("repo") else [])
            + (["--version", a["version"]] if a.get("version") else [])
        ),
    ),
    "release_after": (
        "release_check.py after: did everything follow a release (tag, assets, Zenodo, the site, "
        "consumers' locks). One line per check; exit 1 on a FAIL.",
        _schema(
            {
                "repo": _s("OWNER/NAME", REPO),
                "tag": _s("vX.Y.Z", TAG),
                "repos": _s(
                    "the consumers to look at, comma-separated (default: every public one)"
                ),
            },
            ["repo", "tag"],
        ),
        RELEASE,
        lambda a: (
            ["after", a["repo"], "--tag", a["tag"]]
            + (["--repos", a["repos"]] if a.get("repos") else [])
        ),
    ),
    "lock_verify": (
        "release_lock.py verify: a release lock (swarm-core.lock, ns3-tools.lock) against its "
        "release: the tag's commit, the version, each asset's SHA256. Exit 1 on a mismatch.",
        _schema({"lock": _s("the lock file, e.g. swarm-core.lock")}, ["lock"]),
        LOCK,
        lambda a: ["verify", a["lock"]],
    ),
}


def tool_list():
    return [
        {"name": n, "description": d, "inputSchema": s, "annotations": {"readOnlyHint": True}}
        for n, (d, s, _w, _b) in TOOLS.items()
    ]


def validate(schema, args):
    """The schema subset the tools use; a list of problems."""
    if not isinstance(args, dict):
        return ["arguments must be an object"]
    errs = []
    props = schema["properties"]
    for k in schema["required"]:
        if k not in args:
            errs.append(f"missing `{k}`")
    for k, v in args.items():
        if k not in props:
            errs.append(f"unknown argument `{k}`")
            continue
        p = props[k]
        vals = v if p["type"] == "array" else [v]
        if p["type"] == "array":
            if not isinstance(v, list) or len(v) < p.get("minItems", 0):
                errs.append(f"`{k}` must be a list of at least {p.get('minItems', 0)}")
                continue
            p = p["items"]
        for x in vals:
            if not isinstance(x, str) or not x or "\0" in x:
                errs.append(f"`{k}` must be a non-empty string")
            elif x.startswith("-"):
                errs.append(f"`{k}` must not start with '-' (no options through arguments)")
            elif "pattern" in p and not re.match(p["pattern"], x):
                errs.append(f"`{k}` must match {p['pattern']}")
    return errs


def trim(text, cap):
    if len(text) <= cap:
        return text
    cap = max(cap, 0)
    head, tail = cap * 2 // 3, cap // 3
    cut = len(text) - head - tail
    # text[len(text) - tail:], never text[-tail:]: with tail 0 that is the whole text
    return (
        f"{text[:head]}\n[... {cut} characters cut by swarm-mcp; run the script for the full "
        f"output ...]\n{text[len(text) - tail :]}"
    )


POLL_S = 0.1  # how often a running tool looks for its cancellation


def run(name, args, env=None, cancelled=None):
    """(text, is_error) for one tool call; None when `cancelled()` turned true
    while it ran (its process group killed, nothing to answer)."""
    _d, schema, script, build = TOOLS[name]
    problems = validate(schema, args)
    if problems:
        return f"{name}: invalid arguments: " + "; ".join(problems), True
    env = dict(os.environ if env is None else env)
    cwd = env.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    timeout = float(env.get("SWARM_MCP_TIMEOUT", "300"))
    cap = int(env.get("SWARM_MCP_MAX_CHARS", "6000"))
    cmd = [ORG_TOOL, script, *build(args)]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as e:
        return f"{name}: could not start {cmd[0]}: {e}", True
    deadline = time.monotonic() + timeout
    while True:
        # communicate() keeps what it read when it times out, so it is retried
        # in slices to look for a cancellation in between
        left = deadline - time.monotonic()
        try:
            out, err = proc.communicate(timeout=max(min(POLL_S, left), 0))
            break
        except subprocess.TimeoutExpired:
            try:
                stop = cancelled is not None and cancelled()
            except BaseException:
                # never leave the child running without its timeout's owner
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                raise
            if stop:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                return None
            if left <= POLL_S:
                os.killpg(proc.pid, signal.SIGKILL)
                out, err = proc.communicate()
                return (
                    f"{name}: timed out after {timeout:g} s\n{trim(err, cap // 4)}".rstrip(),
                    True,
                )
    code = proc.returncode
    verdict = {0: "ok", 1: "findings"}.get(code, "error")
    text = f"{name}: exit {code} ({verdict})\n{trim(out, cap)}".rstrip()
    if err.strip():
        text += f"\n--- stderr ---\n{trim(err, cap // 4)}".rstrip()
    return text, code not in (0, 1)


# --- JSON-RPC ------------------------------------------------------------------------


def _err(mid, code, message, data=None):
    e = {"code": code, "message": message}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": e}


def handle(msg, state):
    """One reply for one message (None for a notification)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _err(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    if "id" not in msg:
        return None  # notifications/initialized, cancellations: nothing to answer
    mid, method = msg["id"], msg["method"]
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return _err(mid, -32602, "params must be an object")
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    info = {"name": NAME, "version": VERSION}
    caps = {"tools": {}}

    if method == "initialize":
        asked = params.get("protocolVersion")
        state["legacy"] = asked if asked in LEGACY else LEGACY[0]
        result = {
            "protocolVersion": state["legacy"],
            "capabilities": caps,
            "serverInfo": info,
            "instructions": INSTRUCTIONS,
        }
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    version = meta.get(META_VERSION)
    if version is not None and version not in SUPPORTED:
        return _err(
            mid,
            UNSUPPORTED_VERSION,
            "Unsupported protocol version",
            {"supported": SUPPORTED, "requested": version},
        )
    modern = version in MODERN

    if method == "server/discover":
        result = {
            "supportedVersions": SUPPORTED,
            "capabilities": caps,
            "_meta": {"io.modelcontextprotocol/serverInfo": info},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or name not in TOOLS:
            return _err(mid, -32602, f"Unknown tool: {name}")
        watch = state.get("cancelled")
        done = run(name, params.get("arguments") or {}, cancelled=watch and (lambda: watch(mid)))
        if done is None:
            return None  # cancelled: the client wants no response (MCP "Cancellation")
        text, is_error = done
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return _err(mid, -32601, f"Method not found: {method}")
    if modern:
        result = {"resultType": "complete", **result}
        if method in ("server/discover", "tools/list"):  # CacheableResult in 2026-07-28
            result.update(ttlMs=CACHE_TTL_MS, cacheScope="public")
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _cancels(line):
    """The request id a `notifications/cancelled` line cancels, else None."""
    try:
        msg = json.loads(line)
    except (ValueError, RecursionError):
        return None
    if (
        not isinstance(msg, dict)
        or msg.get("jsonrpc") != "2.0"
        or msg.get("method") != "notifications/cancelled"
        or "id" in msg
    ):
        return None
    params = msg.get("params")
    rid = params.get("requestId") if isinstance(params, dict) else None
    return rid if isinstance(rid, (int, str)) and not isinstance(rid, bool) else None


def _id_of(line):
    try:
        msg = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return msg.get("id") if isinstance(msg, dict) else None


def serve(inp=sys.stdin, out=sys.stdout):
    """Serve one message at a time, in order. A reader thread keeps reading
    stdin while a tool runs, so a `notifications/cancelled` for the running
    request kills its process group and drops its response, and one for a
    request still queued drops that request; every other message waits its
    turn (docs/adr/0002, "Protocol")."""
    lines = queue.Queue()

    def reader():
        for line in inp:
            lines.put(line)
        lines.put(None)  # end of input

    threading.Thread(target=reader, daemon=True).start()
    pending = collections.deque()  # read while a tool ran, not yet served

    def cancelled(mid):
        hit = False
        while True:
            try:
                line = lines.get_nowait()
            except queue.Empty:
                return hit
            rid = None if line is None else _cancels(line)
            if rid is not None and mid is not None and rid == mid:
                hit = True
            elif rid is not None:
                for p in list(pending):
                    if p is not None and _id_of(p) == rid and _cancels(p) is None:
                        pending.remove(p)
                pending.append(line)
            else:
                pending.append(line)

    state = {"cancelled": cancelled}
    while True:
        # what arrived while the last message was served, its cancellations
        # applied, before the next one starts (a fast tool never polls)
        cancelled(None)
        line = pending.popleft() if pending else lines.get()
        if line is None:
            break
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError):  # too deep to parse is still bad JSON
            reply = _err(None, -32700, "Parse error")
        else:
            try:
                reply = handle(msg, state)
            except Exception as e:  # one bad message never ends the server
                mid = msg.get("id") if isinstance(msg, dict) else None
                reply = _err(mid, -32603, f"Internal error: {type(e).__name__}")
        if reply is not None:
            out.write(json.dumps(reply, separators=(",", ":")) + "\n")
            out.flush()
    return 0


# --- self-test -----------------------------------------------------------------------

# One fake for every org script: it prints its argv, and its arguments steer it.
FAKE = """import json, os, sys, time
a = sys.argv[1:]
print("ARGV " + json.dumps(a))
if any("sleep" in x for x in a):
    if os.environ.get("SWARM_MCP_FAKE_PID"):
        with open(os.environ["SWARM_MCP_FAKE_PID"], "w") as f:
            f.write(str(os.getpid()))
    time.sleep(30)
if any("big" in x for x in a):
    print("x" * 50000 + " TAIL")
if any("warn" in x for x in a):
    print("a warning", file=sys.stderr)
sys.exit(2 if any("fail2" in x for x in a) else 1 if any("fail1" in x for x in a) else 0)
"""


def pin_test(env, project, check):
    """org-tool with no ORG_TOOLS_DIR: the commit .github/org-sync.lock pins, an
    explicit ORG_TOOLS_REF over it, and no lock a tool error (exit 2)."""
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    origin = os.path.join(project, "pin-origin")
    repo = os.path.join(origin, ".github")
    script = os.path.join(repo, "tools", "checks", "release_lock.py")
    os.makedirs(os.path.dirname(script))

    def commit(body):
        with open(script, "w", encoding="utf-8") as f:
            f.write(body)
        subprocess.run(git + ["-C", repo, "add", "-A"], check=True)
        subprocess.run(git + ["-C", repo, "commit", "-qm", "c"], check=True)
        return subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    pinned = commit('print("PINNED")\n')
    commit('print("MAIN")\n')
    trees = {}
    for name, lock in (("locked", f'commit = "{pinned}"\n'), ("unlocked", None)):
        tree = os.path.join(project, f"pin-{name}")
        os.makedirs(os.path.join(tree, "tools", "swarm-mcp"))
        os.makedirs(os.path.join(tree, ".github"))
        with open(ORG_TOOL, encoding="utf-8") as src:
            tool = os.path.join(tree, "tools", "swarm-mcp", "org-tool")
            with open(tool, "w", encoding="utf-8") as dst:
                dst.write(src.read())
        os.chmod(tool, 0o700)  # owner only (Sonar python:S2612)
        if lock:
            with open(os.path.join(tree, ".github", "org-sync.lock"), "w", encoding="utf-8") as f:
                f.write("# a comment\n" + lock)
        trees[name] = tool
    pin_env = dict(env, SWARM_ROUTING_GIT="file://" + origin)
    pin_env.pop("ORG_TOOLS_DIR", None)
    pin_env.pop("ORG_TOOLS_REF", None)
    pin_env["XDG_CACHE_HOME"] = os.path.join(project, "pin-cache")

    def org_tool(tool, **extra):
        return subprocess.run(
            [tool, "release-lock"],
            capture_output=True,
            text=True,
            env=dict(pin_env, **extra),
            timeout=60,
            check=False,
        )

    out = org_tool(trees["locked"])
    check(
        out.returncode == 0 and out.stdout == "PINNED\n",
        "org-tool runs the org scripts at the commit .github/org-sync.lock pins, not main",
    )
    out = org_tool(trees["locked"], ORG_TOOLS_REF="main")
    check(
        out.returncode == 0 and out.stdout == "MAIN\n",
        "an explicit ORG_TOOLS_REF wins over the lock",
    )
    out = org_tool(trees["unlocked"])
    check(
        out.returncode == 2 and "no commit in" in out.stderr and not out.stdout,
        "no .github/org-sync.lock is exit 2 (a tool error), never a fallback to main",
    )


def cancel_test(env, project, call, req, check):
    """A tools/call on the fake's sleep, then notifications/cancelled for its id
    and a ping, on a live server: no reply for the call, its child gone, the
    ping answered at once (well inside the 60 s timeout). A second call queued
    behind it and cancelled before it starts is dropped, never run."""
    pidfile = os.path.join(project, "fake.pid")
    srv = subprocess.Popen(
        [sys.executable, "-I", os.path.abspath(__file__)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=dict(env, SWARM_MCP_TIMEOUT="60", SWARM_MCP_FAKE_PID=pidfile),
    )
    srv.stdin.write(call(30, "fidelity_check", {"file": "sleep.md"}) + "\n")
    srv.stdin.flush()
    deadline = time.monotonic() + 30
    while not os.path.exists(pidfile) and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.1)  # the pid written
    with open(pidfile, encoding="utf-8") as f:
        pid = int(f.read())
    t0 = time.monotonic()

    def cancel(rid):
        p = {"requestId": rid, "reason": "self-test"}
        return json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": p})

    # 32 is queued behind 30 and cancelled before it starts: it never runs
    queued = call(32, "fidelity_check", {"file": "sleep.md"})
    srv.stdin.write("\n".join([queued, cancel(32), cancel(30), req(31, "ping")]) + "\n")
    srv.stdin.flush()
    sel = selectors.DefaultSelector()
    sel.register(srv.stdout, selectors.EVENT_READ)
    first = srv.stdout.readline() if sel.select(timeout=20) else ""
    elapsed = time.monotonic() - t0
    gone = False
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            gone = True
            break
        time.sleep(0.1)
    srv.stdin.close()
    rest = srv.stdout.read()
    srv.wait(timeout=30)
    ids = [json.loads(x).get("id") for x in (first + rest).splitlines() if x.strip()]
    check(
        ids == [31] and elapsed < 5,
        f"notifications/cancelled: no reply for the cancelled call, the next request answered "
        f"at once ({ids}, {elapsed:.1f} s)",
    )
    check(gone, "notifications/cancelled: the cancelled call's child is gone")
    # A fast tool never polls: what arrived meanwhile is applied before the next
    # starts. 41's cancellation has no jsonrpc, so 41 runs (to its 3 s timeout)
    # and the message itself is answered -32600;
    # 44 is cancelled while queued and never runs; a line nested too deep to
    # parse is -32700, and every queued line is still read.
    deep = "[" * 200000 + "]" * 200000
    bad = json.dumps({"method": "notifications/cancelled", "params": {"requestId": 41}})
    fast = [
        call(40, "fidelity_check", {"file": "docs/fidelity.md"}),
        call(41, "fidelity_check", {"file": "sleep.md"}),
        bad,
        deep,
        call(44, "fidelity_check", {"file": "sleep.md"}),
        cancel(44),
        req(42, "ping"),
    ]
    t0 = time.monotonic()
    p = subprocess.run(
        [sys.executable, "-I", os.path.abspath(__file__)],
        input="\n".join(fast) + "\n",
        capture_output=True,
        text=True,
        env=dict(env, SWARM_MCP_TIMEOUT="3"),
        timeout=60,
    )
    elapsed = time.monotonic() - t0
    got = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    ids = [r.get("id") for r in got]
    timed = [r for r in got if r.get("id") == 41]
    check(
        ids == [40, 41, None, None, 42]
        and "timed out" in timed[0]["result"]["content"][0]["text"]
        and got[2]["error"]["code"] == -32600  # no jsonrpc: an invalid request, as before
        and got[3]["error"]["code"] == -32700
        and elapsed < 20,
        f"cancellations read before the next request starts; one without jsonrpc is "
        f"ignored; a too-deep line is -32700 ({ids}, {elapsed:.1f} s)",
    )


def self_test():
    failures = []

    def check(cond, what):
        print(f"{'ok' if cond else 'FAIL':5} {what}")
        if not cond:
            failures.append(what)

    org = tempfile.mkdtemp(prefix="swarm-mcp-org-")
    for rel in (
        "tools/fidelity/fidelity.py",
        "tools/protocol-review/check_invariants.py",
        "tools/release/release_check.py",
        "tools/checks/release_lock.py",
    ):
        os.makedirs(os.path.join(org, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(org, rel), "w", encoding="utf-8") as f:
            f.write(FAKE)
    project = tempfile.mkdtemp(prefix="swarm-mcp-project-")
    env = dict(os.environ)
    env.pop("ORG_TOOLS_REF", None)
    env.update(
        ORG_TOOLS_DIR=org,
        CLAUDE_PROJECT_DIR=project,
        SWARM_MCP_TIMEOUT="2",
        SWARM_MCP_MAX_CHARS="1200",
    )
    modern = {META_VERSION: MODERN[0], "io.modelcontextprotocol/clientInfo": {"name": "t"}}

    def req(i, method, params=None):
        m = {"jsonrpc": "2.0", "id": i, "method": method}
        if params is not None:
            m["params"] = params
        return json.dumps(m)

    def call(i, name, args, meta=None):
        p = {"name": name, "arguments": args}
        if meta:
            p["_meta"] = meta
        return req(i, "tools/call", p)

    lines = [
        req(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        req(2, "tools/list"),
        call(3, "fidelity_check", {"file": "docs/fidelity.md"}),
        call(4, "fidelity_verify", {"file": "f.md", "texts": ["G02=/t/g.txt", "W05=w.txt"]}),
        call(5, "protocol_review", {}),
        call(
            6, "release_ready", {"repo_dir": ".", "repo": "swarm-routing/ARA", "version": "0.3.0"}
        ),
        call(7, "release_after", {"repo": "swarm-routing/ARA", "tag": "v0.3.0"}),
        call(8, "lock_verify", {"lock": "swarm-core.lock"}),
        call(9, "fidelity_check", {"file": "fail1.md"}),
        call(10, "fidelity_check", {"file": "fail2-warn.md"}),
        call(11, "fidelity_check", {"file": "sleep.md"}),
        call(12, "fidelity_check", {"file": "big.md"}),
        call(13, "fidelity_check", {}),
        call(14, "fidelity_check", {"file": "--self-test"}),
        call(15, "release_ready", {"repo_dir": ".", "version": "1.2"}),
        call(16, "lock_verify", {"lock": "x.lock", "base": "file:///"}),
        call(17, "no_such_tool", {}),
        req(18, "resources/list"),
        "{not json",
        req(19, "server/discover", {"_meta": modern}),
        call(20, "fidelity_row", {"file": "f.md", "protocol": "ARA"}, modern),
        req(21, "tools/list", {"_meta": {META_VERSION: "1900-01-01"}}),
        req(22, "ping"),
        json.dumps([1, 2]),
        req(23, "tools/call", {"name": [], "arguments": {}}),
        req(24, "tools/list", {"_meta": modern}),
        req(25, "tools/call", {"name": "fidelity_check", "arguments": "x"}),
    ]
    proc = subprocess.run(
        [sys.executable, "-I", os.path.abspath(__file__)],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    replies = [json.loads(x) for x in proc.stdout.splitlines()]
    by_id = {r.get("id"): r for r in replies}
    res = {i: r.get("result", {}) for i, r in by_id.items()}

    def text(i):
        c = res.get(i, {}).get("content") or [{}]
        return c[0].get("text", "")

    check(proc.returncode == 0, "the server exits 0 at the end of its input")
    check(len(replies) == 27, f"one reply per request, none for the notification ({len(replies)})")
    init = res.get(1, {})
    check(
        init.get("protocolVersion") == "2025-06-18"
        and init.get("serverInfo", {}).get("name") == NAME
        and "tools" in init.get("capabilities", {}),
        "initialize: the legacy version asked for, serverInfo, the tools capability",
    )
    names = [t["name"] for t in res.get(2, {}).get("tools", [])]
    check(names == list(TOOLS), f"tools/list: every tool in a fixed order ({names})")
    check(
        all(t["inputSchema"]["additionalProperties"] is False for t in res[2]["tools"]),
        "tools/list: every schema closes its arguments",
    )
    check("resultType" not in res[2], "a legacy result carries no resultType")
    check(
        text(3).startswith("fidelity_check: exit 0 (ok)")
        and 'ARGV ["check", "docs/fidelity.md"]' in text(3)
        and res[3]["isError"] is False,
        "fidelity_check: org-tool runs fidelity.py check FILE",
    )
    check(
        'ARGV ["verify", "f.md", "--text", "G02=/t/g.txt", "--text", "W05=w.txt"]' in text(4),
        "fidelity_verify: one --text per KEY=PATH",
    )
    check(
        'ARGV [".", "--base", "origin/main"]' in text(5),
        "protocol_review: defaults . and origin/main",
    )
    check(
        'ARGV ["ready", ".", "--repo", "swarm-routing/ARA", "--version", "0.3.0"]' in text(6),
        "release_ready: ready REPO_DIR --repo --version",
    )
    check(
        'ARGV ["after", "swarm-routing/ARA", "--tag", "v0.3.0"]' in text(7),
        "release_after: after OWNER/NAME --tag",
    )
    check(
        'ARGV ["verify", "swarm-core.lock"]' in text(8), "lock_verify: release_lock.py verify LOCK"
    )
    check(
        "exit 1 (findings)" in text(9) and res[9]["isError"] is False,
        "exit 1 is a verdict with findings, not a tool error",
    )
    check(
        "exit 2 (error)" in text(10)
        and "--- stderr ---\na warning" in text(10)
        and res[10]["isError"],
        "exit 2 is a tool error, and stderr follows the output",
    )
    check(
        "timed out after 2 s" in text(11) and res[11]["isError"],
        "a call past the timeout is killed",
    )
    check(
        "characters cut by swarm-mcp" in text(12)
        and text(12).endswith("TAIL")
        and len(text(12)) < 1400,
        f"the output is capped, head and tail kept ({len(text(12))} chars)",
    )
    check("missing `file`" in text(13) and res[13]["isError"], "a missing argument is a tool error")
    check("must not start with '-'" in text(14), "an argument cannot pass an option to the script")
    check("must match" in text(15), "a version must be X.Y.Z")
    check("unknown argument `base`" in text(16), "an argument outside the schema is refused")
    check(by_id.get(17, {}).get("error", {}).get("code") == -32602, "an unknown tool is -32602")
    check(by_id.get(18, {}).get("error", {}).get("code") == -32601, "an unknown method is -32601")
    check(any(r.get("error", {}).get("code") == -32700 for r in replies), "bad JSON is -32700")
    disc = res.get(19, {})
    check(
        disc.get("resultType") == "complete"
        and disc.get("supportedVersions") == SUPPORTED
        and disc.get("_meta", {}).get("io.modelcontextprotocol/serverInfo", {}).get("name") == NAME,
        "server/discover: the versions, the capabilities, serverInfo in _meta",
    )
    check(
        res.get(20, {}).get("resultType") == "complete"
        and 'ARGV ["row", "f.md", "--protocol", "ARA"]' in text(20),
        "a modern tools/call is served statelessly, with resultType",
    )
    e21 = by_id.get(21, {}).get("error", {})
    check(
        e21.get("code") == UNSUPPORTED_VERSION
        and e21.get("data", {}).get("supported") == SUPPORTED,
        "an unknown protocol version is UnsupportedProtocolVersionError with the supported list",
    )
    check(res.get(22) == {}, "ping answers {}")
    check(
        any(r.get("error", {}).get("code") == -32600 for r in replies),
        "a batch is an invalid request (MCP has no batches)",
    )
    check(
        by_id.get(23, {}).get("error", {}).get("code") == -32602,
        "a tool name that is not a string is -32602, and the server keeps serving",
    )
    tl = res.get(24, {})
    check(
        tl.get("resultType") == "complete"
        and tl.get("ttlMs") == CACHE_TTL_MS
        and tl.get("cacheScope") == "public"
        and disc.get("ttlMs") == CACHE_TTL_MS
        and disc.get("cacheScope") == "public"
        and "ttlMs" not in res.get(2, {})
        and "ttlMs" not in res.get(20, {}),
        "modern tools/list and server/discover carry ttlMs and cacheScope (CacheableResult)",
    )
    check(
        "arguments must be an object" in text(25) and res[25]["isError"],
        "arguments that are not an object are a tool error",
    )
    check(
        trim("a" * 100 + "Z", 2) == "a\n[... 100 characters cut by swarm-mcp; run the script for "
        "the full output ...]\n",
        "a cap whose tail is 0 keeps no tail, not the whole text",
    )
    check(trim("abc", -5).endswith("...]\n"), "a negative cap keeps nothing")
    cancel_test(env, project, call, req, check)
    pin_test(env, project, check)
    nowhere = dict(env, SWARM_ROUTING_GIT="file://" + os.path.join(project, "nowhere"))
    nowhere.pop("ORG_TOOLS_DIR")
    nowhere["XDG_CACHE_HOME"] = os.path.join(project, "cache")
    text_nf, err_nf = run("lock_verify", {"lock": "x.lock"}, nowhere)
    check(
        err_nf and "exit 2 (error)" in text_nf,
        "org scripts that cannot be fetched are a tool error, not findings",
    )
    bad = subprocess.run(
        [ORG_TOOL, "no-such-script"], capture_output=True, text=True, env=env, timeout=30
    )
    check(
        bad.returncode == 2 and "usage: org-tool" in bad.stderr,
        "org-tool runs only the scripts in its table",
    )
    scripts = {t[2] for t in TOOLS.values()}
    with open(ORG_TOOL, encoding="utf-8") as f:
        table = set(re.findall(r"^    ([a-z-]+)\) py=", f.read(), re.M))
    check(table == scripts, f"org-tool's table is exactly the tools' scripts ({sorted(table)})")
    try:
        with open(os.path.join(HERE, "..", "..", ".cz.toml"), encoding="utf-8") as f:
            cz = re.search(r'^version = "([^"]+)"', f.read(), re.M)
    except OSError:
        cz = None
    check(
        cz is not None and cz.group(1) == VERSION,
        f"VERSION is .cz.toml's version ({VERSION})",
    )
    print(f"swarm_mcp self-test: {'ok' if not failures else f'{len(failures)} failed'}")
    return 1 if failures else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--self-test"]:
        return self_test()
    if argv == ["--list"]:
        for t in tool_list():
            print(f"{t['name']}: {t['description']}")
        return 0
    if argv:
        print(__doc__, file=sys.stderr)
        return 2
    return serve()


if __name__ == "__main__":
    sys.exit(main())
