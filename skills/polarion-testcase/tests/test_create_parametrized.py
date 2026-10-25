#!/usr/bin/env python3
"""
Tests for extract_parametrize_info and
create_parametrized_work_items across several real
OCS-CI parametrized tests.

Tests covered:
- deprecated_test_namespace_store_creation_crd (keyword args, tuples)
- test_check_object_integrity        (6 param sets, dicts of constants.*)
- test_respin_mcg_pod_..._rpc        (*["val"] splat, polarion_id marks)
- test_cephfs_subvolume_top_10_ranking  (constants.* values, resolved)

Nothing here may reach the network: api_call is replaced at import
time, so a mock aimed at a stale target fails loudly instead of
POSTing to the live Polarion server.

Usage:
    python tests/test_create_parametrized.py
"""

import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
import polarion_tc_helpers as H  # noqa: E402
from polarion_tc_helpers import (  # noqa: E402
    create_parametrized_work_items,
    extract_parametrize_info,
    get_project_dir,
)


def _no_network(method, url, token, body=None):
    """Stand-in for api_call that refuses to talk to Polarion.

    These tests mock the work-item functions. If a mock ever targets
    the wrong module again, the real one is reached and lands here —
    a loud failure rather than an unauthenticated POST to production.
    """
    raise AssertionError(
        f"unmocked Polarion API call: {method} {url}"
        " — a patch target is stale"
    )


H.api_call = _no_network

# The project under test is configured, not hardcoded — same source the
# skill itself uses. Every test here needs real OCS-CI files, so
# without it they all skip rather than silently reporting success.
PROJECT_DIR = os.environ.get("POLARION_PROJECT_DIR") or get_project_dir()
OCS_CI = Path(PROJECT_DIR) if PROJECT_DIR else None

SKIPPED = []


def _fixture(*parts):
    """Path to an OCS-CI test module, or None if no project dir."""
    return OCS_CI.joinpath(*parts) if OCS_CI else None


TEST_FILE = _fixture(
    "tests", "functional", "object", "mcg", "test_namespace_crd.py"
)
TEST_NAME = "deprecated_test_namespace_store_creation_crd"

OBJ_INTEGRITY_FILE = _fixture(
    "tests", "functional", "object", "mcg", "test_object_integrity.py"
)
OBJ_INTEGRITY_NAME = "test_check_object_integrity"

RESPIN_FILE = _fixture(
    "tests", "functional", "object", "mcg", "test_namespace_rpc.py"
)
RESPIN_NAME = (
    "test_respin_mcg_pod_and_check_data_integrity_rpc"
)

SUBVOL_FILE = _fixture(
    "tests", "functional", "ui", "test_cephfs_subvolume_metrics.py"
)
SUBVOL_NAME = "test_cephfs_subvolume_top_10_ranking"

FAKE_TOKEN = "fake-token"
FAKE_RELATED = "OCS-2255"


def _skip(name, file_path):
    """Record and report a skip when an upstream fixture is absent."""
    SKIPPED.append(name)
    missing = "no project dir configured" if file_path is None else (
        f"{file_path.name} not present"
    )
    print(f"SKIP: {name} — {missing}")
    return None


def _load(file_path, test_name):
    source = file_path.read_text()
    return extract_parametrize_info(source, test_name)


def _load_param_info():
    return _load(TEST_FILE, TEST_NAME)


def _have(file_path):
    """Return True if an upstream fixture file is available."""
    return file_path is not None and file_path.exists()


def test_extract_parametrize_info():
    if not _have(TEST_FILE):
        return _skip("test_extract_parametrize_info", TEST_FILE)
    result = _load_param_info()

    assert result is not None, "Should detect parametrize"
    assert len(result) == 3, (
        f"Expected 3 param sets, got {len(result)}"
    )

    for i, ps in enumerate(result):
        assert ps["index"] == i
        assert "nss_tup" in ps["params"], (
            f"Set [{i}] missing 'nss_tup' key"
        )

    # None of the 3 param sets have polarion_id inside marks
    for ps in result:
        assert ps["existing_polarion_id"] is None

    print("PASS: extract_parametrize_info")
    print(f"  Param sets: {len(result)}")
    for ps in result:
        print(f"  [{ps['index']}] nss_tup={ps['params']['nss_tup']}")


