#!/usr/bin/env python3
"""
Temp test for add_polarion_decorator and the validate_edit write guard.

Covers the bug where the decorator was added by asking an LLM to echo
back the whole file: on a large module the reply was truncated and the
file was overwritten with a fragment of itself.

Tests covered:
- real OCS-CI module (414 lines)      — decorator added, nothing else changed
- parenthesised marks import          — one name line inserted
- single-line testlib import          — rebuilt on one line
- single-line import that grows long  — converted to parenthesised form
- no polarion_id import anywhere      — marks import added
- polarion_id already imported        — import left alone
- both testlib and marks imports      — testlib is the one extended
- module-level (non-class) test       — decorator at column 0
- async test function                 — handled like a sync one
- existing matching polarion_id       — refuses, file untouched
- existing different polarion_id      — refuses, file untouched
- @pytest.mark.polarion_id form       — recognised, refuses
- function not in file                — refuses, file untouched
- unparseable file                    — refuses, file untouched
- validate_edit against 9 bad rewrites, including the real truncation

Usage:
    python tests/test_add_polarion_decorator.py
"""

import ast
import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
from constants import MARKS_MODULE, TESTLIB_MODULE  # noqa: E402
from polarion_tc_helpers import (  # noqa: E402
    add_polarion_decorator,
    validate_edit,
)

OCS_CI = Path("/home/ikave/IBMProjects/ocs-ci")

REAL_FILE = (
    OCS_CI
    / "tests"
    / "functional"
    / "object"
    / "mcg"
    / "test_noobaa_db_tls.py"
)
REAL_NAME = "test_noobaa_db_tls_after_upgrade"

TMP = Path(tempfile.mkdtemp(prefix="polarion_decorator_test_"))


# ── harness ──────────────────────────────────────────────────────────


def run_add(name, source, test_name, wi_id, answer="y"):
    """Run add_polarion_decorator on a scratch file.

    Returns (returned, text_after, printed_output).
    """
    path = TMP / f"{name}.py"
    path.write_text(source)
    stdin = sys.stdin
    sys.stdin = io.StringIO(answer + "\n")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            returned = add_polarion_decorator(path, test_name, wi_id)
    finally:
        sys.stdin = stdin
    return returned, path.read_text(), buf.getvalue()


def changed_lines(before, after):
    """Return (added, removed) line lists between two file texts."""
    import difflib

    added, removed = [], []
    for line in difflib.unified_diff(
        before.splitlines(), after.splitlines(), n=0
    ):
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    return added, removed


def check(label, condition, detail=""):
    """Assert a condition, reporting the label on failure."""
    if not condition:
        raise AssertionError(f"{label}{': ' + detail if detail else ''}")


def assert_untouched(label, before, after, returned, output, expect):
    """Assert the call refused and left the file byte-identical."""
    check(f"{label}: should return False", returned is False)
    check(f"{label}: file must be unchanged", after == before)
    check(
        f"{label}: expected {expect!r} in output",
        expect in output,
        output.strip(),
    )


# ── the real file that was destroyed ─────────────────────────────────


def test_real_ocs_ci_module():
    """The 414-line module gets a 2-line diff and nothing else."""
    if not REAL_FILE.exists():
        print(f"SKIP: {REAL_FILE.name} not on this branch")
        return

    before = REAL_FILE.read_text()
    returned, after, _ = run_add("real", before, REAL_NAME, "OCS-8365")

    check("real: should return True", returned is True)
    added, removed = changed_lines(before, after)
    check(
        "real: exactly 2 lines added",
        len(added) == 2,
        f"added={added}",
    )
    check(
        "real: no lines removed",
        removed == [],
        f"removed={removed}",
    )
    check(
        "real: decorator added",
        '    @polarion_id("OCS-8365")' in added,
        f"added={added}",
    )
    check(
        "real: import added",
        "    polarion_id," in added,
        f"added={added}",
    )
    check("real: still parses", ast.parse(after) is not None)
    check(
        "real: every definition survived",
        _names(before) == _names(after),
    )
    check(
        "real: decorator sits directly above the def",
        _decorator_is_above_def(after, REAL_NAME, "OCS-8365"),
    )
    print("PASS: real_ocs_ci_module")
    print(f"  {len(before.splitlines())} -> {len(after.splitlines())} lines")


def _names(text):
    """Return all function and class names defined in source text."""
    return {
        n.name
        for n in ast.walk(ast.parse(text))
        if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
    }


