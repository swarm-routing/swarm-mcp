# Roadmap

Which release each piece of work serves, and what each release must show to
ship. Releases are cut on the maintainer's request only (swarm-routing/.github
CONTRIBUTING "Cutting a release"); the org-wide view is the
[org ROADMAP](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md).
A version's scope is the set of issues labelled `release:vX.Y.Z`; the release
workflow's ladder gate refuses a bump whose version has no row here.

swarm-mcp is versioned and released on its own, apart from the skills plugin
that starts it (maintainer decision 2026-11-22, [ADR-0002](adr/0002-swarm-mcp-is-a-local-read-only-mcp-server.md)):
the plugin pins a commit of this repository in `swarm-mcp.lock`
(swarm-routing/skills), so a session runs the server the pin names whether
or not it is a release. A release is the citable, verifiable snapshot, and
the commit the plugin's pin should name once one exists.

## Release ladder

| Release | Theme | Exit criteria |
|---|---|---|
| v0.1.0 | first tagged release: the seven read-only tools moved from swarm-routing/skills | `release.yml` on `reusable-release.yml`; `.cz.toml`, `VERSION` in `swarm_mcp.py` and `CITATION.cff` at one version (the self-test checks the first two); `make check` and CI green on `main`; the skills plugin starts the server from its pin; a dry run green; no open issue labelled `release:v0.1.0`; the maintainer asks for it |
| v0.2.0 | `notifications/cancelled` while a tool runs (#16); the no-flock cache-lock recovery (#17); the org scripts at the commit `.github/org-sync.lock` pins, not `.github` `main` (#39, #40) | the same release machinery green; `make check` and CI green on `main`; a dry run green with Commitizen computing 0.2.0; no open issue labelled `release:v0.2.0`; the maintainer asks for it (2026-11-26, in the swarm-routing coordinator session) |

## Non-goals

- No write tool, no network transport, no hosted endpoint (ADR-0002, "Out of
  scope").
- No release per change: the plugin's pin decides what sessions run.

## Shipped releases

Every published release (no Zenodo archive: `zenodo = false`), read from GitHub by swarm-routing/.github `tools/zenodo/zenodo.py shipped` (org-bot's `release-aftercare` task); never edit the block by hand.

<!-- releases:shipped:begin (zenodo.py shipped --write; never edit by hand) -->
- **v0.1.0** shipped 2026-11-22 ([release](https://github.com/swarm-routing/swarm-mcp/releases/tag/v0.1.0))
<!-- releases:shipped:end -->
