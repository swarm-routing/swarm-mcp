# 0002. swarm-mcp is a local, read-only MCP server over the org's scripts

- **Status:** accepted; moved here from swarm-routing/skills and amended
  (2026-11-22, see "Amendment: its own repository")
- **Date:** 2026-11-22
- **Issue:** swarm-routing/skills#185 (part of swarm-routing/.github#672,
  decisions 20 and 23)
- **Moved from:** swarm-routing/skills
  [`docs/adr/0002-swarm-mcp-is-a-local-read-only-mcp-server.md`](https://github.com/swarm-routing/skills/blob/02e08bad8043a4cf128c7f87ec47faa3850cb8cf/docs/adr/0002-swarm-mcp-is-a-local-read-only-mcp-server.md)
  at commit `02e08bad8043a4cf128c7f87ec47faa3850cb8cf` (swarm-routing/skills#187),
  where it was accepted with the prototype. It keeps its number here: this
  repository's 0001 is the org's seeded "Record architecture decisions", and
  0002 is the number every existing reference to this decision already uses.

## Amendment: its own repository (2026-11-22)

The maintainer decided on 2026-11-22: "configure the MCP repo out of skills
https://github.com/swarm-routing/swarm-mcp — Skills and MCP repo need to work
together". So:

- **swarm-routing/skills** holds the procedures and the Claude Code plugin
  `swarm-routing`; **swarm-routing/swarm-mcp** (this repository) holds the
  MCP server, versioned and released on its own (`.cz.toml`,
  `docs/roadmap.md`, from 0.0.0).
- **The plugin pins swarm-mcp.** Its `.mcp.json` starts a small launcher in
  skills that runs this repository's `tools/swarm-mcp/swarm_mcp.py` at the
  commit skills' `swarm-mcp.lock` names, from the same immutable snapshot
  cache the skill wrappers use. Moving the pin is a reviewed PR in skills,
  so a change merged here reaches no session until skills moves it.
- **The server finds the org scripts itself**, without skills:
  `tools/swarm-mcp/org-tool` (beside the server) carries the skill wrappers'
  `cached-checkout` block byte for byte and runs exactly the four scripts the
  tools use. That keeps this repository self-contained (it runs from any
  checkout or snapshot of it, with no skills checkout beside it) while the
  convention stays the one every skill uses (`ORG_TOOLS_DIR`, else a
  snapshot of `swarm-routing/.github` at `ORG_TOOLS_REF`, default `main`).
- **Versioning.** `serverInfo.version` is this repository's version
  (`VERSION` in `swarm_mcp.py`, moved with `.cz.toml` and `CITATION.cff` by
  Commitizen), no longer the plugin's.

The sections below are the decision as accepted, with the paths and the
places that changed with the move rewritten; nothing else changed.

## Context

The org's procedures are skills over scripts (skills golden rule 11): the
script does the work, the agent reads its summary. An agent reaches those
scripts through a skill's wrapper and the Bash tool, which costs a skill
load, a shell command it has to compose, and the script's whole output in
context. The Model Context Protocol (MCP) lets a client call a named tool
with typed arguments and get its result back, without the shell and without
the skill text, in any MCP client (Claude Code, Codex, Cursor, Copilot, …).

The maintainer decided on 2026-11-22 (swarm-routing/.github#672) that a
`swarm-mcp` prototype starts as an extension of the `protocol-review`,
`fidelity-sheet` and `release` skills rather than as new skills (decision
20), and that it is scheduled now (decision 23). Two questions were open:
the language (swarm-routing/.github ADR-0002 makes pipelines Go and lets
skill scripts stay Python), and the packaging.

What the plugin starts runs in every session of every repository that
enables it, so the server is a trust boundary as the skills are (skills
golden rule 10).

## Decision

### What it is

`swarm-mcp` is a **local stdio MCP server**, `tools/swarm-mcp/swarm_mcp.py`,
run by the agent session; it needs no hosted service, no account and no
port. Each tool runs **one read-only command** of an org script and returns
its exit status and its summary text:

| Tool | Runs | Through |
|------|------|---------|
| `fidelity_check` | `fidelity.py check FILE` | `org-tool fidelity` |
| `fidelity_row` | `fidelity.py row FILE [--protocol NAME]` | same |
| `fidelity_verify` | `fidelity.py verify FILE --text KEY=PATH ...` | same |
| `protocol_review` | `check_invariants.py [REPO] --base REF [--pr-body FILE]` | `org-tool check-invariants` |
| `release_ready` | `release_check.py ready REPO_DIR [--repo O/N] [--version X.Y.Z]` | `org-tool release-check` |
| `release_after` | `release_check.py after O/N --tag vX.Y.Z [--repos A,B]` | same |
| `lock_verify` | `release_lock.py verify LOCK` | `org-tool release-lock` |

The rules every tool keeps, which a review of a new tool checks:

1. **Read-only commands only.** No tool maps to a command that writes a file,
   a branch, an issue or a release (`fidelity.py skeleton`/`bib sources`,
   `release_lock.py bump --write`, `zenodo.py` writes and every dispatch stay
   out). A new tool names its command in this table, and `org-tool`'s table
   names exactly the scripts the tools use (the self-test checks it).
2. **The script's summary, never raw data, and a cap.** The result is
   `<tool>: exit N (ok|findings|error)`, the script's stdout, then its stderr,
   trimmed to `SWARM_MCP_MAX_CHARS` (default 6000 characters for stdout, a
   quarter of that for stderr), keeping the head and the tail (where the
   verdict line is) with a marker naming the cut. Exit 1 is a verdict with
   findings (`isError: false`); any other non-zero exit, a timeout
   (`SWARM_MCP_TIMEOUT`, default 300 s, the process group killed) or a
   command that cannot start is a tool error (`isError: true`).
3. **Arguments are data, never options.** Each tool has a closed input schema
   (`additionalProperties: false`), versions, tags, repositories and refs have
   patterns, and no string may start with `-`, so a caller cannot reach a
   flag the table does not list. The command is an argv list; no shell
   parses it. Relative paths resolve against `CLAUDE_PROJECT_DIR` (set by
   Claude Code), else the server's working directory.
4. **No network of its own, no token, no write.** The server opens no
   connection, reads no credential and writes no file. What it runs does
   what it does for a skill: without `ORG_TOOLS_DIR`, `org-tool` fetches
   `swarm-routing/.github` from github.com into its snapshot cache (below);
   a script reaches the network only as it does when a person runs it
   (`git ls-remote`, `gh` with the user's own login for `release_after`,
   public HTTPS reads). Nothing touches the repository a tool reads. The
   environment passes through to the script unchanged and is never printed.

### Where the scripts come from

`tools/swarm-mcp/org-tool` finds them, with the convention every skill
wrapper uses: `ORG_TOOLS_DIR=<checkout of swarm-routing/.github>` names a
local checkout (the sibling `../.github` when it is one); otherwise its
`cached-checkout` block (the wrappers' own, byte for byte) fetches
`swarm-routing/.github` at `ORG_TOOLS_REF` (default `main`) into an
immutable snapshot under `${XDG_CACHE_HOME:-~/.cache}/swarm-routing/checkouts/`.
That fetch is the only network step outside the scripts, and it is the same
one the skills make. (Before the move the server ran the skills' wrappers
themselves.)

### Language: Python, stdlib only

The server is Python with the standard library alone: JSON-RPC 2.0 over
stdio is a few hundred lines, and a third-party MCP SDK would be the first
dependency a session installs for it. swarm-routing/.github ADR-0002 makes
**pipelines** (code a workflow runs) Go and lets **skill scripts** stay
Python; swarm-mcp is neither a pipeline nor run by a workflow, it is the
agent-side face of the skills' scripts and runs where they run, with the
`python3` the wrappers already need. A Go binary would need a build step or
a published binary per platform. If a pipeline ever needs these verdicts it
calls the scripts (or their Go ports) directly, not this server.

### Protocol

The server is **dual-era** (MCP specification, "Versioning and
Compatibility"): a modern request carries
`params._meta["io.modelcontextprotocol/protocolVersion"]` = `2026-07-28` and
is served statelessly, with `resultType: "complete"`; `server/discover`
returns the supported versions, the `tools` capability and `serverInfo` in
`_meta`. A legacy client opens with `initialize` and gets the version it
asked for among `2025-11-25`, `2025-06-18`, `2025-03-26` (else `2025-11-25`).
An unknown version is `UnsupportedProtocolVersionError` (-32022) listing the
supported ones; an unknown tool is -32602, an unknown method -32601, bad
JSON -32700, a batch -32600 (MCP has no batches); notifications get no
reply. A modern `tools/list` and `server/discover` carry the
`CacheableResult` fields (`ttlMs` one hour, `cacheScope: "public"`: the list
is fixed for a server version). A message the server cannot handle is
-32603 and the server keeps serving. Methods: `initialize`,
`server/discover`, `ping`, `tools/list`, `tools/call`. `tools/list` is in a
fixed order, each tool annotated `readOnlyHint: true`.

### Packaging and running it

- **Claude Code**: the `swarm-routing` plugin (swarm-routing/skills) starts
  it from its `.mcp.json`, through its launcher, at the commit its
  `swarm-mcp.lock` pins (see the amendment above). Every repository that
  enables the plugin gets it with the plugin; nothing is added to any
  repository's `.claude/settings.json`. Its tools appear under the server's
  name (the client prefixes each tool name with the plugin's and the
  server's).
- **Any other MCP client, or by hand**, from a checkout of this repository:

  ```bash
  python3 -I tools/swarm-mcp/swarm_mcp.py               # the server, on stdin/stdout
  python3 -I tools/swarm-mcp/swarm_mcp.py --list        # its tools, one line each
  python3 -I tools/swarm-mcp/swarm_mcp.py --self-test   # what make test runs
  ```

  registered in the client's own MCP configuration with that command, and
  `ORG_TOOLS_DIR` in its environment where a local `.github` checkout should
  be used. skills.sh installs skills only, not this server.
- **Validation**: skills' `tools/checks/check-plugins.py` checks the
  plugin's `.mcp.json` (local stdio servers only, every
  `${CLAUDE_PLUGIN_ROOT}/<path>` a file in the plugin, no literal `env`
  value) and its launcher and pin.

### Versioning

`serverInfo.version` is this repository's version (`VERSION` in
`swarm_mcp.py`, which the self-test checks against `.cz.toml`). A tool's
name, its arguments and their meaning are a contract for the agents and
skills that call it: a tool is added, or an optional argument is added, in
a minor version; a rename, a removed tool or a changed meaning is a new tool
name, with the old one kept until a major version.

### Trust boundary

The server adds no capability a session does not already have through the
Bash tool and the wrappers: the same scripts, the same arguments a skill
documents, minus every write. A change that adds a tool, an argument or a
network step is reviewed here as a change to every session that enables the
plugin, against the four rules above, and reaches those sessions only when
skills moves its pin. The client still shows each call and can deny it.

### Out of scope

- Any tool that writes, dispatches a workflow, comments, or bumps a lock.
- A hosted or remote MCP endpoint (swarm-routing/swarm-routing.github.io#238
  stays deferred), HTTP transports, authentication.
- Resources, prompts, sampling, elicitation, subscriptions and
  `listChanged`: the tool list is fixed for a server version.
- The other skills' scripts (docs-review, pr-status, lit-search, …):
  candidates for later tools, each a reviewed PR.
- Structured output (`structuredContent`): the summary text is the
  contract the scripts already keep (AntHocNet ADR-0014).

## Consequences

- An agent gets a verdict in one typed call, without composing a shell
  command or loading a skill, and with a bounded result size.
- The scripts stay the single implementation: the server only maps tool
  arguments to their argv, so a script's fix reaches the MCP tool at once.
- Every session that enables the plugin can start the server; its whole
  surface is the seven read-only commands above, and widening it is a
  reviewed change here plus a pin move in skills.
- `org-tool`'s `cached-checkout` block is a second copy of the skill
  wrappers'; a change to that block in skills is copied here in a PR.
- The org MCP standard in swarm-routing/.github refers to this server by its
  name, `swarm-mcp`, and its repository.
- Ruled out: write tools in this server, a third-party MCP SDK.
