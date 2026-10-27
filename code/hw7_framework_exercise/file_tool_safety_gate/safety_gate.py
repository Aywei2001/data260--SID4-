import re
import shlex


#safe command forms
SAFE_PREFIXES = (
    ("pwd",),
    ("ls",),
    ("python", "--version"),
    ("git", "--version"),
    ("whoami",),
)

_DESTRUCTIVE_PATTERNS = (
    #recursive deletion
    r"\brm\b.*(?:-r|--recursive)",
    r"\b(?:rmdir|rd|del)\b.*(?:/s|-r|--recursive)",
    r"\bremove-item\b.*-(?:recurse|recursive)",

    #privilege escalation
    r"\b(?:sudo|doas|su|runas|pkexec)\b",

    #permission and ownership changes
    r"\b(?:chmod|chown|chgrp|icacls|takeown)\b",

    #raw-device writes and filesystem operations
    r"\bdd\b.*\bof\s*=\s*/dev/",
    r"\bmkfs(?:\.\w+)?\b",
    r"\b(?:diskpart|format)\b",

    #creating filesystem entries from shell commands
    r"\b(?:mkdir|md|touch|new-item)\b",

    #redirecting output to a root or device path
    r">\s*(?:/|[a-z]:[\\/]|\\\\)",
    r">\s*/dev/",
)


def is_destructive(command: str) -> bool:
    """Return True if the command matches a destructive-operation rule."""
    text = command.lower()

    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in _DESTRUCTIVE_PATTERNS
    )


def confirm_bash(command: str, auto_approve: bool = False) -> dict:
    #decide whether a bash command is allowed.
    #auto_approve=True represents explicit confirmation by the caller.
    #function does not itself ask a person for confirmation.
    
    command = command.strip()
    if not command:
        return {"allowed": False, "reason": "Command is empty."}

    if is_destructive(command):
        if auto_approve:
            return {
                "allowed": True,
                "reason": "Destructive command was explicitly confirmed.",
            }
        return {
            "allowed": False,
            "reason": "Destructive command requires explicit confirmation.",
        }

    #reject shell composition, substitutions, and redirections. 
    #allow-list is for individual simple commands only.
    if any(char in command for char in (";", "&", "|", "`", "$", "<", ">", "\n", "\r")):
        return {
            "allowed": False,
            "reason": "Shell operators and redirections are not allowed.",
        }

    try:
        tokens = tuple(shlex.split(command, posix=True))
    except ValueError as error:
        return {"allowed": False, "reason": f"Could not parse command: {error}"}

    #exact command forms: do not allow extra path or option arguments.
    if tokens in SAFE_PREFIXES:
        return {"allowed": True, "reason": "Command matches the safe allow-list."}

    return {
        "allowed": False,
        "reason": "Command is not on the safe allow-list.",
    }