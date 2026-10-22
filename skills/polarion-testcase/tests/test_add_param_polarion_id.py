#!/usr/bin/env python3
"""
Temp test for add_param_polarion_id.

Per-param-set IDs go inside `pytest.param(..., marks=...)`, not on the
function. This covers the argvalue shapes that occur in OCS-CI.

Tests covered:
- real OCS-CI file, splat argvalue, no marks  — both param sets marked
- param with no marks                         — marks= added
- param with a single bare mark               — promoted to a list
- param with a list of marks                  — appended to the list
- param with a tuple of marks                 — appended to the tuple
- param with an empty list of marks           — filled in
- param spanning several lines, trailing comma— layout preserved
- bare scalar argvalue                        — wrapped in pytest.param
- bare tuple argvalue                         — unpacked and wrapped
- keyword argvalues=                          — found via keyword
- two classes defining the same test name     — class_name disambiguates
- a long line                                 — left for black to wrap
- six param sets marked one at a time         — each keeps its own ID
- param already holding a polarion_id         — refused
- function-level @polarion_id present         — refused
- two parametrize decorators                  — refused as ambiguous
- not parametrized / bad index / no function  — refused
- answering n at the prompt                   — file untouched

Usage:
    python tests/test_add_param_polarion_id.py
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
from polarion_tc_helpers import add_param_polarion_id  # noqa: E402

OCS_CI = Path("/home/ikave/IBMProjects/ocs-ci")
REAL_FILE = OCS_CI / "tests" / "libtest" / "test_sanity_provider_mode.py"
REAL_NAME = "test_sanity_ms"

TMP = Path(tempfile.mkdtemp(prefix="polarion_param_test_"))

HEAD = "import pytest\n\n\n"


def run_add(name, source, test_name, index, wi_id, answer="y", **kw):
    """Run add_param_polarion_id on a scratch file."""
    path = TMP / f"{name}.py"
    path.write_text(source)
    stdin = sys.stdin
    sys.stdin = io.StringIO(answer + "\n")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            returned = add_param_polarion_id(
                path, test_name, index, wi_id, **kw
            )
    finally:
        sys.stdin = stdin
    return returned, path.read_text(), buf.getvalue()


def check(label, condition, detail=""):
    """Assert a condition, reporting the label on failure."""
    if not condition:
        raise AssertionError(f"{label}{': ' + detail if detail else ''}")


def marks_of(text, test_name, index):
    """Return the source of the marks= on one param, or ''."""
    tree = ast.parse(text)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == test_name
    )
    dec = next(
        d
        for d in fn.decorator_list
        if isinstance(d, ast.Call)
        and getattr(d.func, "attr", "") == "parametrize"
    )
    kw = {k.arg: k.value for k in dec.keywords}
    argvalues = dec.args[1] if len(dec.args) >= 2 else kw["argvalues"]
    node = argvalues.elts[index]
    for k in getattr(node, "keywords", []):
        if k.arg == "marks":
            return ast.get_source_segment(text, k.value) or ""
    return ""


def assert_good(label, before, after, test_name, index, wi_id):
    """Assert the file still parses and the mark landed on the param."""
    check(f"{label}: must still parse", ast.parse(after) is not None)
    got = marks_of(after, test_name, index)
    check(
        f"{label}: polarion_id must be on param {index}",
        f'polarion_id("{wi_id}")' in got,
        f"marks are {got!r}",
    )
    check(
        f"{label}: must not add a function-level decorator",
        after.count("@pytest.mark.polarion_id")
        == before.count("@pytest.mark.polarion_id"),
        after,
    )


def body(params, argnames='argnames=["platform"],', extra=""):
    """Build a small parametrized test module."""
    return (
        HEAD
        + "@pytest.mark.parametrize(\n"
        + f"    {argnames}\n"
        + "    argvalues=[\n"
        + params
        + "    ],\n"
        + ")\n"
        + extra
        + "def test_a(platform):\n    pass\n"
    )


# ── the real file ────────────────────────────────────────────────────


def test_real_ocs_ci_file():
    """Splat argvalues with no marks, in a real OCS-CI module."""
    if not REAL_FILE.exists():
        print(f"SKIP: {REAL_FILE.name} not present")
        return
    before = REAL_FILE.read_text()
    _, after, _ = run_add("real0", before, REAL_NAME, 0, "OCS-9001")
    path = TMP / "real0.py"
    path.write_text(after)
    sys.stdin = io.StringIO("y\n")
    with contextlib.redirect_stdout(io.StringIO()):
        add_param_polarion_id(path, REAL_NAME, 1, "OCS-9002")
    final = path.read_text()

    assert_good("real", before, final, REAL_NAME, 0, "OCS-9001")
    assert_good("real", before, final, REAL_NAME, 1, "OCS-9002")
    check(
        "real: line count unchanged",
        len(final.splitlines()) == len(before.splitlines()),
        f"{len(before.splitlines())} -> {len(final.splitlines())}",
    )
    check(
        "real: splat argvalue preserved",
        "*[HCI_PROVIDER]" in final and "*[HCI_CLIENT]" in final,
        final,
    )
    print("PASS: real_ocs_ci_file")
    print(f"  {len(before.splitlines())} lines, unchanged count")


# ── marks shapes ─────────────────────────────────────────────────────


def test_no_marks():
    """A param with no marks gains a marks= keyword."""
    src = body('        pytest.param("aws"),\n')
    returned, after, _ = run_add("nomarks", src, "test_a", 0, "OCS-1")
    check("nomarks: returns True", returned is True)
    assert_good("nomarks", src, after, "test_a", 0, "OCS-1")
    print("PASS: no_marks")


def test_single_bare_mark_promoted_to_list():
    """An existing single mark becomes a list holding both."""
    src = body(
        '        pytest.param("aws", marks=pytest.mark.tier1),\n'
    )
    returned, after, _ = run_add("bare", src, "test_a", 0, "OCS-2")
    check("bare: returns True", returned is True)
    assert_good("bare", src, after, "test_a", 0, "OCS-2")
    got = marks_of(after, "test_a", 0)
    check("bare: became a list", got.startswith("["), got)
    check("bare: original mark kept", "pytest.mark.tier1" in got, got)
    print("PASS: single_bare_mark_promoted_to_list")


def test_list_of_marks_appended():
    """An existing list of marks gains one entry."""
    src = body(
        '        pytest.param("aws", marks=[pytest.mark.tier1,'
        " pytest.mark.slow]),\n"
    )
    returned, after, _ = run_add("list", src, "test_a", 0, "OCS-3")
    check("list: returns True", returned is True)
    assert_good("list", src, after, "test_a", 0, "OCS-3")
    got = marks_of(after, "test_a", 0)
    check("list: still a list", got.startswith("["), got)
    check(
        "list: both originals kept",
        "tier1" in got and "slow" in got,
        got,
    )
    print("PASS: list_of_marks_appended")


def test_tuple_of_marks_appended():
    """An existing tuple of marks gains one entry."""
    src = body(
        '        pytest.param("aws", marks=(pytest.mark.tier1,)),\n'
    )
    returned, after, _ = run_add("tuple", src, "test_a", 0, "OCS-4")
    check("tuple: returns True", returned is True)
    assert_good("tuple", src, after, "test_a", 0, "OCS-4")
    print("PASS: tuple_of_marks_appended")


def test_empty_marks_list_filled():
    """An empty marks list is filled in rather than corrupted."""
    src = body('        pytest.param("aws", marks=[]),\n')
    returned, after, _ = run_add("empty", src, "test_a", 0, "OCS-5")
    check("empty: returns True", returned is True)
    assert_good("empty", src, after, "test_a", 0, "OCS-5")
    print("PASS: empty_marks_list_filled")


def test_multiline_param_with_trailing_comma():
    """A multi-line param keeps its layout; no double comma."""
    src = body(
        "        pytest.param(\n"
        '            "aws",\n'
        "            marks=[pytest.mark.tier1],\n"
        "        ),\n"
    )
    returned, after, _ = run_add("multi", src, "test_a", 0, "OCS-6")
    check("multi: returns True", returned is True)
    assert_good("multi", src, after, "test_a", 0, "OCS-6")
    check("multi: no double comma", ",," not in after.replace(" ", ""))
    print("PASS: multiline_param_with_trailing_comma")


def test_multiline_param_no_marks():
    """A multi-line param with a trailing comma and no marks."""
    src = body(
        "        pytest.param(\n"
        '            "aws",\n'
        "        ),\n"
    )
    returned, after, _ = run_add("multi2", src, "test_a", 0, "OCS-7")
    check("multi2: returns True", returned is True)
    assert_good("multi2", src, after, "test_a", 0, "OCS-7")
    print("PASS: multiline_param_no_marks")


# ── argvalue shapes ──────────────────────────────────────────────────


def test_bare_scalar_wrapped():
    """A bare value is wrapped in pytest.param so it can carry marks."""
    src = body('        "aws",\n')
    returned, after, _ = run_add("scalar", src, "test_a", 0, "OCS-8")
    check("scalar: returns True", returned is True)
    assert_good("scalar", src, after, "test_a", 0, "OCS-8")
    check(
        "scalar: value preserved",
        'pytest.param("aws", marks=' in after,
        after,
    )
    print("PASS: bare_scalar_wrapped")


def test_bare_tuple_unpacked():
    """A bare tuple is unpacked into pytest.param arguments."""
    src = body(
        '        ("aws", 3),\n',
        argnames='argnames=["platform", "count"],',
    ).replace("def test_a(platform):", "def test_a(platform, count):")
    returned, after, _ = run_add("btuple", src, "test_a", 0, "OCS-9")
    check("btuple: returns True", returned is True)
    assert_good("btuple", src, after, "test_a", 0, "OCS-9")
    check(
        "btuple: unpacked, not nested",
        'pytest.param("aws", 3, marks=' in after,
        after,
    )
    print("PASS: bare_tuple_unpacked")


def test_positional_argvalues():
    """argnames/argvalues passed positionally are still found."""
    src = (
        HEAD
        + "@pytest.mark.parametrize(\n"
        + '    "platform",\n'
        + "    [\n"
        + '        pytest.param("aws"),\n'
        + "    ],\n"
        + ")\n"
        + "def test_a(platform):\n    pass\n"
    )
    returned, after, _ = run_add("positional", src, "test_a", 0, "OCS-10")
    check("positional: returns True", returned is True)
    assert_good("positional", src, after, "test_a", 0, "OCS-10")
    print("PASS: positional_argvalues")


def test_long_line_left_for_black():
    """A long result stays correct; black re-wraps it on commit.

    Formatting is deliberately not this function's job — ocs-ci runs
    black 24.3.0 in pre-commit, so width is handled there.
    """
    long_val = '"' + "a" * 55 + '"'
    src = body(f"        pytest.param({long_val}),\n")
    returned, after, _ = run_add("long", src, "test_a", 0, "OCS-11")
    check("long: returns True", returned is True)
    assert_good("long", src, after, "test_a", 0, "OCS-11")
    check("long: value preserved", long_val in after, after)
    print("PASS: long_line_left_for_black")


def test_many_params_sequentially():
    """Six param sets each get their own ID, one call at a time."""
    src = body(
        "".join(
            f'        pytest.param("p{i}", marks=[tier{i % 2 + 1}]),\n'
            for i in range(6)
        )
    )
    text = src
    for i in range(6):
        path = TMP / "many.py"
        path.write_text(text)
        sys.stdin = io.StringIO("y\n")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            ok = add_param_polarion_id(path, "test_a", i, f"OCS-70{i}")
        check(
            f"many: param {i} must be marked",
            ok is True,
            buf.getvalue().strip()[:70],
        )
        text = path.read_text()

    for i in range(6):
        assert_good("many", src, text, "test_a", i, f"OCS-70{i}")
    check(
        "many: original marks all kept",
        all(f"tier{i % 2 + 1}" in marks_of(text, "test_a", i) for i in range(6)),
        text,
    )
    check(
        "many: each ID appears exactly once",
        all(text.count(f'"OCS-70{i}"') == 1 for i in range(6)),
        text,
    )
    check("many: compiles", compile(text, "<t>", "exec") is not None)
    print("PASS: many_params_sequentially")


TWO_CLASSES = '''\
import pytest


class TestOne:
    @pytest.mark.parametrize(
        argnames=["p"], argvalues=[pytest.param("one")]
    )
    def test_a(self, p):
        pass


class TestTwo:
    @pytest.mark.parametrize(
        argnames=["p"], argvalues=[pytest.param("two")]
    )
    def test_a(self, p):
        pass
'''


def test_class_name_picks_the_right_duplicate():
    """Two classes define test_a; class_name selects which one.

    Without a second class this would pass even if class_name were
    ignored, so the duplicate name is the point of the fixture.
    """
    returned, after, _ = run_add(
        "dupe", TWO_CLASSES, "test_a", 0, "OCS-14", class_name="TestTwo"
    )
    check("dupe: returns True", returned is True)
    check(
        "dupe: TestTwo's param was marked",
        'pytest.param("two", marks=pytest.mark.polarion_id("OCS-14"))'
        in after,
        after,
    )
    check(
        "dupe: TestOne's param untouched",
        'pytest.param("one")' in after,
        after,
    )
    check("dupe: exactly one ID added", after.count("OCS-14") == 1, after)
    print("PASS: class_name_picks_the_right_duplicate")


def test_second_param_targeted():
    """The index selects the right param, leaving the others alone."""
    src = body(
        '        pytest.param("aws"),\n'
        '        pytest.param("azure"),\n'
        '        pytest.param("gcp"),\n'
    )
    returned, after, _ = run_add("second", src, "test_a", 1, "OCS-12")
    check("second: returns True", returned is True)
    assert_good("second", src, after, "test_a", 1, "OCS-12")
    check(
        "second: others untouched",
        marks_of(after, "test_a", 0) == ""
        and marks_of(after, "test_a", 2) == "",
        after,
    )
    print("PASS: second_param_targeted")


def test_class_scoped_lookup():
    """class_name disambiguates same-named tests."""
    src = (
        HEAD
        + "class TestOne:\n"
        + "    @pytest.mark.parametrize(\n"
        + '        argnames=["platform"],\n'
        + "        argvalues=[\n"
        + '            pytest.param("aws"),\n'
        + "        ],\n"
        + "    )\n"
        + "    def test_a(self, platform):\n        pass\n"
    )
    returned, after, _ = run_add(
        "scoped", src, "test_a", 0, "OCS-13", class_name="TestOne"
    )
    check("scoped: returns True", returned is True)
    assert_good("scoped", src, after, "test_a", 0, "OCS-13")
    print("PASS: class_scoped_lookup")


# ── refusals ─────────────────────────────────────────────────────────


def assert_untouched(label, before, after, returned, out, expect):
    """Assert the call refused and left the file byte-identical."""
    check(f"{label}: should return False", returned is False)
    check(f"{label}: file must be unchanged", after == before)
    check(
        f"{label}: expected {expect!r} in output",
        expect in out,
        out.strip(),
    )


def test_existing_param_id_refused():
    """A param that already has an ID is left alone."""
    src = body(
        '        pytest.param("aws",'
        ' marks=pytest.mark.polarion_id("OCS-111")),\n'
    )
    returned, after, out = run_add("hasid", src, "test_a", 0, "OCS-14")
    assert_untouched(
        "hasid", src, after, returned, out, "leaving it alone"
    )
    print("PASS: existing_param_id_refused")


def test_function_level_id_refused():
    """A function-level ID blocks adding a per-param one."""
    src = body(
        '        pytest.param("aws"),\n',
        extra='@pytest.mark.polarion_id("OCS-222")\n',
    )
    returned, after, out = run_add("fnid", src, "test_a", 0, "OCS-15")
    assert_untouched(
        "fnid", src, after, returned, out, "function-level"
    )
    print("PASS: function_level_id_refused")


def test_stacked_parametrize_refused():
    """Two parametrize decorators make the index ambiguous."""
    src = (
        HEAD
        + "@pytest.mark.parametrize(\n"
        + '    argnames=["a"], argvalues=[pytest.param(1)],\n'
        + ")\n"
        + "@pytest.mark.parametrize(\n"
        + '    argnames=["b"], argvalues=[pytest.param(2)],\n'
        + ")\n"
        + "def test_a(a, b):\n    pass\n"
    )
    returned, after, out = run_add("stacked", src, "test_a", 0, "OCS-16")
    assert_untouched("stacked", src, after, returned, out, "ambiguous")
    print("PASS: stacked_parametrize_refused")


def test_not_parametrized_refused():
    """A plain test is refused."""
    src = HEAD + "def test_a():\n    pass\n"
    returned, after, out = run_add("plain", src, "test_a", 0, "OCS-17")
    assert_untouched(
        "plain", src, after, returned, out, "not parametrized"
    )
    print("PASS: not_parametrized_refused")


def test_index_out_of_range_refused():
    """An index past the end is refused."""
    src = body('        pytest.param("aws"),\n')
    returned, after, out = run_add("range", src, "test_a", 5, "OCS-18")
    assert_untouched("range", src, after, returned, out, "out of range")
    print("PASS: index_out_of_range_refused")


def test_missing_function_refused():
    """An unknown test name is refused."""
    src = body('        pytest.param("aws"),\n')
    returned, after, out = run_add("nofn", src, "test_nope", 0, "OCS-19")
    assert_untouched("nofn", src, after, returned, out, "not found")
    print("PASS: missing_function_refused")


def test_unparseable_refused():
    """A file with a syntax error is refused, not mangled."""
    src = "def test_a(:\n    pass\n"
    returned, after, out = run_add("broken", src, "test_a", 0, "OCS-20")
    assert_untouched("broken", src, after, returned, out, "Cannot parse")
    print("PASS: unparseable_refused")


def test_declined_at_prompt():
    """Answering n leaves the file alone."""
    src = body('        pytest.param("aws"),\n')
    returned, after, _ = run_add(
        "declined", src, "test_a", 0, "OCS-21", answer="n"
    )
    check("declined: returns False", returned is False)
    check("declined: file unchanged", after == src)
    print("PASS: declined_at_prompt")


# ── runner ───────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_real_ocs_ci_file,
        # marks shapes
        test_no_marks,
        test_single_bare_mark_promoted_to_list,
        test_list_of_marks_appended,
        test_tuple_of_marks_appended,
        test_empty_marks_list_filled,
        test_multiline_param_with_trailing_comma,
        test_multiline_param_no_marks,
        # argvalue shapes
        test_bare_scalar_wrapped,
        test_bare_tuple_unpacked,
        test_positional_argvalues,
        test_long_line_left_for_black,
        test_many_params_sequentially,
        test_second_param_targeted,
        test_class_scoped_lookup,
        test_class_name_picks_the_right_duplicate,
        # refusals
        test_existing_param_id_refused,
        test_function_level_id_refused,
        test_stacked_parametrize_refused,
        test_not_parametrized_refused,
        test_index_out_of_range_refused,
        test_missing_function_refused,
        test_unparseable_refused,
        test_declined_at_prompt,
    ]

    try:
        for t in tests:
            t()
            print()
        print(f"All {len(tests)} tests passed.")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
