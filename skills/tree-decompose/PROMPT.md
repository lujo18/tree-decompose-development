# Ready-to-Paste Prompt

For the `tree-decompose` skill from https://github.com/lujo18/tree-decompose-development.

Copy and paste this into OpenCode to trigger the Tree Decompose Development Engine on any feature request.

## Default invocation

```markdown
@general load skill tree-decompose. Implement the following end-to-end: "YOUR FEATURE DESCRIPTION HERE". Run recursively through all ledger nodes, enforce the global contracts, dispatch isolated builder subagents per node, run diagnostics, and repair any failures until every node is completed.
```

## Example

```markdown
@general load skill tree-decompose. Implement the following end-to-end: "Build a state-driven multi-agent viral app factory with Discord login, reusable project templates, Vercel deployment hooks, and Stripe billing subscriptions. Use TypeScript, Next.js App Router, and React Server Components where appropriate." Run recursively until all ledger nodes are completed and diagnostics pass.
```

## Variations

### With explicit diagnostic command and parallel builders

```markdown
@general load skill tree-decompose. Implement: "...". Run recursively with up to 3 parallel builder subagents for independent nodes. Use the diagnostic command "npx tsc --noEmit" after every execution phase and repair type errors until zero remain.
```

### Reset + fresh run

If you want to wipe the current ledger and start over:

```bash
python .agents/skills/tree-decompose/tree-decompose.py --reset
```

### Manual run without OpenCode skill loading

```bash
python .agents/skills/tree-decompose/tree-decompose.py --dry-run
python .agents/skills/tree-decompose/tree-decompose.py --diagnostic "npx tsc --noEmit" --parallel 3
```

Use `--shell` only if a diagnostic command requires shell syntax (not recommended):

```bash
python .agents/skills/tree-decompose/tree-decompose.py --diagnostic "npx tsc --noEmit | head" --shell
```