def _decorator_is_above_def(text, test_name, wi_id):
    """Return True if @polarion_id(wi_id) is the last decorator."""
    for node in ast.walk(ast.parse(text)):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == test_name
        ):
            if not node.decorator_list:
                return False
            last = node.decorator_list[-1]
            return (
                isinstance(last, ast.Call)
                and getattr(last.func, "id", "") == "polarion_id"
                and last.args[0].value == wi_id
            )
    return False


# ── import handling ──────────────────────────────────────────────────

PAREN_MARKS = '''\
from ocs_ci.framework.pytest_customization.marks import (
    mcg,
    tier2,
)


@mcg
class TestThing:
    @tier2
    def test_a(self):
        pass
'''

SINGLE_TESTLIB = '''\
from ocs_ci.framework.testlib import ManageTest, tier2


@tier2
def test_a():
    pass
'''

LONG_SINGLE = (
    "from ocs_ci.framework.testlib import "
    "ManageTest, tier2, skipif_ocs_version, skipif_ocp_version\n"
    "\n\n@tier2\ndef test_a():\n    pass\n"
)

NO_IMPORT = '''\
import logging

log = logging.getLogger(__name__)


def test_a():
    pass
'''

ALREADY_IMPORTED = '''\
from ocs_ci.framework.testlib import polarion_id, tier2


@tier2
@polarion_id("OCS-1")
def test_other():
    pass


@tier2
def test_a():
    pass
'''


def test_parenthesised_marks_import():
    """A parenthesised marks block gains one name line."""
    returned, after, _ = run_add(
        "paren", PAREN_MARKS, "test_a", "OCS-100"
    )
    added, removed = changed_lines(PAREN_MARKS, after)
    check("paren: returns True", returned is True)
    check("paren: nothing removed", removed == [])
    check(
        "paren: name line inserted",
        "    polarion_id," in added,
        f"added={added}",
    )
    check("paren: parses", ast.parse(after) is not None)
    check(
        "paren: decorator is innermost",
        _decorator_is_above_def(after, "test_a", "OCS-100"),
    )
    print("PASS: parenthesised_marks_import")


def test_single_line_testlib_import():
    """A single-line testlib import is rebuilt on one line."""
    returned, after, _ = run_add(
        "single", SINGLE_TESTLIB, "test_a", "OCS-101"
    )
    check("single: returns True", returned is True)
    check(
        "single: import extended in place",
        "from ocs_ci.framework.testlib import "
        "ManageTest, tier2, polarion_id" in after,
        after,
    )
    check("single: parses", ast.parse(after) is not None)
    print("PASS: single_line_testlib_import")


def test_long_import_becomes_parenthesised():
    """An import that would exceed 79 chars is wrapped."""
    returned, after, _ = run_add(
        "long", LONG_SINGLE, "test_a", "OCS-102"
    )
    check("long: returns True", returned is True)
    check(
        "long: switched to parenthesised form",
        "import (\n" in after and "    polarion_id,\n" in after,
        after,
    )
    check(
        "long: no line over 79 chars",
        max(len(x) for x in after.splitlines()) <= 79,
        max(after.splitlines(), key=len),
    )
    check("long: parses", ast.parse(after) is not None)
    print("PASS: long_import_becomes_parenthesised")


def test_no_import_adds_marks_import():
    """A file with no mark import gains the marks import."""
    returned, after, _ = run_add(
        "noimport", NO_IMPORT, "test_a", "OCS-103"
    )
    check("noimport: returns True", returned is True)
    check(
        "noimport: marks import added",
        "from ocs_ci.framework.pytest_customization.marks "
        "import polarion_id" in after,
        after,
    )
    check("noimport: parses", ast.parse(after) is not None)
    print("PASS: no_import_adds_marks_import")


BOTH_IMPORTS = '''\
from ocs_ci.framework.pytest_customization.marks import (
    mcg,
)
from ocs_ci.framework.testlib import (
    ManageTest,
)


@mcg
class TestThing(ManageTest):
    def test_a(self):
        pass
'''


def _import_module_for(text, name):
    """Return the module that `name` is imported from, or None."""
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and any(
            a.name == name for a in node.names
        ):
            return node.module
    return None