def test_create_parametrized_work_items():
    if not _have(TEST_FILE):
        return _skip("test_create_parametrized_work_items", TEST_FILE)
    param_info = _load_param_info()
    assert param_info is not None

    base_attrs = {
        "type": "testcase",
        "title": "Test Namespace Store Creation CRD",
        "status": "draft",
        "caseautomation": "automated",
        "caseimportance": "high",
        "automationscript": TEST_NAME,
    }

    test_steps = [
        {
            "step": "Create namespace store",
            "expected": "Store created",
        },
        {
            "step": "Verify store status",
            "expected": "Store is ready",
        },
    ]

    wi_counter = {"n": 0}

    def mock_create(token, attrs):
        wi_counter["n"] += 1
        return f"OCS-900{wi_counter['n']}", ""

    with (
        patch(
            "polarion_tc_helpers.create_work_item",
            side_effect=mock_create,
        ) as m_create,
        patch(
            "polarion_tc_helpers.post_test_steps",
            return_value="",
        ) as m_steps,
        patch(
            "polarion_tc_helpers.link_work_item",
            return_value="",
        ) as m_link,
    ):
        results = create_parametrized_work_items(
            FAKE_TOKEN,
            base_attrs,
            test_steps,
            param_info,
            TEST_NAME,
            FAKE_RELATED,
        )

    assert len(results) == 3, (
        f"Expected 3 results, got {len(results)}"
    )

    for r in results:
        assert "index" in r
        assert "wi_id" in r
        assert "params" in r
        assert "error" in r

    for r in results:
        assert r["wi_id"], (
            f"Set [{r['index']}] failed: {r['error']}"
        )
        assert r["error"] == ""

    assert results[0]["wi_id"] == "OCS-9001"
    assert results[1]["wi_id"] == "OCS-9002"
    assert results[2]["wi_id"] == "OCS-9003"

    assert m_create.call_count == 3

    for i, c in enumerate(m_create.call_args_list):
        attrs = c[0][1]
        assert "(" in attrs["title"], (
            f"Call {i}: title missing param suffix:"
            f" {attrs['title']}"
        )
        assert attrs["title"].startswith(
            "Test Namespace Store Creation CRD ("
        )

    for i, c in enumerate(m_create.call_args_list):
        attrs = c[0][1]
        assert attrs["automationscript"].startswith(
            f"{TEST_NAME}["
        ), (
            f"Call {i}: bad automationscript:"
            f" {attrs['automationscript']}"
        )
        assert attrs["automationscript"].endswith("]")

    assert m_steps.call_count == 3
    for c in m_steps.call_args_list:
        assert c[0][2] == test_steps

    assert m_link.call_count == 3
    for c in m_link.call_args_list:
        assert c[0][2] == FAKE_RELATED

    print("PASS: create_parametrized_work_items")
    print(f"  Created: {[r['wi_id'] for r in results]}")
    for r in results:
        attrs = m_create.call_args_list[r["index"]][0][1]
        print(f"  [{r['index']}] {attrs['title']}")
        print(
            f"       automationscript:"
            f" {attrs['automationscript']}"
        )


def test_partial_failure():
    """One param set fails — others still succeed."""
    if not _have(TEST_FILE):
        return _skip("test_partial_failure", TEST_FILE)
    param_info = _load_param_info()

    base_attrs = {
        "type": "testcase",
        "title": "Test Namespace Store Creation CRD",
        "status": "draft",
        "caseautomation": "automated",
        "caseimportance": "high",
        "automationscript": TEST_NAME,
    }

    test_steps = [
        {
            "step": "Create namespace store",
            "expected": "Store created",
        },
    ]

    call_n = {"n": 0}

    def mock_create_with_failure(token, attrs):
        call_n["n"] += 1
        if call_n["n"] == 2:
            return "", '{"error": "API timeout"}'
        return f"OCS-800{call_n['n']}", ""

    with (
        patch(
            "polarion_tc_helpers.create_work_item",
            side_effect=mock_create_with_failure,
        ),
        patch(
            "polarion_tc_helpers.post_test_steps",
            return_value="",
        ) as m_steps,
        patch(
            "polarion_tc_helpers.link_work_item",
            return_value="",
        ) as m_link,
    ):
        results = create_parametrized_work_items(
            FAKE_TOKEN,
            base_attrs,
            test_steps,
            param_info,
            TEST_NAME,
        )

    assert len(results) == 3
    assert results[0]["wi_id"] == "OCS-8001"
    assert results[0]["error"] == ""
    assert results[1]["wi_id"] == ""
    assert results[1]["error"] != ""
    assert results[2]["wi_id"] == "OCS-8003"
    assert results[2]["error"] == ""

    # Steps posted only for successful ones (2 of 3)
    assert m_steps.call_count == 2

    # No related_work_item passed, so link not called
    assert m_link.call_count == 0

    print("PASS: partial_failure")
    for r in results:
        status = r["wi_id"] or "FAILED"
        print(f"  [{r['index']}] {status}")


