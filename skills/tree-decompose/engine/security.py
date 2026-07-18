"""Security helpers: path traversal prevention, safe command execution,
prompt sanitization, and contract integrity checks.
"""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
from pathlib import Path
from typing import Optional


PATH_TRAVERSAL_PATTERN = re.compile(r"\.\.(?:/|\\)")
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")


def sanitize_relative_path(path: str | Path, allow_root: bool = False) -> Path:
    """Return a safe Path that cannot escape the project root.

    Rejects paths containing parent directory traversal or absolute paths.
    """
    raw = str(path)
    path = Path(raw)
    # On Windows a POSIX absolute path is not considered absolute, so check explicitly.
    if path.is_absolute() or raw.startswith(("/", "\\")):
        raise ValueError(f"Absolute paths are not allowed: {raw}")
    if PATH_TRAVERSAL_PATTERN.search(path.as_posix()):
        raise ValueError(f"Path traversal detected: {raw}")
    if not allow_root and path in (Path("."), Path("")):
        raise ValueError("Writing to project root directly is not allowed")
    return path


def resolve_within_root(root: Path, relative: str | Path) -> Path:
    """Resolve a relative path and ensure it stays inside root."""
    safe = sanitize_relative_path(relative)
    target = (Path(root) / safe).resolve()
    root_resolved = Path(root).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Resolved path escapes root: {target}") from exc
    return target


def hash_file(path: Path) -> str:
    """Return SHA-256 hex digest of a file, or empty string if missing."""
    if not path or not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def run_command_safely(
    command: str,
    cwd: Optional[Path] = None,
    shell: bool = False,
    timeout: int = 300,
) -> tuple[int, str, str]:
    """Run a command without shell by default; validate if shell=True.

    When shell=False the command is split with shlex. When shell=True the
    command is validated to contain only a safe subset of shell syntax.
    """
    if shell:
        _validate_shell_command(command)
        cmd = command
    else:
        try:
            cmd = shlex.split(command)
        except ValueError as exc:
            return 1, "", f"Failed to parse diagnostic command: {exc}"

    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 1, "", f"Diagnostic command timed out after {timeout}s"
    except FileNotFoundError as exc:
        return 1, "", f"Diagnostic command not found: {exc}"
    return result.returncode, result.stdout, result.stderr


def _validate_shell_command(command: str) -> None:
    """Block obvious shell metacharacters that are unnecessary for diagnostics."""
    banned = {";", "&", "|", "$", "`", "\n", "\r"}
    for ch in banned:
        if ch in command:
            raise ValueError(
                f"Shell metacharacter '{ch}' is not allowed in diagnostic commands. "
                "Use --shell only with trusted commands."
            )


def sanitize_prompt_text(text: str, max_length: int = 20000) -> str:
    """Remove control characters and truncate very long diagnostic outputs."""
    text = CONTROL_CHAR_PATTERN.sub("", text)
    if len(text) > max_length:
        text = text[:max_length] + "\n... [truncated for safety]"
    return text
