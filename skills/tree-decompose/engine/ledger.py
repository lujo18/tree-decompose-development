"""Ledger I/O, schema validation, and dependency-graph operations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


STATUS_IDLE = "idle"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

VALID_STATUSES = {STATUS_IDLE, STATUS_PROCESSING, STATUS_COMPLETED, STATUS_FAILED, STATUS_SKIPPED}
VALID_KINDS = {"contract", "implementation", "test", "doc", "configuration", "reasoning"}
VALID_TYPES = {"domain", "service", "module", "file", "functional_block", "test", "data_structure", "directory"}

VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
DEFAULT_EFFORT = "high"


@dataclass
class Node:
    id: str
    path: str
    depth_level: int
    parent_id: Optional[str]
    type: str
    kind: str
    dependencies: list[str] = field(default_factory=list)
    contract_signatures: list[str] = field(default_factory=list)
    description: str = ""
    status: str = STATUS_IDLE
    error_log: Optional[str] = None
    retry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    thinking_path: Optional[str] = None
    effort: str = DEFAULT_EFFORT

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{self.status}' for node {self.id}")
        if self.kind not in VALID_KINDS:
            raise ValueError(f"Invalid kind '{self.kind}' for node {self.id}")
        if self.type not in VALID_TYPES:
            raise ValueError(f"Invalid type '{self.type}' for node {self.id}")
        if self.effort not in VALID_EFFORTS:
            raise ValueError(
                f"Invalid effort '{self.effort}' for node {self.id}; "
                f"must be one of {sorted(VALID_EFFORTS)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "depth_level": self.depth_level,
            "parent_id": self.parent_id,
            "type": self.type,
            "kind": self.kind,
            "dependencies": self.dependencies,
            "contract_signatures": self.contract_signatures,
            "description": self.description,
            "status": self.status,
            "error_log": self.error_log,
            "retry_count": self.retry_count,
            "metadata": self.metadata,
            "thinking_path": self.thinking_path,
            "effort": self.effort,
        }

    def is_path_safe(self) -> bool:
        """Check the node path for directory traversal patterns."""
        from . import security

        try:
            security.sanitize_relative_path(self.path)
            return True
        except ValueError:
            return False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Node":
        return cls(
            id=data["id"],
            path=data["path"],
            depth_level=data["depth_level"],
            parent_id=data.get("parent_id"),
            type=data["type"],
            kind=data.get("kind", "implementation"),
            dependencies=list(data.get("dependencies", [])),
            contract_signatures=list(data.get("contract_signatures", [])),
            description=data.get("description", ""),
            status=data.get("status", STATUS_IDLE),
            error_log=data.get("error_log"),
            retry_count=data.get("retry_count", 0),
            metadata=dict(data.get("metadata", {})),
            thinking_path=data.get("thinking_path"),
            effort=data.get("effort", DEFAULT_EFFORT),
        )

    @property
    def is_reasoning_required(self) -> bool:
        """True if this node should trigger the thinking phase.

        Gating rule: explicit reasoning nodes, OR contract nodes with 3+
        downstream dependents.
        """
        if self.kind == "reasoning":
            return True
        # Dependent count check is up to the ledger; this only signals kind-based
        # triggering. Caller combines the two.
        return False

    @property
    def is_terminal(self) -> bool:
        return self.status in {STATUS_COMPLETED, STATUS_FAILED, STATUS_SKIPPED}


class Ledger:
    def __init__(
        self,
        project_name: str,
        project_scope: str,
        nodes: list[Node],
        contracts_hash: str = "",
    ) -> None:
        self.project_name = project_name
        self.project_scope = project_scope
        self.nodes = {n.id: n for n in nodes}
        self.contracts_hash = contracts_hash
        self._validate_dependencies()

    def _validate_dependencies(self) -> None:
        ids = set(self.nodes.keys())
        for node in self.nodes.values():
            if not node.is_path_safe():
                raise ValueError(f"Node {node.id} has unsafe path: {node.path}")
            for dep in node.dependencies:
                if dep not in ids:
                    raise ValueError(f"Node {node.id} depends on unknown node {dep}")
                # Prevent circular dependencies of length 1.
                if dep == node.id:
                    raise ValueError(f"Node {node.id} depends on itself")

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        nodes = [Node.from_dict(n) for n in data.get("nodes", [])]
        return cls(
            project_name=data.get("project_name", "untitled"),
            project_scope=data.get("project_scope", ""),
            nodes=nodes,
            contracts_hash=data.get("contracts_hash", ""),
        )

    def save(self, path: str | Path, backup: bool = True, max_backups: int = 3) -> None:
        path = Path(path)
        os.makedirs(path.parent, exist_ok=True)
        data = {
            "project_name": self.project_name,
            "project_scope": self.project_scope,
            "contracts_hash": self.contracts_hash,
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        if backup and path.exists():
            import time

            backup_path = path.parent / f"{path.stem}.backup.{int(time.time())}.json"
            os.replace(path, backup_path)
            self._rotate_backups(path, max_backups)
        os.replace(tmp, path)

    def _rotate_backups(self, path: Path, max_backups: int) -> None:
        backups = sorted(path.parent.glob(f"{path.stem}.backup.*.json"))
        while len(backups) > max_backups:
            backups.pop(0).unlink(missing_ok=True)

    def next_runnable(self) -> Optional[Node]:
        """Return the next idle node whose dependencies are all completed.

        Prefers lower depth levels first and stable ordering by id.
        """
        completed = {nid for nid, n in self.nodes.items() if n.status == STATUS_COMPLETED}
        candidates = [
            n
            for n in self.nodes.values()
            if n.status == STATUS_IDLE and all(dep in completed for dep in n.dependencies)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda n: (n.depth_level, n.id))
        return candidates[0]

    def ready_batch(self, max_size: int = 4) -> list[Node]:
        """Return up to max_size runnable nodes that are mutually independent."""
        completed = {nid for nid, n in self.nodes.items() if n.status == STATUS_COMPLETED}
        candidates = [
            n
            for n in self.nodes.values()
            if n.status == STATUS_IDLE and all(dep in completed for dep in n.dependencies)
        ]
        candidates.sort(key=lambda n: (n.depth_level, n.id))
        selected: list[Node] = []
        selected_ids: set[str] = set()
        for node in candidates:
            if len(selected) >= max_size:
                break
            # ensure no candidate depends on another candidate
            if node.dependencies and any(dep in selected_ids for dep in node.dependencies):
                continue
            selected.append(node)
            selected_ids.add(node.id)
        return selected

    def update_status(
        self,
        node_id: str,
        status: str,
        error_log: Optional[str] = None,
        increment_retry: bool = False,
        max_error_length: int = 4000,
    ) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status {status}")
        node = self.nodes[node_id]
        node.status = status
        if error_log is not None:
            if len(error_log) > max_error_length:
                error_log = error_log[:max_error_length] + "\n...[truncated]"
            node.error_log = error_log
        if increment_retry:
            node.retry_count += 1

    def failed_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.status == STATUS_FAILED]

    def incomplete_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.status not in {STATUS_COMPLETED, STATUS_SKIPPED}]

    def is_complete(self) -> bool:
        return all(n.status == STATUS_COMPLETED for n in self.nodes.values())

    def has_circular_dependency(self) -> bool:
        """Detect any cycle in the dependency graph using DFS."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in self.nodes}

        def dfs(nid: str) -> bool:
            color[nid] = GRAY
            for dep in self.nodes[nid].dependencies:
                if color[dep] == GRAY:
                    return True
                if color[dep] == WHITE and dfs(dep):
                    return True
            color[nid] = BLACK
            return False

        for nid in self.nodes:
            if color[nid] == WHITE and dfs(nid):
                return True
        return False

    def is_failed_stuck(self, max_retries: int = 3) -> bool:
        """True if no node is idle and at least one failed node exceeded retries."""
        has_idle = any(n.status == STATUS_IDLE for n in self.nodes.values())
        if has_idle:
            return False
        return any(
            n.status == STATUS_FAILED and n.retry_count >= max_retries
            for n in self.nodes.values()
        )

    def statistics(self) -> dict[str, int]:
        stats: dict[str, int] = {s: 0 for s in VALID_STATUSES}
        for n in self.nodes.values():
            stats[n.status] += 1
        return stats

    def ancestors(self, node_id: str) -> list[str]:
        """Return parent chain up to root."""
        chain: list[str] = []
        current = self.nodes.get(node_id)
        seen: set[str] = set()
        while current and current.parent_id and current.parent_id not in seen:
            chain.append(current.parent_id)
            seen.add(current.parent_id)
            current = self.nodes.get(current.parent_id)
        return chain

    def descendants(self, node_id: str) -> list[str]:
        """Return all child node ids recursively."""
        result: list[str] = []
        stack = [node_id]
        while stack:
            current_id = stack.pop()
            children = [n.id for n in self.nodes.values() if n.parent_id == current_id]
            result.extend(children)
            stack.extend(children)
        return result

    def layer(self, depth_level: int) -> list[Node]:
        return [n for n in self.nodes.values() if n.depth_level == depth_level]

    def max_depth(self) -> int:
        if not self.nodes:
            return 0
        return max(n.depth_level for n in self.nodes.values())

    def dependent_count(self, node_id: str) -> int:
        """Count of nodes that directly depend on the given node."""
        return sum(1 for n in self.nodes.values() if node_id in n.dependencies)

    def reasoning_required_nodes(self) -> list[Node]:
        """Nodes that must produce a thinking artifact before execution.

        Gating rule: explicit reasoning kind, OR contract kind with >= 3
        direct dependents. Ordering is by depth then id so the thinker
        processes ancestors before descendants.
        """
        result = [
            n
            for n in self.nodes.values()
            if n.kind == "reasoning"
            or (n.kind == "contract" and self.dependent_count(n.id) >= 3)
        ]
        result.sort(key=lambda n: (n.depth_level, n.id))
        return result
