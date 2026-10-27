import tempfile
from pathlib import Path

from .file_tools import (
    bash,
    edit_file,
    glob_files,
    read_file,
    search_in_files,
    write_file,
)
from .safety_gate import confirm_bash


def require_success(result):
    if not result["success"]:
        raise AssertionError(result["error"])
    return result["data"]


def test_file_workflow(sandbox):
    #create three small test files using the file tool.
    require_success(write_file(
        sandbox, "main.py",
        "from settings import DEBUG\nprint(DEBUG)\n",
    ))
    require_success(write_file(
        sandbox, "settings.py",
        "DEBUG = True\n",
    ))
    require_success(write_file(
        sandbox, "helper.py",
        "VALUE = 1\n",
    ))

    files = require_success(glob_files(sandbox, "*.py"))["files"]
    print("Glob found:", files)

    matches = require_success(
        search_in_files(sandbox, "*.py", "DEBUG")
    )["matches"]
    print("Search matches:", matches)

    #follow the matching path from search into read_file.
    debug_file = matches[0]["path"]
    content = require_success(
        read_file(sandbox, debug_file, max_lines=10)
    )["content"]
    print(f"Contents of {debug_file}:")
    print(content, end="")

    #demonstrate edit_file and its short diff.
    edit = require_success(
        edit_file(sandbox, "helper.py", "VALUE = 1", "VALUE = 2")
    )
    print("Edit diff:")
    print(edit["diff"], end="")


def test_safety_gate():
    should_pass = [
        "pwd",
        "ls",
        "python --version",
        "git --version",
        "whoami",
    ]

    should_block = [
        "rm -rf ./cache",
        "sudo chown root:root ./sample.py",
        "chmod -R 777 ./sample.py",
        "dd if=/dev/zero of=/dev/sda",
        "mkdir /etc/newdir > /etc/tool.log",
    ]

    passed = 0
    blocked = 0

    for command in should_pass:
        result = confirm_bash(command, auto_approve=False)
        print(f"PASS check: {command} -> {result['allowed']}")
        assert result["allowed"], f"Expected command to pass: {command}"
        passed += 1

    for command in should_block:
        result = confirm_bash(command, auto_approve=False)
        print(f"BLOCK check: {command} -> {result['allowed']}")
        assert not result["allowed"], f"Expected command to be blocked: {command}"
        blocked += 1

    #confirm that a destructive command needs explicit confirmation.
    confirmation = confirm_bash("rm -rf ./cache", auto_approve=True)
    assert confirmation["allowed"]

    print(f"Safety-gate results: {passed} passed, {blocked} blocked")
    print("Explicit destructive confirmation:", confirmation["reason"])


def main():
    #all file-tool operations and the bash invocation use this temporary root
    with tempfile.TemporaryDirectory(prefix="part6_sandbox_") as sandbox:
        print("Temporary sandbox:", sandbox)
        test_file_workflow(sandbox)
        test_safety_gate()

        #run one allow-listed command from inside the temporary sandbox
        bash_result = bash("pwd", sandbox)
        if bash_result["success"]:
            print("Bash pwd output:", bash_result["data"]["stdout"].strip())
        else:
            print("Bash invocation unavailable or blocked:", bash_result["error"])


if __name__ == "__main__":
    main()