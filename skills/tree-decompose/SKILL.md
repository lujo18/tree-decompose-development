---
name: tree-decompose
description: Recursive hierarchical task decomposition engine with local state ledger, multi-layer branching, isolated subagent delegation, and autonomous diagnostics/self-healing for lightweight models.
license: MIT
compatibility: opencode
metadata:
  author: opencode
  domain: agentic-development
  pattern: hierarchical-execution
---

# Tree Decompose Development Engine

## What I do

I transform a single high-level user request into a fully implemented multi-file codebase by recursively decomposing it into plans, sub-plans, and atomic implementation nodes. I use a local state engine to avoid token bloat, track progress across depths, and dispatch isolated `@general` subagents for each leaf. I run diagnostics and self-healing loops until the generated code compiles and matches contracts.

This skill is fully self-contained in the `tree-decompose/` folder. It can be copied manually, installed with `npx skills add <owner>/<repo> --skill tree-decompose`, or used directly from this repo.

### Key capabilities

- **Recursive decomposition** from prompt → domains → modules → files → functions → data structures.
- **Layer-aware branching depth**: 2 layers for simple utilities, 4 for features, 5–6+ for platforms and multi-agent systems.
- **Persistent state ledger** (`state/ledger.json`) with atomic writes, timestamped backups, and resume safety.
- **Dependency-graph execution** ensures parent contracts are written before children implement against them; detects circular dependencies.
- **Isolated subagent delegation** with strict context windows and persona-bound instructions.
- **Native diagnostics integration** (type-checking, linting, tests) with targeted repair passes.
- **File-system orchestration** creates directories, writes files, and integrates outputs into the real project.
- **Parallel execution** for independent nodes via `--parallel N`.
- **Security defaults**: no shell execution for diagnostics unless `--shell` is explicitly passed; path-traversal protection; prompt sanitization; contract drift detection.

## When to use me

Use me immediately when the user asks to:

- Build a complex feature or multi-file system.
- Generate a boilerplate, plugin, SDK, or component library.
- Implement anything expected to exceed 300–400 lines of logic or requiring multiple interacting files.
- Produce deeply nested architectures.

Do **not** use me for single-line edits, trivial fixes, or pure questions.

## Package layout

```text
<skills-path>/tree-decompose/   # e.g. .agents/skills/tree-decompose/ or .opencode/skills/tree-decompose/
├── SKILL.md                 # This file
├── README.md                # Installation and usage guide
├── requirements.txt         # Python dependencies (if any)
├── config/
│   ├── architect.json       # Plan expansion persona
│   ├── builder.json         # Isolated code generation persona
│   ├── validator.json       # Diagnostic repair persona
│   └── integrator.json      # Cross-node wiring persona
├── docs/
│   ├── contracts.ts         # Global types/interfaces
│   └── plan_tree.md         # Human-readable nested plan summary
├── state/
│   └── ledger.json          # Live execution state
├── outputs/                 # Generated files before integration
├── engine/
│   ├── __init__.py
│   ├── orchestrator.py      # State machine and subagent dispatcher
│   ├── ledger.py            # Ledger I/O and graph operations
│   ├── dispatcher.py        # Subagent prompt construction and dispatch
│   ├── diagnostics.py       # Native tooling integration
│   └── expander.py          # Recursive plan expansion helpers
└── tests/
    └── test_engine.py       # Smoke / dry-run tests
```

## Execution Protocol

### Phase 0 — Ingest & Horizon Scan

Read the user's prompt and existing project files. Determine:

- Language/stack.
- Conventions from `AGENTS.md` or existing source.
- Required depth by complexity heuristic:
  - Simple utility/library → 2 layers.
  - Feature with UI + state → 4 layers.
  - Multi-agent / framework / platform → 5–6+ layers.

### Phase 1 — Global Contracts

Invoke the **Architect** subagent to write immutable contracts into `docs/contracts.*`:

- Shared types, interfaces, schemas.
- Public API signatures.
- Module-level dependency map.
- Invariants and non-goals.

The Architect must not write implementation logic.

### Phase 2 — Recursive Plan Expansion

Invoke the **Architect** again to produce `docs/plan_tree.md` and populate `state/ledger.json`.

Ledger node schema:

```json
{
  "id": "node_001",
  "path": "src/services/auth/session.ts",
  "depth_level": 3,
  "parent_id": "node_000",
  "type": "file",
  "kind": "contract | implementation | test | doc",
  "dependencies": ["node_000"],
  "contract_signatures": ["export function validateSession(token: string): Promise<User | null>"],
  "description": "Two-sentence requirement.",
  "status": "idle",
  "error_log": null,
  "retry_count": 0
}
```

Expansion rules:

- If a node is still a plan rather than a single file/function, expand it into children before executing it.
- Continue until all leaves are `file`, `functional_block`, `test`, or `data_structure`.
- Contract nodes always precede dependents in dependency order.

### Phase 3 — Execution Loop

Run the orchestrator:

```bash
python .agents/skills/tree-decompose/engine/orchestrator.py
```

The orchestrator:

1. Loads `state/ledger.json`.
2. Finds the next `idle` node whose dependencies are `completed`.
3. Locks it to `processing`.
4. Builds a minimal prompt from its `contract_signatures`, `description`, and global contracts.
5. Dispatches a `@general` subagent using the **Builder** persona.
6. Writes returned code to `outputs/<path>` and to the real project path.
7. Marks the node `completed` or `failed`.
8. Persists `ledger.json` after every change.

### Phase 4 — Diagnostics & Self-Healing

Once execution stalls:

1. Run diagnostics (`tsc --noEmit`, `eslint`, `pytest`, `ruff`, etc.) via `bash`.
2. Map failing files back to ledger nodes.
3. For each failing node, set status to `failed`, append logs, and dispatch a **Validator** repair subagent.
4. Re-run diagnostics. Loop until all nodes are `completed` and diagnostics pass.

### Phase 5 — Integration (optional)

If cross-node wiring is needed, invoke the **Integrator** subagent to reconcile imports, barrel exports, and DI wiring against `docs/contracts.*`.

## Constraints

- **Context deflation**: Subagents see only contracts and their own node. No sibling code.
- **State persistence**: Rewrite `ledger.json` atomically after every state change; keep timestamped backups.
- **Atomic scope**: A builder edits exactly one node path.
- **Contract supremacy**: Violations are fixed in implementation nodes, not contracts.
- **Resume safety**: Restarting the orchestrator continues from the first `idle` or `failed` node.
- **Path safety**: All generated file paths are resolved inside the project root; `..` and absolute paths are rejected.
- **Command safety**: Diagnostic commands run through `shlex` without a shell unless you explicitly pass `--shell`.
- **Contract drift detection**: The orchestrator hashes contracts at startup and warns if they changed since the ledger was created.

## Invocation

```markdown
@general load skill tree-decompose. Implement the following end-to-end using the tree-decompose engine: "Build a state-driven multi-agent viral app factory with Discord login, project templates, deployment hooks, and Stripe billing." Run recursively until all ledger nodes are completed and diagnostics pass.
```

Manual CLI flags:

```bash
python .agents/skills/tree-decompose/engine/orchestrator.py \
  --ledger .agents/skills/tree-decompose/state/ledger.json \
  --contracts .agents/skills/tree-decompose/docs/contracts.ts \
  --diagnostic "npx tsc --noEmit" \
  --parallel 2
```
