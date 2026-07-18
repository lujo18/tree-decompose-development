# Tree Decompose Development Engine

**Repository:** https://github.com/lujo18/tree-decompose-development

A self-contained OpenCode / agent skill that recursively decomposes a single user prompt into plans, sub-plans, and concrete code files. It uses a local state ledger to track progress across multi-layer branch depths and dispatches isolated subagents so lightweight models can build complex systems without context drift.

## Install with `npx skills`

The easiest way to install this skill into any project is with the open agent skills CLI:

```bash
npx skills add lujo18/tree-decompose-development --skill tree-decompose
```

For OpenCode specifically, it will be placed at `.agents/skills/tree-decompose/` (project) or `~/.config/opencode/skills/tree-decompose/` (global). OpenCode discovers it automatically.

### Install options

```bash
# Global install
npx skills add lujo18/tree-decompose-development --skill tree-decompose -g

# Install to OpenCode only
npx skills add lujo18/tree-decompose-development --skill tree-decompose -a opencode

# Install all skills from this repo
npx skills add lujo18/tree-decompose-development --all
```

## Manual install

Copy or symlink the `skills/tree-decompose/` folder into your project's skill path:

```bash
# OpenCode project-local
mkdir -p .opencode/skills
cp -r skills/tree-decompose .opencode/skills/

# Or any agent-compatible project path
mkdir -p .agents/skills
cp -r skills/tree-decompose .agents/skills/
```

## Usage

OpenCode prompt:

```markdown
@general load skill tree-decompose. Implement the following end-to-end: "YOUR FEATURE DESCRIPTION HERE". Run recursively until all ledger nodes are completed and diagnostics pass.
```

Or run the local engine directly from the installed skill folder:

```bash
python .agents/skills/tree-decompose/tree-decompose.py --dry-run
python .agents/skills/tree-decompose/tree-decompose.py --diagnostic "npx tsc --noEmit" --parallel 2
```

## Repo layout

```text
.
├── README.md              # This file
├── AGENTS.md              # Developer notes for agents working on this repo
└── skills/
    └── tree-decompose/    # The installable skill package
        ├── SKILL.md
        ├── README.md
        ├── PROMPT.md
        ├── tree-decompose.py
        ├── config/
        ├── docs/
        ├── engine/
        ├── state/
        ├── outputs/
        └── tests/
```

## Development

See `skills/tree-decompose/README.md` for detailed architecture, security notes, and extension guides.

## License

MIT
