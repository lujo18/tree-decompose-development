"""Run project diagnostics and map failures back to ledger nodes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import ledger as ledger_mod, security


def extract_file_paths(text: str, project_root: Path) -> set[Path]:
    r"""Heuristically extract file paths from diagnostic output.

    Matches common error formats:
      - src/foo.ts(12,34)
      - src/foo.ts:12:34
      - C:\path\to\file.ts(12,34)
      - ./src/foo.ts
    """
    paths: set[Path] = set()
    # Components explained:
    #   (?:[A-Za-z]:)?           optional Windows drive letter
    #   [\w./\\@~-]+             relative or absolute path chars (include @ for aliases)
    #   \.                       extension dot
    #   (?:ts|tsx|...)           allowed file extensions
    pattern = re.compile(
        r"((?:[A-Za-z]\:)?[\w./\\@~-]+\.(?:ts|tsx|js|jsx|py|mjs|cjs|java|kt|swift|go|rs|cpp|c|h|hpp))"
        r"(?:(?:\:|\()(\d+)(?:,\s*|\:)(\d+)\)?)?"
    )
    for match in pattern.finditer(text):
        raw = match.group(1)
        candidate = Path(raw)
        if candidate.is_absolute():
            paths.add(candidate)
        else:
            resolved = Path(project_root) / candidate
            if resolved.exists():
                paths.add(resolved)
    return paths


def map_paths_to_nodes(paths: set[Path], ledger: ledger_mod.Ledger, project_root: Path) -> list[ledger_mod.Node]:
    """Return ledger nodes whose path matches any diagnostic file path."""
    normalized = {p.resolve() for p in paths if p.exists()}
    hits: list[ledger_mod.Node] = []
    for node in ledger.nodes.values():
        node_path = (Path(project_root) / node.path).resolve()
        if node_path in normalized:
            hits.append(node)
    return hits


def run_diagnostics(
    command: str,
    ledger: ledger_mod.Ledger,
    project_root: Path,
    shell: bool = False,
) -> tuple[bool, list[ledger_mod.Node], str]:
    """Run diagnostics and return (success, affected_nodes, combined_logs)."""
    rc, stdout, stderr = security.run_command_safely(
        command, cwd=Path(project_root), shell=shell, timeout=300
    )
    combined = f"{stdout}\n{stderr}".strip()
    if rc == 0:
        return True, [], combined

    failure_paths = extract_file_paths(combined, Path(project_root))
    nodes = map_paths_to_nodes(failure_paths, ledger, Path(project_root))
    return False, nodes, combined


def suggested_diagnostic_command(project_root: Path) -> str:
    """Infer a sane default diagnostic command from project files."""
    root = Path(project_root)
    if (root / "tsconfig.json").exists():
        return "npx tsc --noEmit"
    if (root / "package.json").exists():
        return "npm run lint --if-present"
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists() or (root / "requirements.txt").exists():
        return "python -m compileall ."
    if (root / "Cargo.toml").exists():
        return "cargo check"
    return "echo 'No default diagnostic command configured'"