def test_no_steps_no_link():
    """Empty steps and no related work item."""
    if not _have(TEST_FILE):
        return _skip("test_no_steps_no_link", TEST_FILE)
    param_info = _load_param_info()

    base_attrs = {
        "type": "testcase",
        "title": "Test NSS",
        "status": "draft",
        "caseautomation": "automated",
        "caseimportance": "high",
        "automationscript": TEST_NAME,
    }

    wi_counter = {"n": 0}

    def mock_create(token, attrs):
        wi_counter["n"] += 1
        return f"OCS-700{wi_counter['n']}", ""

    with (
        patch(
            "polarion_tc_helpers.create_work_item",
            side_effect=mock_create,
        ),
        patch(
            "polarion_tc_helpers.post_test_steps",
        ) as m_steps,
        patch(
            "polarion_tc_helpers.link_work_item",
        ) as m_link,
    ):
        results = create_parametrized_work_items(
            FAKE_TOKEN,
            base_attrs,
            [],
            param_info,
            TEST_NAME,
            None,
        )

    assert len(results) == 3
    for r in results:
        assert r["wi_id"]

    assert m_steps.call_count == 0
    assert m_link.call_count == 0

    print("PASS: no_steps_no_link")


# ── test_check_object_integrity ──────────────────────────────────────


def test_extract_object_integrity():
    """6 param sets, keyword argnames (string), complex dicts,
    no polarion_id in marks."""
    if not _have(OBJ_INTEGRITY_FILE):
        return _skip("test_extract_object_integrity", OBJ_INTEGRITY_FILE)
    result = _load(OBJ_INTEGRITY_FILE, OBJ_INTEGRITY_NAME)

    assert result is not None, "Should detect parametrize"
    assert len(result) == 6, (
        f"Expected 6 param sets, got {len(result)}"
    )

    for i, ps in enumerate(result):
        assert ps["index"] == i
        assert "bucketclass_dict" in ps["params"]

    # First param set value is None (literal)
    assert result[0]["params"]["bucketclass_dict"] is None

    # Second has a dict with aws key
    val1 = result[1]["params"]["bucketclass_dict"]
    assert isinstance(val1, dict)
    assert "aws" in val1.get("backingstore_dict", {})

    # None have polarion_id (marks are tier1/tier2)
    for ps in result:
        assert ps["existing_polarion_id"] is None

    print("PASS: extract_object_integrity")
    for ps in result:
        v = ps["params"]["bucketclass_dict"]
        label = "None" if v is None else str(v)[:50]
        print(f"  [{ps['index']}] {label}")


def test_create_object_integrity():
    """Create 6 work items for test_check_object_integrity."""
    if not _have(OBJ_INTEGRITY_FILE):
        return _skip("test_create_object_integrity", OBJ_INTEGRITY_FILE)
    param_info = _load(
        OBJ_INTEGRITY_FILE, OBJ_INTEGRITY_NAME
    )

    base_attrs = {
        "type": "testcase",
        "title": "Test Check Object Integrity",
        "status": "draft",
        "caseautomation": "automated",
        "caseimportance": "high",
        "automationscript": OBJ_INTEGRITY_NAME,
    }

    test_steps = [
        {
            "step": "Write objects to bucket",
            "expected": "Objects written",
        },
        {
            "step": "Read objects and verify integrity",
            "expected": "Checksums match",
        },
    ]

    wi_counter = {"n": 0}

    def mock_create(token, attrs):
        wi_counter["n"] += 1
        return f"OCS-600{wi_counter['n']}", ""

    with (
        patch(
            "polarion_tc_helpers.create_work_item",
            side_effect=mock_create,
        ) as m_create,
        patch(
            "polarion_tc_helpers.post_test_steps",
            return_value="",
        ) as m_steps,
        patch(
            "polarion_tc_helpers.link_work_item",
            return_value="",
        ) as m_link,
    ):
        results = create_parametrized_work_items(
            FAKE_TOKEN,
            base_attrs,
            test_steps,
            param_info,
            OBJ_INTEGRITY_NAME,
            FAKE_RELATED,
        )

    assert len(results) == 6
    assert m_create.call_count == 6
    assert m_steps.call_count == 6
    assert m_link.call_count == 6

    for r in results:
        assert r["wi_id"], (
            f"Set [{r['index']}] failed: {r['error']}"
        )

    for i, c in enumerate(m_create.call_args_list):
        attrs = c[0][1]
        assert attrs["title"].startswith(
            "Test Check Object Integrity ("
        )
        assert attrs["automationscript"].startswith(
            f"{OBJ_INTEGRITY_NAME}["
        )

    print("PASS: create_object_integrity")
    print(f"  Created: {[r['wi_id'] for r in results]}")


