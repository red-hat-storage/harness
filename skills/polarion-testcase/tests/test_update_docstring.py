#!/usr/bin/env python3
"""
Tests for ai_update_docstring.

The model is asked for the docstring alone and its answer is spliced
into the docstring's ast span, so it can neither truncate the file nor
change anything outside those lines. These tests stub call_claude to
return the kinds of answers a model actually gives.

Tests covered:
- a good docstring            — spliced in, rest of the file identical
- the prompt                  — carries the docstring, not the whole file
- a truncated reply           — refused
- an empty reply              — refused
- markdown fences             — refused
- prose instead of a docstring— refused
- a whole file echoed back    — refused
- an unterminated quote       — refused
- code appended after it      — refused
- a reply that deletes code   — cannot reach outside the docstring span
- no docstring on the function— refused with a clear message
- missing function            — refused
- no claude CLI               — refused before the file is read
- the CLI raising             — reported, not propagated
- an unchanged docstring      — no-op, reported as such
- answering n at the prompt   — file untouched

Usage:
    python tests/test_update_docstring.py
"""

import atexit
import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
import polarion_tc_helpers as H  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="polarion_docstring_test_"))
# Also runs under pytest, where the __main__ block below never fires.
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

SOURCE = '''\
import logging

log = logging.getLogger(__name__)


def helper():
    """Untouched helper."""
    return 1


class TestThing:
    def test_a(self):
        """Check the thing works.

        Steps:
        1. Old step one.
        2. Old step two.
        """
        assert True

    def test_b(self):
        """Another test, must not change."""
        assert True
'''

GOOD = '''"""Check the thing works.

        Steps:
        1. Create the bucket.
        2. Upload an object.
        3. Verify the checksum.
        """'''

# The docstring test_a already has, so the model "changing" nothing
# can be told apart from the model being refused.
SAME = '''"""Check the thing works.

        Steps:
        1. Old step one.
        2. Old step two.
        """'''

STEPS = [
    {"step": "Create the bucket.", "expected": "Step completes successfully."},
    {"step": "Upload an object.", "expected": "Step completes successfully."},
    {"step": "Verify the checksum.", "expected": "Checksums match."},
]


def check(label, condition, detail=""):
    """Assert a condition, reporting the label on failure."""
    if not condition:
        raise AssertionError(f"{label}{': ' + detail if detail else ''}")


@contextlib.contextmanager
def stubbed(reply, answer="y", available=True):
    """Stand in for the claude CLI and the confirmation prompt.

    Restores the module globals and stdin on the way out, so a test
    cannot leave a stub behind for whatever runs next.
    """
    captured = {}

    def fake_call_claude(prompt, timeout=120):
        captured["prompt"] = prompt
        if isinstance(reply, Exception):
            raise reply
        return reply

    real_call, real_avail = H.call_claude, H.claude_available
    real_stdin = sys.stdin
    H.call_claude = fake_call_claude
    H.claude_available = lambda: available
    sys.stdin = io.StringIO(answer + "\n")
    try:
        yield captured
    finally:
        H.call_claude, H.claude_available = real_call, real_avail
        sys.stdin = real_stdin


def run(name, reply, answer="y", source=SOURCE, test_name="test_a",
        available=True):
    """Run ai_update_docstring with call_claude stubbed."""
    path = TMP / f"{name}.py"
    path.write_text(source)
    buf = io.StringIO()
    with stubbed(reply, answer, available) as captured:
        with contextlib.redirect_stdout(buf):
            returned = H.ai_update_docstring(
                path, test_name, STEPS, class_name="TestThing"
            )
    return (
        returned,
        path.read_text(),
        buf.getvalue(),
        captured.get("prompt", ""),
    )


def assert_refused(label, returned, after, out, expect, before=SOURCE):
    """Assert the call refused and left the file byte-identical."""
    check(f"{label}: should return False", returned is False)
    check(f"{label}: file must be unchanged", after == before)
    check(
        f"{label}: expected {expect!r} in output",
        expect in out,
        out.strip()[:120],
    )


# ── the good path ────────────────────────────────────────────────────


def test_good_docstring_applied():
    """A sane reply is spliced in and nothing else moves."""
    returned, after, _, _ = run("good", GOOD)
    check("good: returns True", returned is True)
    check("good: new steps present", "Verify the checksum." in after)
    check("good: old steps gone", "Old step one." not in after)
    check(
        "good: the other test is untouched",
        '"""Another test, must not change."""' in after,
        after,
    )
    check(
        "good: the helper is untouched",
        '"""Untouched helper."""' in after and "return 1" in after,
    )
    check("good: compiles", compile(after, "<t>", "exec") is not None)
    print("PASS: good_docstring_applied")


def test_prompt_sends_docstring_not_file():
    """The model sees the docstring, not the module."""
    _, _, _, prompt = run("prompt", GOOD)
    check(
        "prompt: contains the current docstring",
        "Old step one." in prompt,
        prompt[:200],
    )
    check(
        "prompt: does not contain unrelated code",
        "log = logging.getLogger" not in prompt
        and "Untouched helper" not in prompt,
        "the whole file was sent",
    )
    check(
        "prompt: carries the new steps",
        "Verify the checksum." in prompt,
    )
    print("PASS: prompt_sends_docstring_not_file")


