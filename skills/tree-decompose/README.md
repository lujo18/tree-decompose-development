# Tree Decompose Development Engine

**Repository:** https://github.com/lujo18/tree-decompose-development

A self-contained OpenCode Skill that recursively decomposes a single user prompt into plans, sub-plans, and concrete code files. It uses a local state ledger to track progress across multi-layer branch depths and dispatches isolated subagents so lightweight models (e.g. Kimi K3, Fable) can build complex systems without context drift.

## Install

Install directly from GitHub with the `skills` CLI:

```bash
npx skills add lujo18/tree-decompose-development --skill tree-decompose
```

Or install globally:

```bash
npx skills add lujo18/tree-decompose-development --skill tree-decompose -g
```

## What it does

- **Prompt → recursive plan tree** using an Architect subagent.
- **Immutable contracts** written to `docs/contracts.*` before any implementation starts.
- **State ledger** at `state/ledger.json` makes the run interruptible, resumable, and backed up.
- **Isolated builder subagents** implement one file/functional block at a time.
- **Diagnostics & self-healing** loops run project tooling and dispatch Validator repair agents.
- **Optional Integrator** wires everything together.
- **Parallel builders** for independent nodes (`--parallel N`).
- **Security defaults**: path traversal protection, safe diagnostic execution, prompt sanitization, circular-dependency detection, contract-drift detection.

## Manual install

Copy or symlink this entire folder into your project's OpenCode skills path:

```bash
# From your project root:
mkdir -p .opencode/skills
cp -r skills/tree-decompose .opencode/skills/
```

Then start OpenCode. The skill will appear in the native `skill` tool list.

## Quick start

Invoke from inside OpenCode:

```markdown
@general load skill tree-decompose. Implement end-to-end: "Build a state-driven multi-agent viral app factory with Discord login, project templates, deployment hooks, and Stripe billing." Run recursively until all ledger nodes are completed and diagnostics pass.
```

Or run the local engine directly:

```bash
python .agents/skills/tree-decompose/tree-decompose.py --dry-run
```

Pass a diagnostic command:

```bash
python .agents/skills/tree-decompose/tree-decompose.py \
  --diagnostic "npx tsc --noEmit" \
  --project-root . \
  --parallel 2
```

Reset the ledger to start fresh:

```bash
python .agents/skills/tree-decompose/tree-decompose.py --reset
```

Use `--shell` only if your diagnostic command requires shell features (not recommended):

```bash
python .agents/skills/tree-decompose/tree-decompose.py \
  --diagnostic "npx tsc --noEmit | head -20" \
  --shell
```

## Package layout

```text
.agents/skills/tree-decompose/
├── SKILL.md              # Skill definition consumed by OpenCode
├── README.md             # This file
├── tree-decompose.py     # CLI entrypoint
├── tree-decompose        # POSIX wrapper
├── tree-decompose.bat    # Windows wrapper
├── requirements.txt      # No external deps by default
├── config/               # Subagent personas
│   ├── architect.json
│   ├── builder.json
│   ├── validator.json
│   └── integrator.json
├── engine/               # State machine + helpers
│   ├── orchestrator.py
│   ├── ledger.py
│   ├── dispatcher.py
│   ├── spawn_subagent.py
│   ├── diagnostics.py
│   ├── expander.py
│   └── security.py
├── docs/                 # Contracts and plan tree
│   ├── contracts.ts
│   └── plan_tree.md
├── state/                # Live execution ledger
│   └── ledger.json
├── outputs/              # Generated files before integration
└── tests/                # Smoke tests
    └── test_engine.py
```

## How the phases work

1. **Bootstrap**: create the package structure if missing.
2. **Horizon Scan**: infer stack, conventions, and required depth.
3. **Architect** writes global contracts and decomposes the prompt into a ledger.
4. **Builder** loop picks the next runnable `idle` node, locks it, and generates code.
5. **Diagnostics** runs tooling and maps errors to nodes.
6. **Validator** repair loop fixes failing nodes.
7. **Integrator** handles cross-node imports and barrel exports.

## State ledger schema

See `state/ledger.json` for a populated example. Every node has:

- `id`, `path`, `depth_level`, `parent_id`
- `type`, `kind`, `dependencies`
- `contract_signatures`, `description`
- `status` (`idle | processing | completed | failed | skipped`)
- `error_log`, `retry_count`

## Constraints

- Subagents see only contracts + their own node context.
- The ledger is rewritten atomically after every state change; timestamped backups are kept.
- A builder edits exactly one target path; paths cannot escape the project root.
- Contracts win over implementation; violations are repaired, not renegotiated.
- Diagnostic commands are split and executed without a shell unless `--shell` is explicitly enabled.

## Security notes

- **Path traversal**: All `node.path` values are validated; `..`, absolute paths, and root writes are rejected.
- **Shell injection**: Diagnostic commands are tokenized with `shlex` and run without a shell by default. Use `--shell` only for trusted commands.
- **Prompt injection**: Diagnostic logs are sanitized (control characters removed, truncated) before being passed to Validator subagents.
- **Persona validation**: All persona JSON files are loaded and validated at startup.
- **Contract drift**: A SHA-256 hash of `docs/contracts.*` is stored in the ledger; the orchestrator warns if contracts change mid-run.

## Extending

- Add new personas in `config/`.
- Modify `engine/diagnostics.py` for project-specific tooling.
- Adjust depth heuristics in `SKILL.md` Phase 0.

## License

MIT