def test_testlib_preferred_over_marks():
    """With both blocks present, testlib is the one extended."""
    returned, after, _ = run_add(
        "both", BOTH_IMPORTS, "test_a", "OCS-110"
    )
    check("both: returns True", returned is True)
    check(
        "both: polarion_id must go into the testlib block",
        _import_module_for(after, "polarion_id") == TESTLIB_MODULE,
        f"went into {_import_module_for(after, 'polarion_id')}",
    )
    check(
        "both: the marks block must be left alone",
        f"from {MARKS_MODULE} import (\n    mcg,\n)" in after,
        after,
    )
    print("PASS: testlib_preferred_over_marks")


def test_existing_import_not_duplicated():
    """polarion_id already imported means only the decorator is added."""
    returned, after, _ = run_add(
        "imported", ALREADY_IMPORTED, "test_a", "OCS-104"
    )
    added, removed = changed_lines(ALREADY_IMPORTED, after)
    check("imported: returns True", returned is True)
    check("imported: nothing removed", removed == [])
    check(
        "imported: only the decorator line added",
        added == ['@polarion_id("OCS-104")'],
        f"added={added}",
    )
    print("PASS: existing_import_not_duplicated")


# ── function shapes ──────────────────────────────────────────────────

MODULE_LEVEL = NO_IMPORT

ASYNC_TEST = '''\
from ocs_ci.framework.testlib import tier2


@tier2
async def test_a():
    pass
'''


def test_module_level_function():
    """A test outside a class gets the decorator at column 0."""
    _, after, _ = run_add(
        "modlevel", MODULE_LEVEL, "test_a", "OCS-105"
    )
    check(
        "modlevel: decorator unindented",
        '\n@polarion_id("OCS-105")\ndef test_a():' in after,
        after,
    )
    print("PASS: module_level_function")


def test_async_function():
    """An async test is handled like a sync one."""
    returned, after, _ = run_add(
        "asyncfn", ASYNC_TEST, "test_a", "OCS-106"
    )
    check("async: returns True", returned is True)
    check(
        "async: decorator above async def",
        '@polarion_id("OCS-106")\nasync def test_a():' in after,
        after,
    )
    check("async: parses", ast.parse(after) is not None)
    print("PASS: async_function")


# ── refusals: the file must never be touched ─────────────────────────


def test_same_id_refused():
    """Re-running with the same ID is a no-op.

    The expected text is the exact same-ID wording: the different-ID
    branch also says "already has", so a looser check would pass even
    if the two branches were confused.
    """
    source = ALREADY_IMPORTED
    returned, after, out = run_add(
        "sameid", source, "test_other", "OCS-1"
    )
    assert_untouched(
        "sameid",
        source,
        after,
        returned,
        out,
        'already has @polarion_id("OCS-1").',
    )
    check(
        "sameid: must not take the different-ID branch",
        "leaving it alone" not in out,
        out.strip(),
    )
    print("PASS: same_id_refused")


def test_different_id_refused():
    """A different existing ID is left alone, not doubled up."""
    source = ALREADY_IMPORTED
    returned, after, out = run_add(
        "diffid", source, "test_other", "OCS-9999"
    )
    assert_untouched(
        "diffid", source, after, returned, out, "leaving it alone"
    )
    check(
        "diffid: no second decorator",
        after.count("@polarion_id") == 1,
        after,
    )
    print("PASS: different_id_refused")


PYTEST_MARK_FORM = '''\
import pytest


@pytest.mark.polarion_id("OCS-2255")
def test_a():
    pass
'''


def test_pytest_mark_form_refused():
    """@pytest.mark.polarion_id counts as already having an ID.

    232 OCS-CI files use this form rather than the bare decorator, so
    missing it would silently add a second, conflicting ID.
    """
    returned, after, out = run_add(
        "pytestmark", PYTEST_MARK_FORM, "test_a", "OCS-9999"
    )
    assert_untouched(
        "pytestmark",
        PYTEST_MARK_FORM,
        after,
        returned,
        out,
        "leaving it alone",
    )
    check(
        "pytestmark: no second ID added",
        after.count("polarion_id") == 1,
        after,
    )
    print("PASS: pytest_mark_form_refused")


def test_missing_function_refused():
    """A name that is not in the file is refused."""
    returned, after, out = run_add(
        "missing", NO_IMPORT, "test_nope", "OCS-107"
    )
    assert_untouched(
        "missing", NO_IMPORT, after, returned, out, "not found"
    )
    print("PASS: missing_function_refused")


def test_unparseable_file_refused():
    """A file with a syntax error is refused, not mangled."""
    broken = "def test_a(:\n    pass\n"
    returned, after, out = run_add(
        "broken", broken, "test_a", "OCS-108"
    )
    assert_untouched(
        "broken", broken, after, returned, out, "Cannot parse"
    )
    print("PASS: unparseable_file_refused")


