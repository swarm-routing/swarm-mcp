# swarm-mcp

<!-- org-sync:begin badges -->
| Group | Badges |
| --- | --- |
| Build | [![CI](https://github.com/swarm-routing/swarm-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/swarm-routing/swarm-mcp/actions/workflows/ci.yml) |
| Release | [![Release](https://img.shields.io/github/v/release/swarm-routing/swarm-mcp?sort=semver&cacheSeconds=1800)](https://github.com/swarm-routing/swarm-mcp/releases) [![Cite](https://img.shields.io/badge/cite-CITATION.cff-blue)](CITATION.cff) [![Licence: GPL-2.0-only, tools/ MIT OR GPL-2.0-only](https://img.shields.io/badge/licence-GPL--2.0--only%2C%20tools%2F%20MIT%20OR%20GPL--2.0--only-blue)](LICENSING.md) |
| Trust | [![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/swarm-routing/swarm-mcp/badge)](https://scorecard.dev/viewer/?uri=github.com/swarm-routing/swarm-mcp) [![OpenSSF Best Practices](https://www.bestpractices.dev/projects/17076/badge)](https://www.bestpractices.dev/projects/17076) |
| Indexes | [![M8ven Verified](https://m8ven.ai/api/agent-verify/badge?id=a770df99a2438405)](https://m8ven.ai/verified/verify?id=a770df99a2438405) [![swarm-mcp MCP server – quality and maintenance score on Glama](https://glama.ai/mcp/servers/swarm-routing/swarm-mcp/badges/score.svg)](https://glama.ai/mcp/servers/swarm-routing/swarm-mcp) |
| Stack | [![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python)](AGENTS.md) |
| Community & docs | [![Colony Arena: swarm-mcp](https://img.shields.io/badge/Colony%20Arena-project%20page-orange)](https://swarm-routing.github.io/projects/swarm-mcp/) [![Open RCAPA](https://img.shields.io/github/issues/swarm-routing/swarm-mcp/rcapa?label=open%20RCAPA&color=blue)](https://github.com/swarm-routing/swarm-mcp/blob/main/docs/rcapa/README.md) [![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow)](https://www.conventionalcommits.org) |
<!-- org-sync:end badges -->

`swarm-mcp`, the swarm-routing org's **MCP server**: a local, read-only
[Model Context Protocol](https://modelcontextprotocol.io) server (stdio,
Python stdlib) whose tools each run one read-only command of a
`swarm-routing/.github` script (a fidelity sheet's checks, the golden-rule
checks on a diff, a release's readiness and aftercare, a release lock) and
return the script's own summary, capped. The Claude Code plugin
`swarm-routing` from [swarm-routing/skills](https://github.com/swarm-routing/skills)
starts it at the commit it pins; any other MCP client runs it the same way.
Skills hold the procedures, this repository the server, each versioned and
released on its own.

## Tools

| Tool | Runs (a swarm-routing/.github script) |
|------|------|
| `fidelity_check` | `fidelity.py check FILE` |
| `fidelity_row` | `fidelity.py row FILE [--protocol NAME]` |
| `fidelity_verify` | `fidelity.py verify FILE --text KEY=PATH ...` |
| `protocol_review` | `check_invariants.py [REPO] --base REF [--pr-body FILE]` |
| `release_ready` | `release_check.py ready REPO_DIR [--repo O/N] [--version X.Y.Z]` |
| `release_after` | `release_check.py after O/N --tag vX.Y.Z [--repos A,B]` |
| `lock_verify` | `release_lock.py verify LOCK` |

Every tool is read-only and returns the script's summary, capped; exit 1
means findings. The design, its rules and what is out of scope:
[ADR-0002](docs/adr/0002-swarm-mcp-is-a-local-read-only-mcp-server.md).

## Use

In Claude Code, enable the `swarm-routing` plugin
([swarm-routing/skills](https://github.com/swarm-routing/skills)): it starts
this server at the commit its `swarm-mcp.lock` pins. In any other MCP
client, register the command

```bash
python3 -I /path/to/swarm-mcp/tools/swarm-mcp/swarm_mcp.py
```

as a stdio server, with `ORG_TOOLS_DIR` set to a checkout of
swarm-routing/.github if you have one (otherwise the server fetches a
snapshot of the commit this repository's `.github/org-sync.lock` pins).
[`server.json`](server.json) describes the server for the official
[MCP Registry](https://registry.modelcontextprotocol.io) (#51); Commitizen
keeps its version in step with each release, and
`.github/workflows/mcp-registry.yml` publishes it there on each release, by
GitHub OIDC (no stored token).

## Security model

swarm-mcp serves stdio only. The MCP client starts it as a child process
for one user, and it runs with that user's permissions. Nothing listens on
a network, so there is no caller to authenticate and no traffic to
rate-limit. Whoever can start the server can already run the scripts it
wraps. The limits that do apply
([ADR-0002](docs/adr/0002-swarm-mcp-is-a-local-read-only-mcp-server.md)):

- **Read-only tools.** Each tool maps to one read-only command of a
  `swarm-routing/.github` script, from a fixed table. None writes,
  dispatches, comments or bumps a lock.
- **Arguments are data.** Every tool's schema is closed: an unknown argument
  is refused. Every value must be a non-empty string with no NUL byte and no
  leading `-`, so no option reaches a script through an argument. The
  patterned values (a version, a tag, a repository, a ref, a `KEY=PATH`)
  must match their pattern.
- **No shell.** The command is an argv list, run in its own process group
  with stdin closed.
- **One call at a time.** Messages are served in order, one at a time.
- **Bounded time.** A call is killed (its whole process group) after
  `SWARM_MCP_TIMEOUT` seconds, 300 by default, and returned as a tool error.
  A `notifications/cancelled` for the running call kills it at once and
  drops its response (#16).
- **Bounded output.** A result is the script's summary trimmed to
  `SWARM_MCP_MAX_CHARS` characters, 6000 by default, with a quarter of that
  for stderr. Exit 1 means findings; any other failure is a tool error.
- **Pinned scripts.** The scripts run at the commit this repository's
  `.github/org-sync.lock` pins, never `.github` `main` (#39). A lock with no
  commit is a tool error.

The server collects and sends nothing: [PRIVACY.md](PRIVACY.md). Reporting
a vulnerability: [SECURITY.md](SECURITY.md).

<!-- org-sync:begin develop -->
## Develop

New here? [docs/development.md](docs/development.md) is the developer guide:
the tools to install, how to get the code and its dependencies, how to
build, test, run and lint it, the Docker images, what CI checks and how to
read a red run. How changes are proposed, reviewed and released is the org's
[CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md).
Where this repository sits among the org's layers and hosts:
[the org's architecture](https://github.com/swarm-routing/.github/blob/main/docs/architecture.md).
Whether a regression here gets an RCAPA (root cause analysis with corrective
and preventive actions), and how: [docs/rcapa/README.md](docs/rcapa/README.md).
<!-- org-sync:end develop -->

<!-- org-sync:begin citing -->
## Releases & citing

Versions follow [SemVer](https://semver.org) ([CHANGELOG.md](CHANGELOG.md)). Each release is listed under [Releases](https://github.com/swarm-routing/swarm-mcp/releases), built by the org's release workflow.

To cite this repository, use the “Cite this repository” button (from [CITATION.cff](CITATION.cff)). Its releases are not archived on Zenodo, so it has no DOI: name the release you used by its tag.

Using it in your work? Contributions are welcome, and citing it helps just as much.
<!-- org-sync:end citing -->

## Contributing

Contributions from forks are welcome: see
[Outside contributions](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#outside-contributions)
(sign off every commit with `git commit -s`).

## Epics

<!-- epics:begin -->
<!-- Generated by swarm-routing/.github tools/epics/epics.py from the issues labelled `epic`; edit the issues, then re-run it. -->

What is planned and in progress here: the issues labelled [`epic`](https://github.com/swarm-routing/swarm-mcp/issues?q=label%3Aepic). An epic's open sub-issues carry a `priority:*` and a `model:*` label, so a contributor or an AI agent can pick one up ([how issues work](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#issues)). The whole org's plan: the [roadmap](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md#epics).

No open epic: the work here is tracked as single issues.

<!-- epics:end -->

## Licence

See [LICENSING.md](LICENSING.md).