# ── test_respin_mcg_pod_and_check_data_integrity_rpc ─────────────────


def test_extract_respin():
    """3 param sets, keyword argnames (list), *[] splat values,
    each has polarion_id in marks."""
    if not _have(RESPIN_FILE):
        return _skip("test_extract_respin", RESPIN_FILE)
    result = _load(RESPIN_FILE, RESPIN_NAME)

    assert result is not None, "Should detect parametrize"
    assert len(result) == 3, (
        f"Expected 3 param sets, got {len(result)}"
    )

    for i, ps in enumerate(result):
        assert ps["index"] == i
        assert "mcg_pod" in ps["params"]

    # A *["val"] splat has no literal value, so it is unparsed back to
    # source. It used to collapse to "<expr>", which lost the pod name
    # and gave every param set the same automationscript suffix.
    values = [ps["params"]["mcg_pod"] for ps in result]
    assert values == [
        "*['noobaa-db']",
        "*['noobaa-core']",
        "*['noobaa-operator']",
    ], f"Unexpected splat rendering: {values}"

    # Each has a distinct polarion_id, in param order. Exact IDs are
    # asserted because they prove each mark maps to its own param set.
    ids = [ps["existing_polarion_id"] for ps in result]
    assert ids == ["OCS-2291", "OCS-2319", "OCS-2320"]

    print("PASS: extract_respin")
    for ps in result:
        print(
            f"  [{ps['index']}] mcg_pod={ps['params']['mcg_pod']}"
            f"  existing={ps['existing_polarion_id']}"
        )


def test_create_respin():
    """Create 3 work items for respin test."""
    if not _have(RESPIN_FILE):
        return _skip("test_create_respin", RESPIN_FILE)
    param_info = _load(RESPIN_FILE, RESPIN_NAME)

    base_attrs = {
        "type": "testcase",
        "title": "Test Respin MCG Pod Check Data Integrity RPC",
        "status": "draft",
        "caseautomation": "automated",
        "caseimportance": "high",
        "automationscript": RESPIN_NAME,
    }

    test_steps = [
        {
            "step": "Respin the MCG pod",
            "expected": "Pod restarts",
        },
    ]

    wi_counter = {"n": 0}

    def mock_create(token, attrs):
        wi_counter["n"] += 1
        return f"OCS-500{wi_counter['n']}", ""

    with (
        patch(
            "polarion_tc_helpers.create_work_item",
            side_effect=mock_create,
        ) as m_create,
        patch(
            "polarion_tc_helpers.post_test_steps",
            return_value="",
        ) as m_steps,
        patch(
            "polarion_tc_helpers.link_work_item",
            return_value="",
        ),
    ):
        results = create_parametrized_work_items(
            FAKE_TOKEN,
            base_attrs,
            test_steps,
            param_info,
            RESPIN_NAME,
        )

    assert len(results) == 3
    assert m_create.call_count == 3
    assert m_steps.call_count == 3

    for r in results:
        assert r["wi_id"]
        assert r["error"] == ""

    # The splat value reaches the automationscript suffix, so the three
    # work items are distinguishable. Under the old "<expr>" rendering
    # all three suffixes were identical.
    scripts = [
        c[0][1]["automationscript"] for c in m_create.call_args_list
    ]
    assert scripts == [
        f"{RESPIN_NAME}[*['noobaa-db']]",
        f"{RESPIN_NAME}[*['noobaa-core']]",
        f"{RESPIN_NAME}[*['noobaa-operator']]",
    ], f"Unexpected automationscripts: {scripts}"
    assert len(set(scripts)) == 3

    print("PASS: create_respin")
    print(f"  Created: {[r['wi_id'] for r in results]}")


# ── test_cephfs_subvolume_top_10_ranking ─────────────────────────────