def test_declined_at_prompt():
    """Answering n at the confirmation leaves the file alone."""
    returned, after, _ = run_add(
        "declined", SINGLE_TESTLIB, "test_a", "OCS-109", answer="n"
    )
    check("declined: returns False", returned is False)
    check("declined: file unchanged", after == SINGLE_TESTLIB)
    print("PASS: declined_at_prompt")


# ── the write guard ──────────────────────────────────────────────────


def test_validate_edit_blocks_bad_rewrites():
    """Every destructive rewrite is rejected, the good one allowed."""
    source = (
        REAL_FILE.read_text()
        if REAL_FILE.exists()
        else ALREADY_IMPORTED * 40
    )
    lines = source.splitlines(keepends=True)
    cut = len(lines) // 2

    must_block = {
        # ast.parse accepts a repeated keyword argument; only compile
        # rejects it. Without that, invalid code reaches the file.
        "repeated keyword argument": (
            source + "\n\nf(marks=1, marks=2)\n"
        ),
        "empty": "",
        "whitespace only": "\n\n   \n",
        "truncated head": "".join(lines[:cut]),
        "truncated tail": "".join(lines[:-3]),
        "summarised": (
            "".join(lines[:20]) + "\n# ... rest unchanged ...\n"
        ),
        "markdown fenced": f"```python\n{source}\n```",
        "prose preamble": f"Here is the file:\n\n{source}",
        "unrelated content": "x = 1\n",
    }
    for label, bad in must_block.items():
        problem = validate_edit(source, bad)
        check(
            f"guard: {label!r} must be blocked",
            bool(problem),
            "it was allowed through",
        )

    # Each rule above has a fallback that would also reject most bad
    # input, so pin the reported reason too. Otherwise deleting a rule
    # leaves the suite green because a later rule happens to catch it.
    reasons = {
        "empty": validate_edit("x = 1\n", ""),
        "fences": validate_edit(source, f"```python\n{source}\n```"),
    }
    for word, reason in reasons.items():
        check(
            f"guard: the {word} case must be reported as such",
            word in reason,
            f"reported instead: {reason!r}",
        )

    # Valid Python, keeps every definition, but most of the module is
    # gone: only the size rule catches this one.
    bulky = "def alpha():\n    return 1\n" + "x = 1\n" * 50
    lean = "def alpha():\n    return 1\n"
    check(
        "guard: a large unexplained shrink must be blocked",
        "smaller" in validate_edit(bulky, lean),
        validate_edit(bulky, lean) or "it was allowed through",
    )

    # Valid Python, same size, but one function has quietly vanished.
    # The size and syntax rules both pass here, so this is the only
    # case that proves the dropped-definition check is doing the work.
    two_fns = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
    without_beta = "def alpha():\n    return 1\n"
    without_beta += "# pad\n" * (
        (len(two_fns) - len(without_beta)) // len("# pad\n") + 1
    )
    check(
        "guard: padding must defeat the size rule",
        len(without_beta) >= len(two_fns) * 0.9,
    )
    check(
        "guard: a silently dropped function must be blocked",
        "beta" in validate_edit(two_fns, without_beta),
        validate_edit(two_fns, without_beta) or "it was allowed through",
    )

    good = source + "\n\ndef test_appended():\n    pass\n"
    check(
        "guard: a legitimate edit must pass",
        validate_edit(source, good) == "",
        validate_edit(source, good),
    )
    print("PASS: validate_edit_blocks_bad_rewrites")
    print(f"  {len(must_block)} destructive rewrites rejected")


# ── runner ───────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        # the regression itself
        test_real_ocs_ci_module,
        # import handling
        test_parenthesised_marks_import,
        test_single_line_testlib_import,
        test_long_import_becomes_parenthesised,
        test_no_import_adds_marks_import,
        test_testlib_preferred_over_marks,
        test_existing_import_not_duplicated,
        # function shapes
        test_module_level_function,
        test_async_function,
        # refusals
        test_same_id_refused,
        test_different_id_refused,
        test_pytest_mark_form_refused,
        test_missing_function_refused,
        test_unparseable_file_refused,
        test_declined_at_prompt,
        # write guard
        test_validate_edit_blocks_bad_rewrites,
    ]

    try:
        for t in tests:
            t()
            print()
        print(f"All {len(tests)} tests passed.")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
