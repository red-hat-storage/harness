"""Constants, templates, and validation sets for polarion-testcase."""

import os

POLARION_BASE = os.environ.get(
    "POLARION_BASE_URL",
    "https://polarion.engineering.redhat.com/polarion/rest/v1",
)
PROJECT = os.environ.get(
    "POLARION_PROJECT", "OpenShiftContainerStorage"
)
_polarion_root = POLARION_BASE.split("/rest/")[0]
POLARION_REDIRECT = f"{_polarion_root}/redirect"
TOKEN_FILE = os.path.expanduser("~/.polarion-token")
CONF_FILE = os.path.expanduser("~/.polarion-testcase.conf")

ACRONYMS = {
    "lso", "cli", "odf", "ocp", "obc", "mcg", "rgw", "mco",
    "ui", "api", "s3", "ocs", "kms", "aws", "gcp", "ibm",
    "rbd", "pvc", "pv", "sc", "crd", "csi", "nvme", "iscsi",
}
VALID_CASEAUTOMATION = {"automated", "notautomated"}
VALID_CASEIMPORTANCE = {"critical", "high", "medium", "low"}

DEFAULT_EXPECTED = "Step completes successfully."

STEPS_FILE_EXAMPLE = """\
steps:
  - step: "Do something to the cluster"
    expected: "Something happens"
  - step: "Verify the result"
    expected: "Result is correct"
setup:           # optional
  - step: "Initialize the environment"
    expected: "Environment is ready"
teardown:        # optional
  - step: "Delete test resources"
    expected: "Resources are removed"
"""

TXT_STEPS_EXAMPLE = """\
Steps:
1. Do something to the cluster
   Expected: Something happens
2. Verify the result
   Expected: Result is correct
Setup:
1. Initialize the environment
   Expected: Environment is ready
Teardown:
1. Delete test resources
   Expected: Resources are removed
"""

EXTRACT_PROMPT = """\
You are analyzing OCS-CI pytest test code. Extract the test steps, setup \
steps, and teardown steps for the function `{test_name}`.

Rules:
- test_steps: numbered items in the `Steps:` (or `Test Steps:`) section of \
the test function docstring. If the docstring has no Steps section but the \
function body has inline comments like `# Step N:`, use those as steps.
- setup_steps: what happens BEFORE the test runs. Look at autouse fixtures. \
If a fixture does setup work (creates resources, initializes objects), those \
are setup steps. If the fixture body only calls `request.addfinalizer`, \
that is NOT a setup step.
- teardown_steps: what happens AFTER the test. Look at the callback functions \
passed to `request.addfinalizer`, or at `teardown_method`, or at any \
`@pytest.fixture(autouse=True)` that explicitly does cleanup.

Write each step as what a human tester would DO, not what the code does \
(e.g. "Select a random mon deployment" not "Call get_mon_deployments()").

Return ONLY a JSON object, no explanation, no markdown fences:
{{"test_steps": [{{"step": "...", "expected": "..."}}],
  "setup_steps": [{{"step": "...", "expected": "..."}}],
  "teardown_steps": [{{"step": "...", "expected": "..."}}]}}

If a section has no steps, return an empty list.
For expected result: if not stated, use "Step completes successfully."

Code:
```python
{code}
```
"""

DECORATOR_PROMPT = """\
Add the decorator `@polarion_id("{wi_id}")` to the Python function \
`{test_name}` in the code below.

Rules:
- Place `@polarion_id("{wi_id}")` immediately above the `def {test_name}` \
line, after any existing decorators on that function.
- If `from ocs_ci.framework.testlib import` is present and does not already \
contain `polarion_id`, add `polarion_id` to that import alphabetically.
- Do NOT change anything else in the file.
- Return ONLY the complete updated file content, with no markdown fences and \
no explanation.

Current file:
{source}
"""

DOCSTRING_PROMPT = """\
Update the docstring of the function `{test_name}` in the code below.
Replace its `Steps:` section with the steps listed here.
If there is no `Steps:` section, add one before the closing triple-quote.
Do NOT change any other part of the docstring or any other part of the file.

New steps:
{steps_text}

Return ONLY the complete updated file content, with no markdown fences and \
no explanation.

Current file:
{source}
"""

CONF_TITLE_PROMPT = """\
Generate a concise, human-readable Polarion test case title for this OCS-CI
deployment configuration scenario.

File name (decoded): {file_stem}
Description: {description}

Rules:
- Sentence-style title, not a slug decode of the file name
- Be specific: platform, storage type, and key scenario characteristics
- Under 120 characters
- Good examples:
  "ODF vSphere LSO CLI deployment with wipe devices on simulated encrypted \
bluestore OSDs (encrypted to encrypted)"
  "ODF AWS IPI storage cluster deployment with in-transit encryption"

Return ONLY the title string, no quotes, no explanation.
"""
