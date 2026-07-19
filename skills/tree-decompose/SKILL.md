---
name: tree-decompose
description: Recursive hierarchical task decomposition engine with preserved reasoning state, effort dial, isolated subagent delegation, and autonomous diagnostics/self-healing for lightweight models.
license: MIT
compatibility: opencode
metadata:
  author: opencode
  domain: agentic-development
  pattern: hierarchical-execution
---

# Tree Decompose Development Engine

## What I do

I transform a single high-level user request into a fully implemented multi-file codebase by recursively decomposing it into plans, sub-plans, and atomic implementation nodes. Before any code is written for decision points, I produce structured reasoning artifacts (thinker → critic) that emulate the adaptive thinking + effort dial of frontier models like Claude Fable, GPT-5, and Kimi K3. All runtime state — ledger, contracts, thinking artifacts, prompts, outputs — lives under a single `.decompose/` workspace.

### Key capabilities

- **Recursive decomposition** from prompt → domains → modules → files → functions → data structures.
- **Reasoning layer**: gated decision nodes produce `thinking.yaml` artifacts with candidates, multi-axis evaluation, selected approach, and checkable invariants.
- **Context deflation**: downstream builders see only the selected approach + invariants, never the candidate exploration. This is the summarized-not-raw-CoT pattern from Fable.
- **Effort dial**: `--effort {low,medium,high,xhigh,max}` controls reasoning depth per node, matching the frontier model pattern.
- **Persisted thinking state**: thinking artifacts are committed to `.decompose/thinking/` and survive across runs, like K3's preserved thinking history.
- **Parallel execution** for independent nodes via `--parallel N`.
- **Security defaults**: no shell execution for diagnostics unless `--shell` is passed; path-traversal protection; prompt sanitization; contract-drift detection.

## When to use me

Use me immediately when the user asks to:

- Build a complex feature or multi-file system.
- Generate a boilerplate, plugin, SDK, or component library.
- Implement anything expected to exceed 300–400 lines of logic or requiring multiple interacting files.
- Produce deeply nested architectures.

Do **not** use me for single-line edits, trivial fixes, or pure questions.

## Package layout

