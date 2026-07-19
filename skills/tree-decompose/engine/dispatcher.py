"""Construct isolated prompts and dispatch subagents via OpenCode tools.

This module is intentionally thin: it builds prompts and emits commands that
OpenCode can execute. It does not try to call a private OpenCode API; instead
it relies on the standard `task` or `bash` tooling the host agent already has.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any, Optional

from . import security
from .ledger import Node, DEFAULT_EFFORT, VALID_EFFORTS


# Effort language tokens injected into persona prompts, drawn from Anthropic's
# documented adaptive-thinking steering phrases. Empty string means no injection.
EFFORT_LANGUAGE = {
    "low": "Answer directly without deliberating. Skip exploration.",
    "medium": "",  # default behavior
    "high": "",  # default
    "xhigh": "This task involves multistep reasoning. Think carefully before responding.",
    "max": "This task requires the deepest possible reasoning and most thorough analysis. Explore every implication before committing.",
}


def _parse_yaml_lite(text: str) -> dict[str, Any]:
    """Minimal YAML parser for thinking artifacts.

    Handles the fixed thinking.yaml schema: top-level scalar keys, list-valued
    keys (pros/cons/edge_cases/invariants), and nested maps (evaluation.scores).
    """
    result: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line or line.startswith("#"):
            i += 1
            continue
        # Top-level key
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2)
        if val:
            val = val.split(" #")[0].strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            result[key] = _coerce(val)
            i += 1
            continue
        # key with no value — could be a list or a nested map
        # Peek ahead to determine type
        if i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            if next_stripped.startswith("- "):
                # It's a list
                items: list[Any] = []
                j = i + 1
                while j < len(lines):
                    item_line = lines[j].strip()
                    if not item_line.startswith("- "):
                        break
                    item_val = item_line[2:].split(" #")[0].strip()
                    if item_val.startswith('"') and item_val.endswith('"'):
                        item_val = item_val[1:-1]
                    items.append(_coerce(item_val))
                    j += 1
                result[key] = items
                i = j
                continue
            elif next_stripped.startswith("-"):
                # bare dash with space after
                items = []
                j = i + 1
                while j < len(lines):
                    item_line = lines[j].strip()
                    if not item_line.startswith("-"):
                        break
                    item_val = item_line[1:].strip().split(" #")[0].strip()
                    if item_val.startswith('"') and val.endswith('"'):
                        item_val = item_val[1:-1]
                    items.append(_coerce(item_val))
                    j += 1
                result[key] = items
                i = j
                continue
            else:
                # It's a nested map — parse key: value lines at deeper indent
                nested: dict[str, Any] = {}
                base_indent = len(lines[i + 1]) - len(lines[i + 1].lstrip())
                j = i + 1
                while j < len(lines):
                    raw_j = lines[j]
                    if not raw_j.strip() or raw_j.strip().startswith("#"):
                        j += 1
                        continue
                    indent_j = len(raw_j) - len(raw_j.lstrip())
                    if indent_j < base_indent:
                        break
                    # could be a key: value, a key: {inline}, or a sub-list
                    inner = raw_j.strip()
                    inline_m = re.match(r"^(\w+):\s*\{(.+)\}$", inner)
                    if inline_m:
                        label, body = inline_m.group(1), inline_m.group(2)
                        inner_dict: dict[str, Any] = {}
                        for piece in body.split(","):
                            if ":" in piece:
                                k2, v2 = piece.split(":", 1)
                                inner_dict[k2.strip()] = _coerce(v2.strip())
                        nested[label] = inner_dict
                        j += 1
                        continue
                    kv_m = re.match(r"^(\w+):\s*(.*)$", inner)
                    if kv_m:
                        k2, v2 = kv_m.group(1), kv_m.group(2)
                        if v2:
                            v2 = v2.split(" #")[0].strip()
                            if v2.startswith('"') and v2.endswith('"'):
                                v2 = v2[1:-1]
                            nested[k2] = _coerce(v2)
                            j += 1
                        else:
                            # sub-list under this key
                            sub_items: list[Any] = []
                            k = j + 1
                            while k < len(lines) and lines[k].strip().startswith("- "):
                                sv = lines[k].strip()[2:].split(" #")[0].strip()
                                if sv.startswith('"') and sv.endswith('"'):
                                    sv = sv[1:-1]
                                sub_items.append(_coerce(sv))
                                k += 1
                            nested[k2] = sub_items
                            j = k
                        continue
                    # could be a list item inside the map
                    if inner.startswith("- "):
                        # This is a list item under a sub-key; handled above
                        j += 1
                        continue
                    j += 1
                result[key] = nested
                i = j
                continue
        i += 1
    return result


def _coerce(val: str) -> Any:
    if val.lower() in {"true", "false"}:
        return val.lower() == "true"
    if val.lower() == "null":
        return None
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    if re.fullmatch(r"-?\d+\.\d+", val):
        return float(val)
    return val


class ThinkingArtifact:
    """Parsed view of a thinking.yaml artifact.

    Only the fields builders/validators need are exposed. The full text is
    retained for hashing and audit.
    """

    __slots__ = ("selected", "rationale", "invariants", "verdict", "recompose_target", "raw")

    def __init__(
        self,
        selected: str = "",
        rationale: str = "",
        invariants: Optional[list[str]] = None,
        verdict: str = "proceed",
        recompose_target: Optional[str] = None,
        raw: str = "",
    ) -> None:
        self.selected = selected
        self.rationale = rationale
        self.invariants = invariants or []
        self.verdict = verdict
        self.recompose_target = recompose_target
        self.raw = raw

    @classmethod
    def from_text(cls, text: str) -> "ThinkingArtifact":
        data = _parse_yaml_lite(text)
        return cls(
            selected=str(data.get("selected", "")),
            rationale=str(data.get("rationale", "")),
            invariants=list(data.get("invariants") or []),
            verdict=str(data.get("verdict", "proceed") or "proceed"),
            recompose_target=data.get("target_node_id"),
            raw=text,
        )

    @classmethod
    def from_path(cls, path: Path) -> Optional["ThinkingArtifact"]:
        if not path or not Path(path).exists():
            return None
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_text(text)


class PromptBuilder:
    def __init__(
        self,
        config_dir: Path,
        contracts_path: Optional[Path] = None,
        thinking_dir: Optional[Path] = None,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.contracts_path = contracts_path
        self.thinking_dir = Path(thinking_dir) if thinking_dir else None
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

    def _effort_line(self, effort: str) -> str:
        if effort not in VALID_EFFORTS:
            effort = DEFAULT_EFFORT
        lang = EFFORT_LANGUAGE.get(effort, "")
        return f"\nEFFORT: {effort}\n{lang}\n" if lang else f"\nEFFORT: {effort}\n"

    def thinking_artifact_path(self, node: Node) -> Optional[Path]:
        if not node.thinking_path:
            return None
        return Path(node.thinking_path)

    def load_thinking(self, node: Node) -> Optional[ThinkingArtifact]:
        path = self.thinking_artifact_path(node)
        return ThinkingArtifact.from_path(path) if path else None

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

        # Context deflation: if this node has a thinking artifact, inject ONLY
        # the selected approach + rationale + invariants. Never the candidates.
        # This emulates Fable's summarized-not-raw-CoT pattern.
        thinking = self.load_thinking(node)
        if thinking is not None:
            inv_list = "\n".join(f"- {inv}" for inv in thinking.invariants) or "- (no invariants emitted)"
            thinking_block = f"""
