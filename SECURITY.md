# Security Policy

`swarm-routing/swarm-mcp` is the org's agent tooling: a local, read-only MCP server over the org's scripts, no simulation code. This document records its
security posture honestly; it promises nothing the code does not do. The
org-wide policy is [swarm-routing/.github SECURITY.md](https://github.com/swarm-routing/.github/blob/main/SECURITY.md).

## Trust boundary

The arguments of a `tools/call` request, which come from the MCP client
(an agent). Only `tools/swarm-mcp/swarm_mcp.py` parses them: each tool's
schema is closed (an unknown argument is refused), every value is a
non-empty string that cannot start with `-` (no option reaches a script
through an argument) and the patterned ones (a version, a tag, a repository,
a ref) must match. The server runs a fixed table of read-only script
commands with an argument list, never a shell; it opens no connection, reads
no token and writes no file of its own. A script reaches the network only as
it does when a person runs it: `tools/swarm-mcp/org-tool` fetches
`swarm-routing/.github` (public HTTPS) unless `ORG_TOOLS_DIR` names a
checkout, and some scripts read GitHub with `gh` as the user.

## Known, by-design limitations (out of scope)

- **The scripts are `swarm-routing/.github`'s.** The server runs them from a
  snapshot of that repository's `main` (or `ORG_TOOLS_REF`, or the checkout
  `ORG_TOOLS_DIR` names), so what a tool does is what that script does at
  that commit; review lands there.
- **Local stdio only.** There is no network transport and no authentication:
  whoever starts the server can call its tools, with their own permissions.

<!-- org-sync:begin reporting -->
## Reporting a vulnerability

Report privately through GitHub's private vulnerability reporting: the
repository's **Security** tab, then **Report a vulnerability**. If that is
not available, open an issue that only asks for a private contact, and put
no vulnerability details in it. This is a research project maintained on a
best-effort basis: expect an acknowledgement within a few days, not an SLA.
<!-- org-sync:end reporting -->

## Verifying what it ships

Nothing is released yet. The Claude Code plugin starts this server at the
commit `swarm-routing/skills` pins in `swarm-mcp.lock`; compare `git log`
of this repository up to that commit before moving the pin.
