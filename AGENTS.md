# Agent Instructions

@RTK.md

This repository uses `RTK.md` as the working guide for AI coding agents.

Before making code changes, read:

1. `RTK.md`
2. `docs/14-terminal-commands.md`
3. The smallest relevant domain doc under `docs/`

Keep changes scoped, verify with tests/build when possible, and do not rewrite unrelated project history or user edits.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

Use the relevant global GitNexus skill in `C:\Users\ndtha\.agents\skills` when
exploring, debugging, planning, reviewing, or changing this codebase.

- Query GitNexus before broad text searches when tracing concepts or execution flows.
- Run impact analysis before editing a function, class, or method.
- Treat `UNKNOWN` impact as unresolved and confirm it with targeted source searches.
- Run `gitnexus detect-changes --scope all --repo .` before committing.
- Run `gitnexus status` and re-analyze when the index is stale.

<!-- gitnexus:end -->
