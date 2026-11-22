# CONTEXT.md — orientation and history

Background an agent or a new contributor needs that does not belong in
`AGENTS.md`: domain notes, current state, glossary, open questions. Read the
section a task needs, not the whole file.

## Current state

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

Moved from swarm-routing/skills on 2026-11-22 (maintainer decision: "configure
the MCP repo out of skills ... Skills and MCP repo need to work together";
swarm-routing/skills#185, swarm-routing/.github#672), where it was prototyped
in swarm-routing/skills#187. The design and the move: `docs/adr/0002`.

## Glossary

- **MCP**: the Model Context Protocol; a client (an agent) calls a server's
  named tools with typed arguments.
- **org-tool**: `tools/swarm-mcp/org-tool`, which finds a swarm-routing/.github
  script and runs it; the server's only way to the org scripts.
- **the pin**: the commit of this repository the skills plugin runs,
  `swarm-mcp.lock` in swarm-routing/skills.

## Open questions
