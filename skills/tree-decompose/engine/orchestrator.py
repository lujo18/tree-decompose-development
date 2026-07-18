#!/usr/bin/env python3
"""Main orchestrator for the Tree Decompose Development Engine.

Reads the ledger, dispatches isolated builder subagents, runs diagnostics,
and repairs failed nodes until the project is complete.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from . import ledger as ledger_mod
from . import dispatcher, diagnostics, expander, security


class Orchestrator:
    def __init__(
        self,
        package_root: Path,
        ledger_path: Path,
        contracts_path: Path,
        outputs_root: Path,
        project_root: Path,
        diagnostic_command: Optional[str] = None,
        max_retries: int = 3,
        parallel: int = 1,
        dry_run: bool = False,
    ) -> None:
        self.package_root = Path(package_root)
        self.ledger_path = Path(ledger_path)
        self.contracts_path = Path(contracts_path)
        self.outputs_root = Path(outputs_root)
        self.project_root = Path(project_root)
        self.diagnostic_command = diagnostic_command
        self.max_retries = max_retries
        self.parallel = max(1, parallel)
        self.dry_run = dry_run
        self.use_shell = False
        self._ledger_lock = threading.Lock()

        self.prompt_builder = dispatcher.PromptBuilder(
            self.package_root / "config",
            self.contracts_path,
        )
        self.cmd_builder = dispatcher.OpenCodeCommandBuilder(self.package_root, dry_run=dry_run)

        # Validate that persona config files are readable JSON.
        for persona in ("architect", "builder", "validator", "integrator"):
            try:
                self.prompt_builder.load_persona(persona)
            except Exception as exc:
                raise RuntimeError(f"Failed to load persona '{persona}': {exc}") from exc

    def load_ledger(self) -> ledger_mod.Ledger:
        if not self.ledger_path.exists():
            raise FileNotFoundError(f"Ledger not found: {self.ledger_path}")
        ledger = ledger_mod.Ledger.load(self.ledger_path)
        if ledger.has_circular_dependency():
            raise ValueError("Ledger contains a circular dependency")
        return ledger

    def save_ledger(self, ledger: ledger_mod.Ledger) -> None:
        if self.dry_run:
            return
        with self._ledger_lock:
            ledger.save(self.ledger_path)

    def write_source(self, node: ledger_mod.Node, code: str) -> None:
        """Write generated code to outputs mirror and real project path."""
        if self.dry_run:
            return
        output_path = security.resolve_within_root(self.outputs_root, node.path)
        project_path = security.resolve_within_root(self.project_root, node.path)
        for target in (output_path, project_path):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code, encoding="utf-8")

    def _extract_code(self, output_path: Path, stdout: str) -> str | None:
        """Return generated code from disk or stdout."""
        if output_path.exists():
            return output_path.read_text(encoding="utf-8")
        stripped = stdout.strip()
        if stripped:
            # Remove markdown fences if the subagent used them despite instructions.
            if stripped.startswith("```"):
                lines = stripped.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                return "\n".join(lines)
            return stripped
        return None

    def _plan_tree_summary(self, ledger: ledger_mod.Ledger, node: ledger_mod.Node) -> str:
        """Minimal context: ancestors and direct children of this node."""
        ancestors = [ledger.nodes[a].path for a in ledger.ancestors(node.id) if a in ledger.nodes]
        children = [
            ledger.nodes[c].path
            for c in ledger.nodes
            if ledger.nodes[c].parent_id == node.id
        ]
        lines: list[str] = []
        if ancestors:
            lines.append("Ancestors: " + " -> ".join(reversed(ancestors)))
        if children:
            lines.append("Direct children: " + ", ".join(children))
        if not lines:
            lines.append("Leaf node.")
        return "\n".join(lines)

    def dispatch_builder(self, node: ledger_mod.Node, ledger: ledger_mod.Ledger) -> tuple[bool, str]:
        summary = self._plan_tree_summary(ledger, node)
        prompt = self.prompt_builder.builder_prompt(node, plan_tree_summary=summary)
        code_path = security.resolve_within_root(self.outputs_root, node.path)
        command = self.cmd_builder.run_subagent_command(
            persona="builder",
            prompt=prompt,
            node_id=node.id,
            output_path=code_path,
        )

        if self.dry_run:
            print(f"[DRY-RUN] Would execute:\n{command}")
            return True, ""

        try:
            result = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            success = result.returncode == 0
            logs = f"{result.stdout}\n{result.stderr}".strip()
            if success:
                code = self._extract_code(code_path, result.stdout)
                if code is not None:
                    self.write_source(node, code)
                else:
                    success = False
                    logs = "Subagent succeeded but produced no code output."
            return success, logs
        except Exception as exc:
            return False, str(exc)

    def dispatch_validator(self, node: ledger_mod.Node, diagnostic_output: str) -> tuple[bool, str]:
        prompt = self.prompt_builder.validator_prompt(node, diagnostic_output)
        code_path = security.resolve_within_root(self.outputs_root, node.path)
        command = self.cmd_builder.run_subagent_command(
            persona="validator",
            prompt=prompt,
            node_id=node.id,
            output_path=code_path,
        )

        if self.dry_run:
            print(f"[DRY-RUN] Would repair {node.id}:\n{command}")
            return True, ""

        try:
            result = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            success = result.returncode == 0
            logs = f"{result.stdout}\n{result.stderr}".strip()
            if success:
                code = self._extract_code(code_path, result.stdout)
                if code is not None:
                    self.write_source(node, code)
                else:
                    success = False
                    logs = "Validator succeeded but produced no code output."
            return success, logs
        except Exception as exc:
            return False, str(exc)

    def _process_single_node(
        self, node: ledger_mod.Node, ledger: ledger_mod.Ledger
    ) -> tuple[str, bool, str]:
        """Process one node and return (node_id, success, logs)."""
        with self._ledger_lock:
            ledger.update_status(node.id, ledger_mod.STATUS_PROCESSING)
            self.save_ledger(ledger)
        success, logs = self.dispatch_builder(node, ledger)
        with self._ledger_lock:
            if success:
                ledger.update_status(node.id, ledger_mod.STATUS_COMPLETED)
            else:
                ledger.update_status(
                    node.id,
                    ledger_mod.STATUS_FAILED,
                    error_log=logs,
                    increment_retry=True,
                )
            self.save_ledger(ledger)
        return node.id, success, logs

    def run_execution_phase(self, ledger: ledger_mod.Ledger) -> ledger_mod.Ledger:
        print("[*] Starting execution phase...")
        iteration = 0
        executor = ThreadPoolExecutor(max_workers=self.parallel) if self.parallel > 1 else None
        pending_futures: dict = {}

        def collect_batch() -> list[ledger_mod.Node]:
            with self._ledger_lock:
                processing_ids = {
                    nid for nid, n in ledger.nodes.items() if n.status == ledger_mod.STATUS_PROCESSING
                }
                return [
                    n
                    for n in ledger.ready_batch(max_size=self.parallel)
                    if not any(dep in processing_ids for dep in n.dependencies)
                ][: self.parallel]

        try:
            while True:
                # If there are futures in flight, block until at least one completes.
                if pending_futures:
                    for fut in as_completed(pending_futures):
                        node_id = pending_futures.pop(fut)
                        _, success, logs = fut.result()
                        if success:
                            print(f"    [OK] {node_id}")
                        else:
                            print(f"    [FAIL] {node_id}: {logs[:500]}")
                        break

                # Replenish worker pool with independent runnable nodes.
                if executor and len(pending_futures) < self.parallel:
                    batch = collect_batch()
                    for node in batch:
                        iteration += 1
                        print(f"[{iteration}] Queued {node.id} ({node.path}) depth={node.depth_level}")
                        fut = executor.submit(self._process_single_node, node, ledger)
                        pending_futures[fut] = node.id

                # Sequential fallback when no work is in flight.
                if not pending_futures:
                    with self._ledger_lock:
                        node = ledger.next_runnable()
                    if not node:
                        print(f"[+] No runnable nodes after {iteration} iterations.")
                        break

                    iteration += 1
                    print(f"[{iteration}] Processing {node.id} ({node.path}) depth={node.depth_level}")
                    _, success, logs = self._process_single_node(node, ledger)
                    if success:
                        print(f"    [OK] {node.id}")
                    else:
                        print(f"    [FAIL] {node.id}: {logs[:500]}")
                    time.sleep(0.05)
        finally:
            if executor:
                executor.shutdown(wait=True, cancel_futures=True)
        return ledger

    def run_diagnostics_phase(self, ledger: ledger_mod.Ledger) -> ledger_mod.Ledger:
        if not self.diagnostic_command:
            self.diagnostic_command = diagnostics.suggested_diagnostic_command(self.project_root)
        print(f"[*] Running diagnostics: {self.diagnostic_command}")

        success, affected_nodes, logs = diagnostics.run_diagnostics(
            self.diagnostic_command,
            ledger,
            self.project_root,
            shell=self.use_shell,
        )
        logs = security.sanitize_prompt_text(logs)
        if success:
            print("[+] Diagnostics passed.")
            return ledger

        print(f"[!] Diagnostics failed. Affected nodes: {len(affected_nodes)}")
        for node in affected_nodes:
            if node.retry_count >= self.max_retries:
                print(f"    [SKIP] {node.id} exceeded max retries.")
                continue
            print(f"    [REPAIR] {node.id}")
            ledger.update_status(node.id, ledger_mod.STATUS_PROCESSING)
            self.save_ledger(ledger)
            safe_logs = security.sanitize_prompt_text(logs)
            success, repair_logs = self.dispatch_validator(node, safe_logs)
            if success:
                ledger.update_status(node.id, ledger_mod.STATUS_COMPLETED)
                node.error_log = None
            else:
                ledger.update_status(
                    node.id,
                    ledger_mod.STATUS_FAILED,
                    error_log=repair_logs[:4000],
                    increment_retry=True,
                )
            self.save_ledger(ledger)
        return ledger

    def run(self) -> int:
        ledger = self.load_ledger()
        current_hash = security.hash_file(self.contracts_path)
        if ledger.contracts_hash and ledger.contracts_hash != current_hash:
            print(
                "[!] WARNING: contracts file has changed since the ledger was created. "
                "Builders may produce code that no longer matches current contracts. "
                "Consider regenerating the ledger or resetting contracts_hash."
            )
        else:
            ledger.contracts_hash = current_hash
            self.save_ledger(ledger)

        print(f"[*] Loaded ledger: {ledger.project_name}")
        print(f"    nodes={len(ledger.nodes)} depth={ledger.max_depth()}")

        if not ledger.is_complete():
            ledger = self.run_execution_phase(ledger)

        # Keep running diagnostics+repair until no nodes remain failed/retryable
        for repair_round in range(self.max_retries + 1):
            failed = ledger.failed_nodes()
            if not failed or all(n.retry_count >= self.max_retries for n in failed):
                break
            print(f"[*] Diagnostics/repair round {repair_round + 1}")
            ledger = self.run_diagnostics_phase(ledger)

        self.save_ledger(ledger)
        stats = ledger.statistics()
        print("\n[+] Final ledger statistics:")
        for status, count in stats.items():
            print(f"    {status}: {count}")

        if ledger.is_complete():
            print("[++] Tree decomposition complete.")
            return 0
        else:
            print("[!!] Tree decomposition incomplete. Check ledger for failed nodes.")
            return 1


def reset_ledger(ledger_path: Path) -> None:
    """Reset every node in the ledger to idle."""
    if not ledger_path.exists():
        raise FileNotFoundError(f"Ledger not found: {ledger_path}")
    ledger = ledger_mod.Ledger.load(ledger_path)
    for node in ledger.nodes.values():
        node.status = ledger_mod.STATUS_IDLE
        node.error_log = None
        node.retry_count = 0
    ledger.save(ledger_path)
    print(f"[+] Reset ledger: {ledger_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tree Decompose Development Engine")
    default_root = Path(__file__).resolve().parent.parent
    parser.add_argument("--ledger", type=Path, default=default_root / "state" / "ledger.json")
    parser.add_argument("--contracts", type=Path, default=default_root / "docs" / "contracts.ts")
    parser.add_argument("--outputs", type=Path, default=default_root / "outputs")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--diagnostic", default=None, help="Diagnostic shell command")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--shell", action="store_true", help="Allow shell syntax in --diagnostic (security warning)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true", help="Reset ledger to idle and exit")
    args = parser.parse_args(argv)

    if args.reset:
        reset_ledger(args.ledger)
        return 0

    package_root = Path(__file__).resolve().parent.parent
    orch = Orchestrator(
        package_root=package_root,
        ledger_path=args.ledger,
        contracts_path=args.contracts,
        outputs_root=args.outputs,
        project_root=args.project_root,
        diagnostic_command=args.diagnostic,
        max_retries=args.max_retries,
        parallel=args.parallel,
        dry_run=args.dry_run,
    )
    orch.use_shell = args.shell
    return orch.run()


if __name__ == "__main__":
    sys.exit(main())