def test_extract_subvolume():
    """3 param sets, constants.* values resolved to their literals."""
    if not _have(SUBVOL_FILE):
        return _skip("test_extract_subvolume", SUBVOL_FILE)
    result = _load(SUBVOL_FILE, SUBVOL_NAME)

    assert result is not None, "Should detect parametrize"
    assert len(result) == 3, (
        f"Expected 3 param sets, got {len(result)}"
    )

    for i, ps in enumerate(result):
        assert ps["index"] == i
        assert "metric" in ps["params"]

    # A constants.* reference is followed into the imported module and
    # replaced by its literal. These used to come back as "<expr>",
    # which put no usable metric name in the title.
    values = [ps["params"]["metric"] for ps in result]
    assert all(isinstance(v, str) for v in values), values
    assert not any(
        v == "<expr>" or v.startswith("constants.") for v in values
    ), f"constants were not resolved: {values}"
    assert len(set(values)) == 3, f"metrics not distinct: {values}"

    # IDs are asserted by shape, not value: this fixture is an upstream
    # file and its placeholder OCS-XXXX IDs have since become real ones.
    ids = [ps["existing_polarion_id"] for ps in result]
    assert all(
        i and re.fullmatch(r"OCS-(\d+|X+)", i) for i in ids
    ), f"Unexpected polarion IDs: {ids}"
    assert len(set(ids)) == 3, f"IDs not distinct: {ids}"

    print("PASS: extract_subvolume")
    for ps in result:
        print(
            f"  [{ps['index']}] metric={ps['params']['metric']}"
            f"  existing={ps['existing_polarion_id']}"
        )


def test_create_subvolume():
    """Create 3 work items for subvolume ranking test."""
    if not _have(SUBVOL_FILE):
        return _skip("test_create_subvolume", SUBVOL_FILE)
    param_info = _load(SUBVOL_FILE, SUBVOL_NAME)

    base_attrs = {
        "type": "testcase",
        "title": "Test CephFS Subvolume Top 10 Ranking",
        "status": "draft",
        "caseautomation": "automated",
        "caseimportance": "high",
        "automationscript": SUBVOL_NAME,
    }

    test_steps = [
        {
            "step": "Select metric from dropdown",
            "expected": "Metric selected",
        },
        {
            "step": "Verify top-10 table rows",
            "expected": "10 rows displayed",
        },
    ]

    wi_counter = {"n": 0}

    def mock_create(token, attrs):
        wi_counter["n"] += 1
        return f"OCS-400{wi_counter['n']}", ""

    with (
        patch(
            "polarion_tc_helpers.create_work_item",
            side_effect=mock_create,
        ) as m_create,
        patch(
            "polarion_tc_helpers.post_test_steps",
            return_value="",
        ) as m_steps,
        patch(
            "polarion_tc_helpers.link_work_item",
            return_value="",
        ) as m_link,
    ):
        results = create_parametrized_work_items(
            FAKE_TOKEN,
            base_attrs,
            test_steps,
            param_info,
            SUBVOL_NAME,
            "OCS-1234",
        )

    assert len(results) == 3
    assert m_create.call_count == 3
    assert m_steps.call_count == 3
    assert m_link.call_count == 3

    for r in results:
        assert r["wi_id"]
        assert r["error"] == ""

    # The resolved metric name reaches both the title and the
    # automationscript, so the three work items are distinguishable.
    # Under the old "<expr>" rendering all three were identical.
    metrics = [ps["params"]["metric"] for ps in param_info]
    titles = [c[0][1]["title"] for c in m_create.call_args_list]
    scripts = [
        c[0][1]["automationscript"] for c in m_create.call_args_list
    ]
    assert titles == [
        f"Test CephFS Subvolume Top 10 Ranking (metric={m})"
        for m in metrics
    ], f"Unexpected titles: {titles}"
    assert scripts == [
        f"{SUBVOL_NAME}[{m}]" for m in metrics
    ], f"Unexpected automationscripts: {scripts}"
    assert len(set(scripts)) == 3

    print("PASS: create_subvolume")
    print(f"  Created: {[r['wi_id'] for r in results]}")


# ── runner ───────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        # deprecated_test_namespace_store_creation_crd
        test_extract_parametrize_info,
        test_create_parametrized_work_items,
        test_partial_failure,
        test_no_steps_no_link,
        # test_check_object_integrity
        test_extract_object_integrity,
        test_create_object_integrity,
        # test_respin_mcg_pod_and_check_data_integrity_rpc
        test_extract_respin,
        test_create_respin,
        # test_cephfs_subvolume_top_10_ranking
        test_extract_subvolume,
        test_create_subvolume,
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
    passed = len(tests) - len(SKIPPED)
    if not passed:
        print(f"No tests ran — all {len(SKIPPED)} skipped.")
        sys.exit(1)
    print(f"All {passed} tests passed.")
    if SKIPPED:
        print(f"{len(SKIPPED)} skipped: {', '.join(SKIPPED)}")
