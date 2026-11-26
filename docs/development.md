# Developer guide

swarm-mcp is the org's local, read-only MCP server: one stdlib Python file,
`tools/swarm-mcp/swarm_mcp.py`, whose tools run read-only commands of
`swarm-routing/.github` scripts through `tools/swarm-mcp/org-tool`. A
contributor usually adds or changes a tool (the design and its rules:
[ADR-0002](adr/0002-swarm-mcp-is-a-local-read-only-mcp-server.md)).

## Prerequisites

Python 3.11 or newer (the org scripts the tools run import `tomllib`; CI
runs 3.13), bash, git, and for `make lint` ruff (the version in
swarm-routing/.github `tools/versions.env`), shellcheck and actionlint
1.7.12. `make headers`, and so `make check`, also needs Docker with a
running daemon or Go: the org's header check is a Go tool it runs in its
image or builds. `make doctor` compares this machine's tools with CI's.

## Get the code

```bash
git clone https://github.com/swarm-routing/swarm-mcp.git
cd swarm-mcp
```

A checkout of swarm-routing/.github beside it (`../.github`) lets the server
run the scripts from it (`ORG_TOOLS_DIR=../.github`) instead of fetching a
snapshot; the self-test needs neither.

## Dependencies

None to install: the server uses the standard library only. At run time
`org-tool` reads the org scripts from `ORG_TOOLS_DIR`, else a snapshot of
swarm-routing/.github at `ORG_TOOLS_REF` (default: the commit
`.github/org-sync.lock` pins; docs/adr/0002) cached under
`${XDG_CACHE_HOME:-~/.cache}/swarm-routing/checkouts/`.

## Build

Nothing to build: `make build` says so.

## Test

```bash
make test   # python3 -I tools/swarm-mcp/swarm_mcp.py --self-test
```

The self-test starts the server, sends it every kind of request (legacy and
modern protocol, every tool, bad arguments, a timeout, an oversized output)
against fake org scripts, and checks each reply; no network. CI runs it
under coverage through `tools/swarm-mcp/test_swarm_mcp.py` (`python /
python`).

## Run

```bash
python3 -I tools/swarm-mcp/swarm_mcp.py --list                        # the tools
ORG_TOOLS_DIR=../.github python3 -I tools/swarm-mcp/swarm_mcp.py      # serve on stdin/stdout
```

One request by hand:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"fidelity_check","arguments":{"file":"docs/fidelity.md"}}}' \
  | ORG_TOOLS_DIR=../.github CLAUDE_PROJECT_DIR=../ARA python3 -I tools/swarm-mcp/swarm_mcp.py
```

In Claude Code the `swarm-routing` plugin (swarm-routing/skills) starts it
at the commit its `swarm-mcp.lock` pins.

## Docker and dev containers

None: `make shell` opens a `python:3.13-slim` shell with the repository at
`/src`.

## Lint and format

```bash
make lint     # ruff check + ruff format --check on tools/, shellcheck on org-tool, actionlint
make format   # ruff format tools
make headers  # the licence headers (LICENSING.md), as licence.yml
```

## CI map

| Workflow | What it checks | Required |
| --- | --- | --- |
| `ci.yml` | `lint`: actionlint, shellcheck; `python / python`: ruff, the self-test under coverage | yes |
| `licence.yml` | `headers / licence`: every file's SPDX line against LICENSING.md | yes |
| `org-sync.yml` | `check / org-sync`: the org-managed files against the templates the lock pins | yes |
| `pr-title.yml` | `title / title`: a lowercase Conventional Commit | yes |
| `review-gate.yml` | `review / coderabbit`: CodeRabbit has reviewed | yes |
| `scorecard.yml`, `dco.yml` | OpenSSF Scorecard, DCO sign-off of outside contributors | no |
| `release.yml` | the release, on the maintainer's dispatch only | no |

The required checks are the ones the `main` ruleset lists (`gh api
repos/swarm-routing/swarm-mcp/rules/branches/main`), set from
`.github/org-sync.toml` `[settings]`.

## Release

How a version is cut: [CONTRIBUTING "Cutting a release"](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#cutting-a-release).
A release publishes `swarm-mcp-<version>.tar.gz` (`make dist`, the tree at
the release commit) with its checksums and provenance; Commitizen moves
`.cz.toml`, `VERSION` in `swarm_mcp.py` and `CITATION.cff` together. The
ladder is [docs/roadmap.md](roadmap.md); the first release is v0.1.0.

## Troubleshooting

- **A tool returns `could not refresh` or a git error**: `org-tool` could
  not fetch swarm-routing/.github; set `ORG_TOOLS_DIR` to a local checkout.
- **`VERSION is .cz.toml's version` fails**: a hand edit moved one of the
  two; only Commitizen moves them, together.
