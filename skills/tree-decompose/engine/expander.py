"""Helpers for recursive plan expansion and ledger normalization."""

from __future__ import annotations

from .ledger import Node


def flatten_tree(tree: dict, parent_id: str | None = None, depth: int = 0, counter: int = 0) -> list[Node]:
    """Convert a nested dict tree into flat ledger nodes.

    Input tree node (loose schema):
    {
      "id": "node_001",
      "path": "src/services/auth/session.ts",
      "type": "file",
      "kind": "implementation",
      "dependencies": ["node_000"],
      "contract_signatures": [...],
      "description": "...",
      "children": [ {...}, {...} ]
    }
    """
    nodes: list[Node] = []
    children = tree.pop("children", [])
    node = Node(
        id=tree.get("id", f"node_{counter:04d}"),
        path=tree.get("path", ""),
        depth_level=depth,
        parent_id=parent_id,
        type=tree.get("type", "file"),
        kind=tree.get("kind", "implementation"),
        dependencies=list(tree.get("dependencies", [])),
        contract_signatures=list(tree.get("contract_signatures", [])),
        description=tree.get("description", ""),
        status=tree.get("status", "idle"),
        error_log=tree.get("error_log"),
        retry_count=tree.get("retry_count", 0),
        metadata=dict(tree.get("metadata", {})),
    )
    nodes.append(node)
    for idx, child in enumerate(children):
        nodes.extend(flatten_tree(child, parent_id=node.id, depth=depth + 1, counter=counter + idx + 1))
    return nodes


def assign_missing_ids(nodes: list[Node]) -> list[Node]:
    """Ensure every node has a unique id."""
    for idx, node in enumerate(nodes):
        if not node.id:
            node.id = f"node_{idx:04d}"
    return nodes


def normalize_dependencies(nodes: list[Node]) -> list[Node]:
    """Remove self-references and duplicate dependencies."""
    for node in nodes:
        node.dependencies = list(dict.fromkeys(d for d in node.dependencies if d != node.id))
    return nodes


def required_contracts_for_node(node: Node, ledger_nodes: dict[str, Node]) -> list[str]:
    """Collect contract_signatures from dependency contract nodes."""
    signatures: list[str] = []
    for dep_id in node.dependencies:
        dep = ledger_nodes.get(dep_id)
        if dep and dep.kind == "contract":
            signatures.extend(dep.contract_signatures)
    return signatures
