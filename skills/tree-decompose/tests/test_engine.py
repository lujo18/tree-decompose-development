"""Smoke tests for the Tree Decompose engine."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add package root to path.
package_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(package_root))

from engine import ledger as ledger_mod
from engine import expander, security


class SecurityTests(unittest.TestCase):
    def test_sanitize_relative_path_rejects_traversal(self) -> None:
        with self.assertRaises(ValueError):
            security.sanitize_relative_path("../foo.ts")

    def test_sanitize_relative_path_rejects_absolute(self) -> None:
        with self.assertRaises(ValueError):
            security.sanitize_relative_path("/etc/passwd")

    def test_resolve_within_root(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        target = security.resolve_within_root(root, "src/foo.ts")
        self.assertTrue(str(target).startswith(str(root)))

    def test_resolve_within_root_rejects_escape(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        with self.assertRaises(ValueError):
            security.resolve_within_root(root, "../foo.ts")

    def test_validate_shell_command_blocks_metacharacters(self) -> None:
        with self.assertRaises(ValueError):
            security._validate_shell_command("npx tsc; rm -rf /")

    def test_sanitize_prompt_text_removes_control_chars(self) -> None:
        cleaned = security.sanitize_prompt_text("error\x00\x1b[31m")
        self.assertNotIn("\x00", cleaned)
        self.assertNotIn("\x1b", cleaned)


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.ledger_path = Path(self.tmp) / "ledger.json"
        data = {
            "project_name": "test",
            "project_scope": "test scope",
            "nodes": [
                {
                    "id": "node_000",
                    "path": "src/types.ts",
                    "depth_level": 1,
                    "parent_id": None,
                    "type": "file",
                    "kind": "contract",
                    "dependencies": [],
                    "contract_signatures": [],
                    "description": "",
                    "status": "idle",
                },
                {
                    "id": "node_001",
                    "path": "src/util.ts",
                    "depth_level": 2,
                    "parent_id": "node_000",
                    "type": "file",
                    "kind": "implementation",
                    "dependencies": ["node_000"],
                    "contract_signatures": [],
                    "description": "",
                    "status": "idle",
                },
                {
                    "id": "node_002",
                    "path": "src/feature.ts",
                    "depth_level": 2,
                    "parent_id": "node_000",
                    "type": "file",
                    "kind": "implementation",
                    "dependencies": ["node_000", "node_001"],
                    "contract_signatures": [],
                    "description": "",
                    "status": "idle",
                },
            ],
        }
        self.ledger_path.write_text(json.dumps(data), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def test_load_and_next_runnable(self) -> None:
        ld = ledger_mod.Ledger.load(self.ledger_path)
        nxt = ld.next_runnable()
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.id, "node_000")

    def test_execution_order(self) -> None:
        ld = ledger_mod.Ledger.load(self.ledger_path)
        order: list[str] = []
        while True:
            nxt = ld.next_runnable()
            if not nxt:
                break
            ld.update_status(nxt.id, ledger_mod.STATUS_COMPLETED)
            order.append(nxt.id)
        self.assertEqual(order, ["node_000", "node_001", "node_002"])

    def test_save_and_reload(self) -> None:
        ld = ledger_mod.Ledger.load(self.ledger_path)
        ld.update_status("node_000", ledger_mod.STATUS_COMPLETED)
        ld.save(self.ledger_path)
        ld2 = ledger_mod.Ledger.load(self.ledger_path)
        self.assertEqual(ld2.nodes["node_000"].status, ledger_mod.STATUS_COMPLETED)

    def test_statistics(self) -> None:
        ld = ledger_mod.Ledger.load(self.ledger_path)
        stats = ld.statistics()
        self.assertEqual(stats["idle"], 3)

    def test_ancestors_and_descendants(self) -> None:
        ld = ledger_mod.Ledger.load(self.ledger_path)
        self.assertEqual(ld.ancestors("node_002"), ["node_000"])
        self.assertEqual(sorted(ld.descendants("node_000")), ["node_001", "node_002"])

    def test_circular_dependency_detection(self) -> None:
        data = {
            "project_name": "bad",
            "project_scope": "",
            "nodes": [
                {
                    "id": "a",
                    "path": "a.ts",
                    "depth_level": 1,
                    "parent_id": None,
                    "type": "file",
                    "kind": "implementation",
                    "dependencies": ["b"],
                    "status": "idle",
                },
                {
                    "id": "b",
                    "path": "b.ts",
                    "depth_level": 1,
                    "parent_id": None,
                    "type": "file",
                    "kind": "implementation",
                    "dependencies": ["a"],
                    "status": "idle",
                },
            ],
        }
        bad_path = Path(self.tmp) / "bad.json"
        bad_path.write_text(json.dumps(data), encoding="utf-8")
        ld = ledger_mod.Ledger.load(bad_path)
        self.assertTrue(ld.has_circular_dependency())

    def test_unsafe_path_rejected(self) -> None:
        data = json.loads(self.ledger_path.read_text())
        data["nodes"][0]["path"] = "../escape.ts"
        bad_path = Path(self.tmp) / "unsafe.json"
        bad_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            ledger_mod.Ledger.load(bad_path)


class ExpanderTests(unittest.TestCase):
    def test_flatten_tree(self) -> None:
        tree = {
            "id": "root",
            "path": "src",
            "type": "directory",
            "kind": "contract",
            "children": [
                {
                    "id": "child",
                    "path": "src/a.ts",
                    "type": "file",
                    "kind": "implementation",
                }
            ],
        }
        nodes = expander.flatten_tree(tree)
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[1].parent_id, "root")
        self.assertEqual(nodes[1].depth_level, 1)


class ReasoningLayerTests(unittest.TestCase):
    """Tests for the reasoning artifact, effort dial, and context deflation."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_reasoning_kind_valid(self) -> None:
        node = ledger_mod.Node(
            id="r1",
            path="src/reason.ts",
            depth_level=1,
            parent_id=None,
            type="file",
            kind="reasoning",
        )
        self.assertEqual(node.kind, "reasoning")

    def test_invalid_effort_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ledger_mod.Node(
                id="n1",
                path="src/a.ts",
                depth_level=1,
                parent_id=None,
                type="file",
                kind="implementation",
                effort="ultra",
            )

    def test_thinking_path_and_effort_roundtrip(self) -> None:
        node = ledger_mod.Node(
            id="n1",
            path="src/a.ts",
            depth_level=1,
            parent_id=None,
            type="file",
            kind="implementation",
            thinking_path=".decompose/thinking/n1.yaml",
            effort="xhigh",
        )
        d = node.to_dict()
        self.assertEqual(d["thinking_path"], ".decompose/thinking/n1.yaml")
        self.assertEqual(d["effort"], "xhigh")
        restored = ledger_mod.Node.from_dict(d)
        self.assertEqual(restored.thinking_path, ".decompose/thinking/n1.yaml")
        self.assertEqual(restored.effort, "xhigh")

    def test_reasoning_required_nodes_gating(self) -> None:
        """Only reasoning-kind nodes OR contracts with >=3 dependents trigger."""
        data = {
            "project_name": "test",
            "project_scope": "",
            "nodes": [
                {
                    "id": "root_contract",
                    "path": "src/types.ts",
                    "depth_level": 1,
                    "parent_id": None,
                    "type": "file",
                    "kind": "contract",
                    "dependencies": [],
                },
                {
                    "id": "impl_a",
                    "path": "src/a.ts",
                    "depth_level": 2,
                    "parent_id": "root_contract",
                    "type": "file",
                    "kind": "implementation",
                    "dependencies": ["root_contract"],
                },
                {
                    "id": "impl_b",
                    "path": "src/b.ts",
                    "depth_level": 2,
                    "parent_id": "root_contract",
                    "type": "file",
                    "kind": "implementation",
                    "dependencies": ["root_contract"],
                },
                {
                    "id": "impl_c",
                    "path": "src/c.ts",
                    "depth_level": 2,
                    "parent_id": "root_contract",
                    "type": "file",
                    "kind": "implementation",
                    "dependencies": ["root_contract"],
                },
                {
                    "id": "explicit_reasoning",
                    "path": "src/reason.ts",
                    "depth_level": 1,
                    "parent_id": None,
                    "type": "file",
                    "kind": "reasoning",
                    "dependencies": [],
                },
                {
                    "id": "low_dep_contract",
                    "path": "src/low.ts",
                    "depth_level": 1,
                    "parent_id": None,
                    "type": "file",
                    "kind": "contract",
                    "dependencies": [],
                },
            ],
        }
        ledger_path = Path(self.tmp) / "ledger.json"
        ledger_path.write_text(json.dumps(data), encoding="utf-8")
        ld = ledger_mod.Ledger.load(ledger_path)
        targets = ld.reasoning_required_nodes()
        ids = [n.id for n in targets]
        self.assertIn("root_contract", ids)  # contract with 3 dependents
        self.assertIn("explicit_reasoning", ids)  # explicit reasoning kind
        self.assertNotIn("low_dep_contract", ids)  # contract with 0 dependents
        self.assertNotIn("impl_a", ids)  # implementation node

    def test_dependent_count(self) -> None:
        data = {
            "project_name": "test",
            "project_scope": "",
            "nodes": [
                {"id": "a", "path": "a.ts", "depth_level": 1, "parent_id": None, "type": "file", "kind": "contract"},
                {"id": "b", "path": "b.ts", "depth_level": 2, "parent_id": "a", "type": "file", "kind": "implementation", "dependencies": ["a"]},
                {"id": "c", "path": "c.ts", "depth_level": 2, "parent_id": "a", "type": "file", "kind": "implementation", "dependencies": ["a"]},
            ],
        }
        ledger_path = Path(self.tmp) / "ledger.json"
        ledger_path.write_text(json.dumps(data), encoding="utf-8")
        ld = ledger_mod.Ledger.load(ledger_path)
        self.assertEqual(ld.dependent_count("a"), 2)
        self.assertEqual(ld.dependent_count("b"), 0)

    def test_thinking_artifact_parsing(self) -> None:
        from engine import dispatcher

        yaml_text = """node_id: n1
target_path: src/a.ts
selected: B
rationale: B handles the edge case better.
invariants:
  - "TTL <= 5 min"
  - "No blocking I/O"
verdict: proceed
"""
        art = dispatcher.ThinkingArtifact.from_text(yaml_text)
        self.assertEqual(art.selected, "B")
        self.assertIn("TTL", art.invariants[0])
        self.assertEqual(art.verdict, "proceed")

    def test_builder_prompt_excludes_candidates(self) -> None:
        """When thinking_path is set, builder sees selected + invariants, never candidates."""
        from engine import dispatcher

        # Create a fake thinking artifact
        thinking_dir = Path(self.tmp) / "thinking"
        thinking_dir.mkdir()
        art_path = thinking_dir / "n1.yaml"
        art_path.write_text(
            "node_id: n1\nselected: A\nrationale: test\ninvariants:\n  - \"inv1\"\nverdict: proceed\n",
            encoding="utf-8",
        )

        # Create a node with thinking_path set
        node = ledger_mod.Node(
            id="n1",
            path="src/a.ts",
            depth_level=1,
            parent_id=None,
            type="file",
            kind="implementation",
            thinking_path=str(art_path),
        )

        # Create contracts file
        contracts_path = Path(self.tmp) / "contracts.ts"
        contracts_path.write_text("export interface Foo {}", encoding="utf-8")

        builder = dispatcher.PromptBuilder(Path(self.tmp) / "config", contracts_path, thinking_dir)
        # Need a persona file
        config_dir = Path(self.tmp) / "config"
        config_dir.mkdir()
        (config_dir / "builder.json").write_text(
            json.dumps({"system_prompt": "test builder"}), encoding="utf-8"
        )

        prompt = builder.builder_prompt(node)
        # Should contain the selected approach and invariants
        self.assertIn("AUTHORITATIVE DECISION", prompt)
        self.assertIn("selected: A" if False else "Selected approach: A", prompt)
        self.assertIn("inv1", prompt)
        # Should NOT contain candidate exploration
        self.assertNotIn("candidates", prompt.lower())

    def test_effort_language_injection(self) -> None:
        from engine import dispatcher

        builder = dispatcher.PromptBuilder(Path(self.tmp) / "config", None, None)
        line = builder._effort_line("xhigh")
        self.assertIn("xhigh", line)
        self.assertIn("multistep reasoning", line.lower())
        line_low = builder._effort_line("low")
        self.assertIn("low", line_low)
        self.assertIn("directly", line_low.lower())


if __name__ == "__main__":
    unittest.main()