```text
tree-decompose/
├── SKILL.md                 # This file
├── README.md                # Installation and usage guide
├── PROMPT.md                # Ready-to-paste invocation prompts
├── tree-decompose.py        # CLI entrypoint
├── config/                  # Subagent personas (committed)
│   ├── architect.json       # Plan expansion
│   ├── builder.json         # Isolated code generation
│   ├── validator.json       # Diagnostic repair
│   ├── integrator.json      # Cross-node wiring
│   ├── thinker.json         # Divergent candidate generation (temp 0.8)
│   └── critic.json          # Convergent evaluation + invariant emission
├── engine/                  # Code (committed)
│   ├── orchestrator.py      # State machine + reasoning + execution + diagnostics
│   ├── ledger.py            # Ledger I/O, graph ops, reasoning gating
│   ├── dispatcher.py        # Prompt builder + YAML parser + context deflation
│   ├── spawn_subagent.py    # Isolated subagent spawn helper
│   ├── diagnostics.py       # Tooling integration + error-to-node mapping
│   ├── expander.py          # Recursive tree-to-ledger helpers
│   └── security.py          # Path safety + command safety + prompt sanitization
├── tests/                   # Smoke + security + reasoning tests
└── .decompose/               # ALL runtime state (gitignored)
    ├── ledger.json           # Live execution ledger
    ├── contracts.ts          # Global types/interfaces (source of truth)
    ├── plan_tree.md           # Human-readable nested plan
    ├── thinking/              # Reasoning artifacts per decision node
    │   └── <node_id>.yaml
    ├── prompts/               # Prompt files for subagent inspection
    ├── outputs/                # Generated files before project integration
    └── backups/                # Timestamped ledger backups
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

Invoke the **Architect** subagent to write immutable contracts into `.decompose/contracts.*`:

- Shared types, interfaces, schemas.
- Public API signatures.
- Module-level dependency map.
- Invariants and non-goals.

The Architect must not write implementation logic.

### Phase 2 — Recursive Plan Expansion

Invoke the **Architect** again to produce `.decompose/plan_tree.md` and populate `.decompose/ledger.json`.

Ledger node schema:

```json
{
  "id": "node_001",
  "path": "src/services/auth/session.ts",
  "depth_level": 3,
  "parent_id": "node_000",
  "type": "file",
  "kind": "contract | implementation | test | doc | reasoning",
  "dependencies": ["node_000"],
  "contract_signatures": ["export function validateSession(token: string): Promise<User | null>"],
  "description": "Two-sentence requirement.",
  "status": "idle",
  "error_log": null,
  "retry_count": 0,
  "thinking_path": null,
  "effort": "high"
}
```

Expansion rules:

- If a node is still a plan rather than a single file/function, expand it into children before executing it.
- Continue until all leaves are `file`, `functional_block`, `test`, or `data_structure`.
- Contract nodes always precede dependents in dependency order.

### Phase 2.5 — Reasoning (thinker → critic)

For each node where `kind == "reasoning"` OR (`kind == "contract"` AND `len(dependents) >= 3`):

1. **Thinker** persona generates 3 structurally distinct candidate approaches (temp 0.8, primed to disagree).
2. **Critic** persona scores each on 5 axes (correctness, simplicity, fit, edge_coverage, dependency_cost), enumerates failure modes, selects one, and emits 2-6 checkable invariants.
3. The output is written to `.decompose/thinking/<node_id>.yaml`.
4. The node's `thinking_path` field is set in the ledger.

This emulates the adaptive thinking + preserved thinking state of Fable/GPT-5/K3. Low effort (`--effort low`) skips this phase entirely.

**Gating rule**: only decision points get reasoning. Leaf utilities and tests go straight to the builder. This keeps token cost proportional to decision weight.

### Phase 3 — Execution Loop

Run the orchestrator:

```bash
python tree-decompose.py
```

The orchestrator:

1. Loads `.decompose/ledger.json`.
2. Finds the next `idle` node whose dependencies are `completed`.
3. Locks it to `processing`.
4. Builds a minimal prompt from its `contract_signatures`, `description`, global contracts, and — if `thinking_path` is set — the selected approach + invariants from the thinking artifact. Candidate exploration is never included.
5. Dispatches a `@general` subagent using the **Builder** persona.
6. Writes returned code to `.decompose/outputs/<path>` and to the real project path.
7. Marks the node `completed` or `failed`.
8. Persists `ledger.json` after every change.

### Phase 4 — Diagnostics & Self-Healing

Once execution stalls:

1. Run diagnostics (`tsc --noEmit`, `eslint`, `pytest`, `ruff`, etc.) via `bash`.
2. Map failing files back to ledger nodes.
3. For each failing node, set status to `failed`, append logs, and dispatch a **Validator** repair subagent.
4. The validator reads invariants from the thinking artifact (if any) and treats them as first-class checks alongside diagnostic errors.
5. Re-run diagnostics. Loop until all nodes are `completed` and diagnostics pass.

### Phase 5 — Integration (optional)

If cross-node wiring is needed, invoke the **Integrator** subagent to reconcile imports, barrel exports, and DI wiring against `.decompose/contracts.*`.

## Constraints

- **The artifact is the contract**: when a thinking artifact exists, its selected approach and invariants are authoritative. Builders may not deviate even when they "know better." This prevents K3's documented "excessive proactiveness" failure mode.
- **Context deflation**: Subagents see only contracts and their own node. No sibling code. No candidate exploration from thinking artifacts.
- **State persistence**: Rewrite `ledger.json` atomically after every state change; keep timestamped backups.
- **Atomic scope**: A builder edits exactly one node path.
- **Contract supremacy**: Violations are fixed in implementation nodes, not contracts.
- **Resume safety**: Restarting the orchestrator continues from the first `idle` or `failed` node.
- **Path safety**: All generated file paths are resolved inside the project root; `..` and absolute paths are rejected.
- **Command safety**: Diagnostic commands run through `shlex` without a shell unless you explicitly pass `--shell`.
- **Contract drift detection**: The orchestrator hashes contracts at startup and warns if they changed since the ledger was created.
- **Single workspace**: All runtime state lives under `.decompose/`. No scattered directories.

## Invocation

```markdown
@general load skill tree-decompose. Implement the following end-to-end using the tree-decompose engine: "Build a state-driven multi-agent viral app factory with Discord login, project templates, deployment hooks, and Stripe billing." Run recursively until all ledger nodes are completed and diagnostics pass.
```

Manual CLI flags:

```bash
python .agents/skills/tree-decompose/tree-decompose.py --dry-run
python .agents/skills/tree-decompose/tree-decompose.py --effort xhigh --parallel 2
python .agents/skills/tree-decompose/tree-decompose.py --diagnostic "npx tsc --noEmit" --effort max
```