AUTHORITATIVE DECISION (from thinking.yaml):
Selected approach: {thinking.selected}
Rationale: {thinking.rationale}

INVARIANTS (hard contract; implementation MUST satisfy each):
{inv_list}

The decision above is authoritative. Do not substitute alternatives. If the
approach is genuinely infeasible, halt and report rather than improvising.
"""
        else:
            thinking_block = ""

        return f"""{persona}{self._effort_line(node.effort)}

GLOBAL CONTRACTS:
{contracts}
{thinking_block}
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

    def thinking_prompt(self, node: Node, plan_tree_summary: str = "") -> str:
        """Build the divergent thinker prompt for a reasoning node."""
        persona = self.load_persona("thinker").get("system_prompt", "")
        contracts = self.contracts_text()
        sigs = "\n".join(f"- {s}" for s in node.contract_signatures) or "- (no signatures provided; infer from contracts and description)"
        return f"""{persona}{self._effort_line(node.effort)}

GLOBAL CONTRACTS:
{contracts}

NODE ID: {node.id}
TARGET FILE PATH: {node.path}
NODE TYPE: {node.type}
NODE KIND: {node.kind}
DESCRIPTION: {node.description}

TARGET SIGNATURES / ENTITIES TO ADDRESS:
{sigs}

PLAN TREE CONTEXT:
{plan_tree_summary or '[Plan tree summary not provided]'}

TASK:
Produce exactly 3 structurally distinct candidate approaches for this node. Each
candidate must be a fundamentally different approach, not a variant of the same
idea with renamed pieces.

Output ONLY valid JSON matching this schema (no markdown fences, no preamble):

{{
  "candidates": [
    {{
      "id": "A",
      "approach": "one sentence describing the fundamental approach",
      "pros": ["concrete pro 1", "concrete pro 2"],
      "cons": ["concrete con 1"],
      "edge_cases": ["specific scenario that would expose this choice as wrong"]
    }},
    {{
      "id": "B",
      "approach": "...",
      "pros": ["..."],
      "cons": ["..."],
      "edge_cases": ["..."]
    }},
    {{
      "id": "C",
      "approach": "...",
      "pros": ["..."],
      "cons": ["..."],
      "edge_cases": ["..."]
    }}
  ]
}}"""

    def critic_prompt(self, node: Node, candidates_json: str) -> str:
        """Build the convergent critic prompt for a reasoning node's candidates."""
        persona = self.load_persona("critic").get("system_prompt", "")
        contracts = self.contracts_text()
        return f"""{persona}{self._effort_line(node.effort)}

GLOBAL CONTRACTS:
{contracts}

NODE ID: {node.id}
TARGET FILE PATH: {node.path}
DESCRIPTION: {node.description}

CANDIDATES FROM THE THINKER:
{candidates_json}

TASK:
Score each candidate on five axes (1-10): correctness, simplicity, fit,
edge_coverage, dependency_cost. Enumerate failure modes for each. Select
exactly one. Emit checkable invariants (2-6) that any implementation must
satisfy. If all three are fundamentally flawed, emit verdict=re-decompose with
target_node_id.

Output ONLY valid YAML matching this schema (no markdown fences, no preamble):

node_id: {node.id}
target_path: {node.path}
selected: <A|B|C>
rationale: "one paragraph explaining the tradeoff that drove selection"
evaluation:
  axes: [correctness, simplicity, fit, edge_coverage, dependency_cost]
  scores:
    A: {{correctness: 8, simplicity: 9, fit: 7, edge_coverage: 5, dependency_cost: 8}}
    B: {{correctness: 7, simplicity: 5, fit: 9, edge_coverage: 8, dependency_cost: 4}}
    C: {{correctness: 9, simplicity: 6, fit: 8, edge_coverage: 9, dependency_cost: 6}}
  failure_modes_per_candidate:
    A:
      - "specific failure mode"
    B:
      - "specific failure mode"
    C:
      - "specific failure mode"
invariants:
  - "checkable assertion 1"
  - "checkable assertion 2"
verdict: proceed
"""


    def validator_prompt(self, node: Node, diagnostic_output: str) -> str:
        persona = self.load_persona("validator").get("system_prompt", "")
        contracts = self.contracts_text()

        # Inject invariants as first-class checks alongside diagnostics.
        # This makes the thinking artifact authoritative at repair time too.
        thinking = self.load_thinking(node)
        if thinking is not None and thinking.invariants:
            inv_list = "\n".join(f"- {inv}" for inv in thinking.invariants)
            invariants_block = f"""
INVARIANTS (from thinking.yaml; treat as hard checks):
{inv_list}

A violation of any invariant above is a contract breach, distinct from a
diagnostic error. If diagnostics pass but an invariant is violated, report
the invariant violation explicitly.
"""
        else:
            invariants_block = ""

        return f"""{persona}{self._effort_line(node.effort)}

GLOBAL CONTRACTS:
{contracts}
{invariants_block}
NODE ID: {node.id}
TARGET FILE PATH: {node.path}
DESCRIPTION: {node.description}

DIAGNOSTIC OUTPUT:
{diagnostic_output}

TASK:
Fix ONLY the errors shown in the diagnostic output for this file. Also verify
that the resulting code satisfies all invariants above (if any). Preserve all
other behavior. Do not modify sibling files or global contracts. Output the
corrected raw source code."""


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

    def __init__(
        self, package_root: Path, prompts_dir: Optional[Path] = None, dry_run: bool = False
    ) -> None:
        self.package_root = Path(package_root)
        self.dry_run = dry_run
        self.prompts_dir = Path(prompts_dir) if prompts_dir else self.package_root / ".decompose" / "prompts"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)

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
        # Write prompt to the consolidated workspace prompts directory.
        suffix = output_path.stem if output_path else "node"
        safe_id = security.sanitize_prompt_text(node_id.replace("_", "-"))
        prompt_file = self.prompts_dir / f"{persona}_{safe_id}_{suffix}.txt"
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


