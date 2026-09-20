# Install into the project

The pack is designed for Claude Code's current project configuration model.

Copy these items into the repository root:

- `CLAUDE.md` -> replace the current minimal root `CLAUDE.md` after backing it up if desired.
- `.claude/agents/` -> add the four project-specific subagents.
- `PROMPTS.md` -> optional reference; does not affect runtime by itself.
- `PROJECT_ANALYSIS.md` -> optional project note.

The existing `frontend/CLAUDE.md` that imports `@AGENTS.md` can remain. It is useful because `frontend/AGENTS.md` contains the important warning to consult the installed Next.js documentation before editing Next.js-specific code.

After creating `.claude/agents/` for the first time, restart Claude Code once if the current session was already open. Current Claude Code documentation notes that a newly-created agents directory may require a restart for the first discovery.

Recommended first command from the repository root:

```bash
claude
```

Then paste the “Recommended First Prompt” from `PROMPTS.md`.
