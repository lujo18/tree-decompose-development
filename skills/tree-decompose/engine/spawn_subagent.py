#!/usr/bin/env python3
"""Spawn an isolated OpenCode subagent for a single node.

This helper is invoked by the orchestrator. It can operate in two modes:

1. Real mode: call `opencode query --silent <prompt>` to execute a standalone
   sub-query against the local OpenCode CLI (if available).
2. Dry-run / test mode: echo the prompt and write a placeholder output file.

If neither mode can produce code, the orchestrator treats the node as failed
and includes the stdout/stderr in the ledger error_log.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from . import security


def write_output(package_root: Path, output_path: Path, content: str) -> None:
    outputs_root = package_root / "outputs"
    safe_path = security.resolve_within_root(outputs_root, output_path)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_text(content, encoding="utf-8")
    return safe_path


def run_opencode_query(prompt: str, timeout: int) -> str:
    opencode = shutil.which("opencode")
    if not opencode:
        raise RuntimeError("`opencode` CLI not found in PATH")
    # `--silent` keeps output clean but may not exist on all versions; we try plain query.
    cmd = [opencode, "query"]
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout / 1000.0,
    )
    if result.returncode != 0:
        raise RuntimeError(f"opencode query failed: {result.stderr}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description="Spawn an isolated OpenCode subagent.")
    parser.add_argument("--persona", required=True)
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=120000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    prompt = args.prompt_file.read_text(encoding="utf-8")

    if args.dry_run:
        placeholder = (
            f"// DRY RUN output for {args.persona}\n"
            f"// Prompt file: {args.prompt_file}\n"
            "// In real mode, this file would contain the subagent's generated code.\n"
        )
        if args.output:
            write_output(args.package_root, args.output, placeholder)
        print(placeholder)
        return 0

    try:
        code = run_opencode_query(prompt, args.timeout)
        if args.output:
            write_output(args.package_root, args.output, code)
        print(code)
        return 0
    except Exception as exc:
        msg = f"Subagent '{args.persona}' failed: {exc}"
        print(msg, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
