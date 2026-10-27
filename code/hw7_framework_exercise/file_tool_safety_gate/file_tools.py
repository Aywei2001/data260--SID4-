import difflib
import shutil
import subprocess
from pathlib import Path

from .safety_gate import confirm_bash


def _result(success, data=None, error=None):
    return {"success": success, "data": data, "error": error}


def _resolve_inside_sandbox(sandbox_dir, file_path):
    root = Path(sandbox_dir).resolve()
    requested = Path(file_path)

    target = requested.resolve() if requested.is_absolute() else (root / requested).resolve()

    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError("Requested path is outside the sandbox.") from error

    return root, target


def _validate_pattern(file_pattern):
    pattern = Path(file_pattern)

    if pattern.is_absolute() or ".." in pattern.parts:
        raise ValueError("File pattern must be relative and stay inside the sandbox.")

    return file_pattern


def read_file(sandbox_dir, file_path, max_lines=100):
    #read a file, returning at most max_lines lines by default
    try:
        _, target = _resolve_inside_sandbox(sandbox_dir, file_path)

        if not target.is_file():
            return _result(False, error="File does not exist.")

        if max_lines is not None and max_lines < 1:
            return _result(False, error="max_lines must be positive or None.")

        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        shown = lines if max_lines is None else lines[:max_lines]

        return _result(True, {
            "path": str(target),
            "content": "".join(shown),
            "lines_returned": len(shown),
            "truncated": len(shown) < len(lines),
        })
    except (OSError, ValueError) as error:
        return _result(False, error=str(error))


def write_file(sandbox_dir, file_path, content):
    #create or replace a UTF-8 text file inside the sandbox
    try:
        root, target = _resolve_inside_sandbox(sandbox_dir, file_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        #check again after creating parent directories.
        _, target = _resolve_inside_sandbox(root, target)
        target.write_text(content, encoding="utf-8")

        return _result(True, {
            "path": str(target),
            "bytes_written": len(content.encode("utf-8")),
        })
    except (OSError, ValueError) as error:
        return _result(False, error=str(error))


def edit_file(sandbox_dir, file_path, old_text, new_text):
    #replace one unique text occurrence and return a short unified diff
    try:
        _, target = _resolve_inside_sandbox(sandbox_dir, file_path)

        if not target.is_file():
            return _result(False, error="File does not exist.")

        original = target.read_text(encoding="utf-8")
        occurrences = original.count(old_text)

        if occurrences == 0:
            return _result(False, error="Text to replace was not found.")
        if occurrences > 1:
            return _result(
                False,
                error="Text to replace appears more than once; make it unique first.",
            )

        updated = original.replace(old_text, new_text, 1)
        diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=str(target),
            tofile=str(target),
        ))

        target.write_text(updated, encoding="utf-8")

        #keep the returned diff short
        diff_lines = diff.splitlines()
        if len(diff_lines) > 40:
            diff = "\n".join(diff_lines[:40]) + "\n... diff shortened ..."

        return _result(True, {"path": str(target), "diff": diff})
    except (OSError, ValueError) as error:
        return _result(False, error=str(error))


def glob_files(sandbox_dir, file_pattern):
    #find files matching a relative pattern, such as '**/*.py'
    try:
        root = Path(sandbox_dir).resolve()
        pattern = _validate_pattern(file_pattern)
        matches = []

        for candidate in root.glob(pattern):
            resolved = candidate.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue

            if resolved.is_file():
                matches.append(str(resolved.relative_to(root)))

        return _result(True, {"files": sorted(matches)})
    except (OSError, ValueError) as error:
        return _result(False, error=str(error))


def search_in_files(sandbox_dir, file_pattern, search_text):
    #search matching files and return each matching line and line number
    try:
        root = Path(sandbox_dir).resolve()
        pattern = _validate_pattern(file_pattern)
        matches = []

        for candidate in root.glob(pattern):
            resolved = candidate.resolve()

            try:
                relative_path = resolved.relative_to(root)
            except ValueError:
                continue

            if not resolved.is_file():
                continue

            try:
                lines = resolved.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue

            for line_number, line in enumerate(lines, start=1):
                if search_text in line:
                    matches.append({
                        "path": str(relative_path),
                        "line_number": line_number,
                        "line": line,
                    })

        return _result(True, {"matches": matches})
    except (OSError, ValueError) as error:
        return _result(False, error=str(error))


def bash(command, sandbox_dir, auto_approve=False, timeout=15):
    """Run an allowed bash command with its working directory set to the sandbox."""
    root = Path(sandbox_dir).resolve()
    decision = confirm_bash(command, auto_approve=auto_approve)

    if not decision["allowed"]:
        return _result(False, {
            "allowed": False,
            "reason": decision["reason"],
        }, error=decision["reason"])

    bash_path = shutil.which("bash")
    if not bash_path:
        return _result(False, error="bash was not found on PATH.")

    try:
        completed = subprocess.run(
            [bash_path, "-lc", command],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return _result(completed.returncode == 0, {
            "allowed": True,
            "reason": decision["reason"],
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "returncode": completed.returncode,
        })
    except (OSError, subprocess.TimeoutExpired) as error:
        return _result(False, error=str(error))