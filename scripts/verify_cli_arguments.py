"""Compare argument parsing with a trusted local baseline commit (no API calls)."""

import argparse
import ast
import contextlib
import io
import subprocess

from jdsh import arguments


def capture(parse, argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = ("parsed", vars(parse(list(argv))))
        except SystemExit as error:
            result = ("exit", error.code)
    return result, stdout.getvalue(), stderr.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Trusted local git ref containing the former CLI parser")
    options = parser.parse_args()
    source = subprocess.check_output(
        ["git", "show", "--end-of-options", options.baseline + ":src/jdsh/cli.py"], text=True,
    )
    names = {"_build_parser", "_normalize_argv", "_parse_args"}
    tree = ast.parse(source)
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in tree.body} != names:
        parser.error("baseline must contain all three former CLI argument functions")
    # Execute only the selected parser functions from the explicitly trusted ref.
    namespace = {"argparse": argparse}
    exec(compile(tree, "<baseline-cli-arguments>", "exec"), namespace)
    baseline = namespace["_parse_args"]
    cases = [[], ["unknown"], ["--help"], ["-h"]]
    commands = ["status", "list", "ls", "show", "why", "check", "grabber", "confirm",
                "start", "stop", "clear", "version", "help", "add", "remove", "rm", "replace"]
    for command in commands:
        cases.extend([[command], [command, "--help"], [command, "--unknown"]])
    cases.extend([
        ["ls", "-d"], ["list", "--detail"], ["grabber", "-d"],
        ["show", "123", "--json"], ["why", "123", "--json"], ["show", "invalid"],
        ["check", "123"], ["check", "--all"], ["check", "--all", "--json"],
        ["check", "123", "--all"], ["check", "invalid"],
        ["remove", "1", "2"], ["rm", "1"], ["replace", "1", "https://new.example"],
        ["add", "--", "--clipboard", "--file"], ["add", "URL1", "--file"],
        ["add", "URL1", "--file", "--clipboard"], ["add", "--file="],
        ["add", "--file", "first.txt", "--file", "last.txt", "URL1"],
        ["add", "URL1", "--unknown"], ["add", "--clip", "URL1"],
    ])
    for file_option in (["--file", "links list.txt"], ["-f", "links list.txt"],
                        ["--file=links list.txt"], ["-flinks.txt"], ["--clipboard"]):
        for before, after in (([], ["URL1", "URL2"]), (["URL1"], ["URL2"]), (["URL1", "URL2"], [])):
            cases.append(["add"] + before + file_option + after)
        cases.append(["add"] + file_option)
    cases.append(["add", "URL1", "--file=links.txt", "--clipboard", "URL2"])
    for argv in cases:
        expected, actual = capture(baseline, argv), capture(arguments.parse_args, argv)
        if actual != expected:
            raise AssertionError((argv, expected, actual))
    print("Argument parsing, help, stderr and exit codes match in {} cases.".format(len(cases)))


if __name__ == "__main__":
    main()