def test_splice_cannot_escape_the_docstring():
    """Even a reply trying to delete code only fills the span."""
    hostile = '"""Short.\n\n        Steps:\n        1. One.\n        """'
    returned, after, _, _ = run("hostile", hostile)
    check("hostile: returns True", returned is True)
    check(
        "hostile: helper survived",
        "def helper():" in after and "return 1" in after,
        after,
    )
    check(
        "hostile: both tests survived",
        "def test_a(self):" in after and "def test_b(self):" in after,
    )
    check("hostile: compiles", compile(after, "<t>", "exec") is not None)
    print("PASS: splice_cannot_escape_the_docstring")


# ── refusals ─────────────────────────────────────────────────────────


def test_truncated_reply_refused():
    """A reply cut off mid-string is refused."""
    returned, after, out, _ = run(
        "trunc", '"""Check the thing works.\n\n   Steps:\n   1. Cre'
    )
    assert_refused("trunc", returned, after, out, "Not updating")
    print("PASS: truncated_reply_refused")


def test_empty_reply_refused():
    """An empty reply is refused."""
    returned, after, out, _ = run("empty", "")
    assert_refused("empty", returned, after, out, "returned nothing")
    print("PASS: empty_reply_refused")


def test_fenced_reply_refused():
    """A fenced reply is refused rather than written literally."""
    returned, after, out, _ = run("fenced", f"```python\n{GOOD}\n```")
    assert_refused("fenced", returned, after, out, "markdown fences")
    print("PASS: fenced_reply_refused")


def test_prose_reply_refused():
    """Chatty output that is not a docstring is refused."""
    returned, after, out, _ = run(
        "prose", f"Sure! Here is the updated docstring:\n\n{GOOD}"
    )
    assert_refused("prose", returned, after, out, "triple-quote")
    print("PASS: prose_reply_refused")


def test_whole_file_reply_refused():
    """A model that echoes the file back is refused."""
    returned, after, out, _ = run("wholefile", SOURCE)
    assert_refused("wholefile", returned, after, out, "Not updating")
    print("PASS: whole_file_reply_refused")


def test_trailing_code_refused():
    """A docstring with code appended after it is refused.

    Only the single-statement check catches this: the text starts with
    a triple-quote and parses fine.
    """
    returned, after, out, _ = run("trailing", f"{GOOD}\nimport os")
    assert_refused(
        "trailing", returned, after, out, "single string literal"
    )
    print("PASS: trailing_code_refused")


def test_no_docstring_refused():
    """A function with no docstring is refused with guidance."""
    src = (
        "class TestThing:\n"
        "    def test_a(self):\n"
        "        assert True\n"
    )
    returned, after, out, _ = run("nodoc", GOOD, source=src)
    assert_refused("nodoc", returned, after, out, "no docstring", before=src)
    print("PASS: no_docstring_refused")


def test_missing_function_refused():
    """An unknown test name is refused."""
    returned, after, out, _ = run(
        "nofn", GOOD, test_name="test_nope"
    )
    assert_refused("nofn", returned, after, out, "not found")
    print("PASS: missing_function_refused")


def test_no_claude_refused():
    """With no claude CLI the file is never even read."""
    returned, after, out, prompt = run("noclaude", GOOD, available=False)
    assert_refused(
        "noclaude", returned, after, out, "claude CLI not available"
    )
    check("noclaude: the CLI was not called", prompt == "", prompt[:80])
    print("PASS: no_claude_refused")


def test_ai_call_failure_refused():
    """An exception from the CLI is reported, not propagated."""
    returned, after, out, _ = run("boom", RuntimeError("timed out"))
    assert_refused("boom", returned, after, out, "AI call failed")
    check("boom: the reason is shown", "timed out" in out, out.strip())
    print("PASS: ai_call_failure_refused")


def test_unchanged_docstring_is_a_no_op():
    """An already-correct docstring writes nothing.

    False here means "nothing to write", not "refused" — worth pinning
    so a caller treating False as failure shows up as a test change.
    """
    returned, after, out, _ = run("same", SAME)
    check("same: returns False", returned is False)
    check("same: file unchanged", after == SOURCE)
    check(
        "same: reported as a no-op, not a refusal",
        "No changes needed" in out and "REFUSING" not in out,
        out.strip(),
    )
    print("PASS: unchanged_docstring_is_a_no_op")


def test_declined_at_prompt():
    """Answering n leaves the file alone."""
    returned, after, _, _ = run("declined", GOOD, answer="n")
    check("declined: returns False", returned is False)
    check("declined: file unchanged", after == SOURCE)
    print("PASS: declined_at_prompt")


# ── runner ───────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_good_docstring_applied,
        test_prompt_sends_docstring_not_file,
        test_splice_cannot_escape_the_docstring,
        test_truncated_reply_refused,
        test_empty_reply_refused,
        test_fenced_reply_refused,
        test_prose_reply_refused,
        test_whole_file_reply_refused,
        test_trailing_code_refused,
        test_no_docstring_refused,
        test_missing_function_refused,
        test_no_claude_refused,
        test_ai_call_failure_refused,
        test_unchanged_docstring_is_a_no_op,
        test_declined_at_prompt,
    ]

    failed = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed.append(t.__name__)
            print(f"FAIL: {t.__name__}\n  {e}")
        print()

    if failed:
        print(f"{len(failed)} of {len(tests)} tests failed:")
        print(f"  {', '.join(failed)}")
        sys.exit(1)
    print(f"All {len(tests)} tests passed.")
