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


if __name__ == "__main__":
    unittest.main()
