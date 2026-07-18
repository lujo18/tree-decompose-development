"""Construct isolated prompts and dispatch subagents via OpenCode tools.

This module is intentionally thin: it builds prompts and emits commands that
OpenCode can execute. It does not try to call a private OpenCode API; instead
it relies on the standard `task` or `bash` tooling the host agent already has.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Optional

from . import security
from .ledger import Node


class PromptBuilder:
    def __init__(self, config_dir: Path, contracts_path: Optional[Path] = None) -> None:
        self.config_dir = Path(config_dir)
        self.contracts_path = contracts_path
        self._personas: dict[str, dict[str, Any]] = {}

    def load_persona(self, name: str) -> dict[str, Any]:
        if name in self._personas:
            return self._personas[name]
        path = self.config_dir / f"{name}.json"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._personas[name] = data
        return data

    def contracts_text(self) -> str:
        if self.contracts_path and self.contracts_path.exists():
            return self.contracts_path.read_text(encoding="utf-8")
        return "// No global contracts file found."

    def architect_prompt(
        self,
        user_prompt: str,
        stack: str,
        depth: int,
        existing_context: str = "",
    ) -> str:
        contracts_sample = self.contracts_text()
        return f"""{self.load_persona('architect').get('system_prompt', '')}

USER REQUEST:
{user_prompt}

STACK: {stack}
TARGET LAYER DEPTH: {depth}

EXISTING PROJECT CONTEXT (summarize only, do not copy code):
{existing_context or 'None provided.'}

CURRENT CONTRACTS SNIPPET:
{contracts_sample[:1200]}

TASK:
1. Produce or update the global contracts file with shared types, interfaces, schemas, public API signatures, and module-level dependency map.
2. Produce a recursive plan tree using the node schema below.
3. Output a JSON object matching this exact shape (no markdown fences):

{{
  "contracts": "full file contents as a string",
  "nodes": [
    {{
      "id": "node_001",
      "path": "src/services/auth/session.ts",
      "depth_level": 3,
      "parent_id": null,
      "type": "file",
      "kind": "implementation",
      "dependencies": ["node_000"],
      "contract_signatures": ["export function validateSession(token: string): Promise<User | null>"],
      "description": "Implement session validation using the shared User type.",
      "status": "idle",
      "error_log": null,
      "retry_count": 0,
      "metadata": {{}}
    }}
  ],
  "plan_tree_md": "markdown outline of the decomposition"
}}

EXPANSION RULE:
If a node is still a plan (not a single file/function/type), expand it into children before execution. Continue until every leaf is one of: file, functional_block, test, data_structure. Contract nodes must precede implementations that depend on them."""

    def builder_prompt(self, node: Node, plan_tree_summary: str = "") -> str:
        persona = self.load_persona("builder").get("system_prompt", "")
        contracts = self.contracts_text()
        sigs = "\n".join(f"- {s}" for s in node.contract_signatures) or "- (no signatures provided; follow contracts)"
        return f"""{persona}

GLOBAL CONTRACTS:
{contracts}

NODE ID: {node.id}
TARGET FILE PATH: {node.path}
NODE TYPE: {node.type}
NODE KIND: {node.kind}
DESCRIPTION: {node.description}

TARGET SIGNATURES / ENTITIES TO IMPLEMENT:
{sigs}

PLAN TREE CONTEXT:
{plan_tree_summary or '[Plan tree summary not provided]'}

TASK:
Implement ONLY this node. Write complete, correct, production-ready code that matches the contracts and signatures above. Do not write markdown explanations. Do not implement sibling functionality. Do not add unauthorized dependencies. Output raw source code that can be written directly to disk."""

    def validator_prompt(self, node: Node, diagnostic_output: str) -> str:
        persona = self.load_persona("validator").get("system_prompt", "")
        contracts = self.contracts_text()
        return f"""{persona}

GLOBAL CONTRACTS:
{contracts}

NODE ID: {node.id}
TARGET FILE PATH: {node.path}
DESCRIPTION: {node.description}

DIAGNOSTIC OUTPUT:
{diagnostic_output}

TASK:
Fix ONLY the errors shown in the diagnostic output for this file. Preserve all other behavior. Do not modify sibling files or global contracts. Output the corrected raw source code."""

    def integrator_prompt(self, node_ids: list[str], ledger_summary: str) -> str:
        persona = self.load_persona("integrator").get("system_prompt", "")
        contracts = self.contracts_text()
        return f"""{persona}

GLOBAL CONTRACTS:
{contracts}

NODES TO WIRE TOGETHER:
{chr(10).join(node_ids)}

LEDGER SUMMARY:
{ledger_summary}

TASK:
Add or correct imports, barrel exports, dependency injection wiring, and index files so the implemented nodes form a coherent project. Do not change implementation logic. Output raw source code for any new or modified integration files."""


class OpenCodeCommandBuilder:
    """Build commands the OpenCode host can run to dispatch subagents.

    Since there is no public OpenCode RPC API at the time of writing, we emit
    shell commands that use `opencode` if available, or instruct the host to
    call `task` subagents. The orchestrator can also operate in a 'dry_run'
    mode where it writes prompts to disk instead of spawning processes.
    """

    def __init__(self, package_root: Path, dry_run: bool = False) -> None:
        self.package_root = Path(package_root)
        self.dry_run = dry_run

    def run_subagent_command(
        self,
        persona: str,
        prompt: str,
        node_id: str,
        output_path: Optional[Path] = None,
        timeout_ms: int = 120000,
    ) -> str:
        """Return a shell command string.

        In a real OpenCode session the host agent would prefer to use the
        native `task` tool. This fallback uses a small Python helper that
        writes the prompt and (in dry-run mode) a placeholder response.
        """
        # Write prompt to a temp location so the subagent or reviewer can inspect it.
        suffix = output_path.stem if output_path else "node"
        safe_id = security.sanitize_prompt_text(node_id.replace("_", "-"))
        prompt_file = self.package_root / ".prompts" / f"{persona}_{safe_id}_{suffix}.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt, encoding="utf-8")

        if self.dry_run:
            return f"# DRY RUN: prompt written to {prompt_file}\n# Persona: {persona}\n# Output target: {output_path}"

        # Prefer a helper script invocation. The script will call `task` subagent or `opencode query`.
        helper = self.package_root / "engine" / "spawn_subagent.py"
        args = [
            "python",
            str(helper),
            "--persona", persona,
            "--prompt-file", str(prompt_file),
            "--package-root", str(self.package_root),
        ]
        if output_path:
            args.extend(["--output", str(output_path)])
        args.extend(["--timeout", str(timeout_ms)])
        return " ".join(shlex.quote(a) for a in args)


