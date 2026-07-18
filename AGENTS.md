# Agent Notes

## Tree Decompose Development Engine

This repository contains a self-contained OpenCode Skill at `skills/tree-decompose/` for recursive hierarchical task decomposition.

**Repository:** https://github.com/lujo18/tree-decompose-development

It is installable with `npx skills add lujo18/tree-decompose-development --skill tree-decompose`, or manually by copying `skills/tree-decompose/` to `.opencode/skills/` or `.agents/skills/`. When a user asks to build a complex multi-file feature, load the `tree-decompose` skill and follow its execution protocol.

### What the skill does

- Decomposes a single prompt into plans, sub-plans, and atomic code nodes.
- Maintains global contracts in `docs/contracts.*`.
- Tracks execution state in `state/ledger.json`.
- Dispatches isolated `@general` subagents using the personas in `config/`.
- Runs diagnostics and repairs failing nodes.

### How to run it

From inside OpenCode:

```markdown
@general load skill tree-decompose. Implement the following end-to-end: "YOUR FEATURE DESCRIPTION HERE". Run recursively until all ledger nodes are completed and diagnostics pass.
```

Or manually from the terminal:

```bash
python skills/tree-decompose/tree-decompose.py --dry-run
python skills/tree-decompose/tree-decompose.py --diagnostic "npx tsc --noEmit"
```

### Important conventions

- Keep the skill package self-contained under `skills/tree-decompose/`.
- Do not edit the contract file while implementations are in progress; fix implementations instead.
- Always persist `state/ledger.json` after any node status change.
- Subagents should see only global contracts + their assigned node context.

### Updating this note

If you change the skill structure, personas, ledger schema, or CLI, update both this file and `skills/tree-decompose/README.md`.
