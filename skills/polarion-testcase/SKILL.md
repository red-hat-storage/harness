---
name: polarion-testcase
description: >
  Create or update a Polarion test case. Create mode reads a Python test
  function or deployment conf YAML file to extract steps and creates the
  work item. Update mode posts steps or adds links to an existing work
  item. The Polarion project is controlled by the POLARION_PROJECT env
  var (default: OpenShiftContainerStorage).
allowed_prompts:
  - tool: Bash
    prompt: "run create_polarion_tc.py or update_polarion_tc.py script"
  - tool: Edit
    prompt: "add polarion_id import and decorator to test file"
---

# polarion-testcase — Create or Update Polarion Test Case

## Overview

Drives `create_polarion_tc.py` and `update_polarion_tc.py` (from the
polarion-testcase repo) to create or update Polarion test cases. Shared
logic lives in `polarion_tc_helpers.py` and constants in `constants.py`.

**Create mode:** extracts steps from a Python test function or conf YAML file,
creates the work item via the Polarion REST API, and adds the `@polarion_id`
decorator to the source file.

**Update mode:** posts steps and/or adds a related work item link to an
existing Polarion test case. Use when the test case already exists but is
missing steps or a link.

For conf files (`.yaml`/`.yml`), the script handles everything natively —
this skill simply passes the file path through and lets the script run
interactively. Conf files are only supported in create mode.

## Invocation

```
# Create mode:
/polarion-testcase create <file_path>::<test_function_name> [key=value ...]
/polarion-testcase create <file_path>::<ClassName>::<test_function_name> [key=value ...]
/polarion-testcase create <conf_file.yaml> [key=value ...]

# Update mode:
/polarion-testcase update <OCS-ID> related=OCS-XXXX
/polarion-testcase update <OCS-ID> <file_path>::<test_name> [related=OCS-XXXX]
/polarion-testcase update <OCS-ID> <file_path>::<ClassName>::<test_name> [related=OCS-XXXX]
/polarion-testcase update <OCS-ID> steps-file=<path> [related=OCS-XXXX]
```

Examples:
```
# Create:
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature related=OCS-7430
/polarion-testcase create tests/functional/ui/test_foo.py::TestMyClass::test_my_feature related=OCS-7430
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature related=OCS-7430 importance=critical
/polarion-testcase create test_my_feature          # file path omitted — skill will search tests/
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature automation=notautomated
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature setup="Deploy ODF cluster." teardown="Delete all created resources."
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature steps-file=/tmp/my_steps.yaml
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature no-steps
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature steps-from-code
/polarion-testcase create conf/deployment/vsphere/upi_1az_rhcos_vsan_lso_vmdk.yaml related=OCS-7430
# Parametrized tests:
/polarion-testcase create tests/functional/z_cluster/test_foo.py::test_bar param=all
/polarion-testcase create tests/functional/z_cluster/test_foo.py::test_bar param=0

# Update:
/polarion-testcase update OCS-8221 related=OCS-7430
/polarion-testcase update OCS-8221 tests/functional/ui/test_foo.py::test_my_feature
/polarion-testcase update OCS-8221 tests/functional/ui/test_foo.py::TestMyClass::test_my_feature related=OCS-7430
/polarion-testcase update OCS-8221 steps-file=/tmp/my_steps.yaml
```

## Help

If invoked with no arguments or `help`, display:

```
/polarion-testcase — Create or update a Polarion test case

Usage:
  /polarion-testcase create <file_path>::<test_function_name> [key=value ...]
  /polarion-testcase create <file_path>::<ClassName>::<test_function_name> [key=value ...]
  /polarion-testcase create <conf_file.yaml> [key=value ...]
  /polarion-testcase update <OCS-ID> [<file_path>::<test_name>] [related=OCS-XXXX]
  /polarion-testcase update <OCS-ID> [steps-file=<path>] [related=OCS-XXXX]

Modes:
  create               Create a new Polarion test case (required as first argument)
  update               Update an existing Polarion test case (required as first argument)

Create mode arguments:
  file_path            Path to the test .py file (optional if test name is unique)
  ClassName            Optional test class name (e.g. TestRbdCBTMetadata) for disambiguation
  test_function_name   Python test method name (e.g. test_add_capacity_cli)
  conf_file.yaml       Path to a deployment .yaml/.yml conf file

Update mode arguments:
  OCS-ID               Existing Polarion work item ID (e.g. OCS-8221)
  related=OCS-XXXX     Link the work item to another Polarion ID
  file_path::test_name Extract and post steps from this test function
  steps-file=<path>    Post steps from a YAML or plain-text file

Optional key=value overrides:
  related=<ID>         Polarion ID to link as relates_to (e.g. OCS-7430)
  importance=<level>   critical|high|medium|low  (default: high)
  automation=<value>   automated|notautomated  (default: automated)
  title=<text>         Override auto-generated title
  description=<text>   Override description extracted from docstring/file
  setup=<text>         Override setup text extracted from fixture (plain text)
  teardown=<text>      Override teardown text extracted from fixture (plain text)
  status=<value>       Polarion status (default: draft)
  steps-file=<path>    Path to a YAML or plain-text (.txt) file with steps
  no-steps             Skip step generation; create the test case without steps
  steps-from-code      Ignore the docstring Steps: section; derive steps from
                       the test function body and fixture code instead
  param=all            Create work items for ALL parametrize sets
  param=<N>            Create a work item for param set N (0-based index)
                       If omitted on a parametrized test, auto-detects and asks

Steps YAML format (for steps-file=):
  steps:
    - step: "Do X"
      expected: "X happens."
    - step: "Do Y"
      expected: "Y completes."

Steps text format (for steps-file=*.txt):
  1. Do X
     Expected: X happens.
  2. Do Y
     Expected: Y completes.
  Optional section headers: Setup:, Steps:, Teardown:
  Freeform text is auto-converted via AI if no numbered steps found.

What it does (create — test file):
  1. Resolves the test file path
  2. Extracts steps and generates expected results, shows preview for confirmation
  3. Runs create_polarion_tc.py (handles API calls)
  4. Adds @polarion_id("<NEW_ID>") decorator to the test file

What it does (create — parametrized test, param=all):
  1. Detects @pytest.mark.parametrize, shows all param sets
  2. Extracts steps using {argname} placeholders for parametrized values
  3. Creates one Polarion work item per param set (title, steps, and
     description are customized with the actual param values)
  4. Shows summary with all created IDs and URLs

What it does (create — conf file):
  Runs create_polarion_tc.py directly — the script reads the
  file's header comments for the description, generates a title, previews, and
  writes deployment_id back into REPORTING.polarion in the YAML file.

What it does (update mode):
  1. Validates the work item ID
  2. If a test file or steps-file is specified: extracts steps, shows preview
  3. Posts steps and/or links to the existing work item via update_polarion_tc.py
  4. Reports results (no decorator/docstring offers)

File structure:
  create_polarion_tc.py    — Create mode entry point
  update_polarion_tc.py    — Update mode entry point
  polarion_tc_helpers.py   — Shared helper functions (API, AST, steps, display)
  constants.py             — All constants, templates, and validation sets
```

Then stop.

---

## Workflow

### Step 0: Load Configuration

Read `~/.polarion-testcase.conf` to get two variables:
- `POLARION_SCRIPT_PATH` — absolute path to `create_polarion_tc.py`
- `POLARION_PROJECT_DIR` — absolute path to the Python project root

Derive the update script path from the create script path:
- `POLARION_UPDATE_SCRIPT_PATH` — `$(dirname $POLARION_SCRIPT_PATH)/update_polarion_tc.py`

If the file does not exist, print:
```
Error: ~/.polarion-testcase.conf not found.
Run install.sh first: ./install.sh --project /path/to/python-project
```
Then stop.

The create script is invoked via `python3 $POLARION_SCRIPT_PATH`. The update
script is invoked via `python3 $POLARION_UPDATE_SCRIPT_PATH`. Both scripts
automatically resolve relative `--test-path` values against
`POLARION_PROJECT_DIR` from the config, so callers can pass relative paths.
Use `$POLARION_PROJECT_DIR` for grep lookups in Step 2.

### Step 1: Validate Input and Detect Mode

If no argument provided or argument is `help`, show help text and stop.

**Parse the first positional token as the mode:**
- Must be `create` or `update`. If anything else, print:
  ```
  Error: First argument must be 'create' or 'update'.
  Run /polarion-testcase help for usage.
  ```
  Then stop.

**If mode is `create`:**

Detect the sub-mode from the next token:
- If it ends in `.yaml` or `.yml` → **CONF FILE MODE**: skip to Step 4 directly.
  No step extraction is needed — the script handles everything interactively.
- Otherwise → **TEST FILE MODE**: continue with Steps 2–5.

Parse remaining arguments:
- Split on `::` to get the path components. Three forms are supported:
  - `file_path::test_name` (2 parts) → `file_path`, `test_name`, no `class_name`
  - `file_path::ClassName::test_name` (3 parts) → `file_path`, `class_name`, `test_name`
  - `test_name` (no `::`) → `file_path` must be found via grep, no `class_name`
  The middle component is a class name if it starts with an uppercase letter
  and does NOT start with `test_`.
- All remaining tokens are optional overrides:
  - `related=<ID>` → `--related-work-item` (e.g. `related=OCS-7430`)
  - `importance=<value>` → `--caseimportance` (default: `high`)
  - `automation=<value>` → `--caseautomation` (default: `automated`)
  - `title=<text>` → `--title`
  - `description=<text>` → `--description`
  - `setup=<text>` → `--setup` (suppresses auto-extraction from fixture)
  - `teardown=<text>` → `--teardown` (suppresses auto-extraction from fixture)
  - `status=<value>` → `--status` (default: `draft`)
  - `steps-file=<path>` → path to a user-supplied steps file (YAML or .txt)
  - `no-steps` (flag, no value) → skip all step generation
  - `steps-from-code` (flag, no value) → ignore the docstring `Steps:` section
    and derive steps from the test function body instead
- When `setup=` or `teardown=` is explicitly provided by the user, skip the
  auto-extraction from fixture bodies in Step 3 for that field and use the
  user-provided value verbatim.
- `steps-file=`, `no-steps`, and `steps-from-code` are mutually exclusive;
  if more than one is given, print an error and stop.
- `param=all` → `--parametrize-all` flag on the script
- `param=<N>` (integer) → `--param-index <N>` on the script
- If no `param=` is given, parametrize is auto-detected in Step 2.5.

**If mode is `update`:**

- Second token is the work item ID (e.g. `OCS-8221`). Required.
  If missing, print error and stop.
- Remaining tokens:
  - `related=OCS-XXXX` → related work item to link
  - A token containing `::` → `file_path::test_name` or
    `file_path::ClassName::test_name` for step extraction.
    Parse by splitting on `::` (same logic as create mode).
  - `steps-file=<path>` → pre-written steps file
  - `no-steps` is NOT valid in update mode (error if given)
- At least one of `related=` or a `file_path::test_name` or `steps-file=`
  must be present. If none, print error and stop.
- Continue to Step 3U for step extraction, then Step 4U for script invocation.

### Step 2: Resolve the Test File

If `file_path` was given, use it directly.

Otherwise grep for `def <test_name>` under `$POLARION_PROJECT_DIR/tests/` to find the file:
```
grep -r "def <test_name>" $POLARION_PROJECT_DIR/tests/ --include="*.py" -l
```
If multiple files match, report them and stop — ask the user to pass the full
`file_path::test_name` form.

### Step 2.1: Check for Existing Polarion ID (TEST FILE MODE only)

Read the test file and look at the decorators on the target test function.
If the function already has a `@polarion_id("OCS-XXXX")` decorator, warn
the user and ask for confirmation before proceeding.

Print:
```
WARNING: This test already has a Polarion ID: OCS-XXXX
```

Then ask using AskUserQuestion:
"This test already has @polarion_id("OCS-XXXX"). Creating a new test case
will result in a duplicate. Do you want to proceed?"
- Option 1: "Yes, create a new test case anyway"
- Option 2: "No, stop"

If the user chooses "No, stop", stop immediately.

For parametrized tests, this check applies to function-level `@polarion_id`
decorators only. Per-param-set `polarion_id` marks inside `pytest.param()`
are reported separately in Step 2.5.

### Step 2.5: Detect Parametrize (TEST FILE MODE only)

Read the test file and check whether the target function has a
`@pytest.mark.parametrize` decorator.

**If `param=all` was given:** skip detection — go straight to Step 3
with the parametrize-all flag set.

**If `param=<N>` was given:** validate that `N` is within range of the
detected param sets. If out of range, print an error and stop.

**If no `param=` was given and parametrize IS detected:**

1. Parse the `@pytest.mark.parametrize` decorator using AST to extract:
   - `argnames`: the parameter names
   - `argvalues`: each param set's values
   - Any existing `polarion_id` marks inside `pytest.param()`

2. Print all param sets to the user:
   ```
   Parametrized test detected with <N> param set(s):
     [0] mon_timeout=3m, mon_interval=20s (existing: OCS-7428)
     [1] mon_timeout=12m, mon_interval=30s (existing: OCS-7429)
   ```

3. Ask the user using AskUserQuestion:
   "This test is parametrized. Create work items for all param sets
   or just one?"
   - Option 1: "All param sets" — continue to Step 3 with
     parametrize-all set.
   - Option 2: "One specific param set" — tell the user to rerun
     with `param=<N>` and the index they want, then stop:
     ```
     Rerun with param=<N> for a specific param set. Example:
       /polarion-testcase <file>::<test_name> param=0
     ```

**If no `param=` and test is NOT parametrized:** continue normally.

### Step 3: Extract Steps and Confirm with User

**If `no-steps` was given:** skip all step extraction below. Show the preview
without a Steps section and continue.

**If `steps-file=<path>` was given:**

**YAML files** (`.yaml` / `.yml`):
- Read the file at `<path>`. Validate that:
  - The file exists and is non-empty.
  - It is valid YAML with a top-level `steps:` list where each item has a
    `step:` key (the `expected:` key is optional but recommended).
- If validation fails, print:
  ```
  Error: <path> is not a valid steps YAML file.
  Expected format:
    steps:
      - step: "Do X"
        expected: "X happens."
  Please fix the file or re-run without steps-file= to auto-generate steps.
  ```
  Then stop.
- If valid, use those steps verbatim as the step list. Skip auto-extraction.

**Plain text files** (`.txt`):
- Read the file at `<path>`. Validate that it exists and is non-empty.
- Check if the file contains numbered steps (lines matching `<digits>. <text>`).
- **If numbered steps found**: pass the file directly to the script — the
  script's built-in `parse_steps_txt()` parser handles it. Use the file as-is.
- **If NO numbered steps found** (freeform text): use **AI fallback**:
  1. Read the file content using the Read tool (do NOT use shell interpolation).
  2. Write a prompt file to `/tmp/polarion_convert_prompt.txt` containing:
     ```
     Convert the following test steps into YAML format.
     Output ONLY valid YAML with no markdown fences, matching this schema:
     steps:
       - step: "..."
         expected: "..."
     setup:
       - step: "..."
         expected: "..."
     teardown:
       - step: "..."
         expected: "..."
     Only include setup/teardown sections if the input describes them.

     Input:
     <paste the file content here>
     ```
  3. Run:
     ```bash
     claude -p "$(cat /tmp/polarion_convert_prompt.txt)" > /tmp/polarion_steps_converted.yaml
     ```
  4. Strip any leading/trailing markdown fences (` ```yaml ` / ` ``` `) from
     the output file if present.
  5. Validate the converted YAML (same checks as YAML files above).
  6. If valid, tell the user: `"AI-converted freeform text to YAML steps."`
     Then use `/tmp/polarion_steps_converted.yaml` as the steps file path
     (replacing the original `.txt` path for the script invocation).
  7. If invalid, print:
     ```
     Error: AI conversion of <path> produced invalid YAML.
     Please rewrite the file using numbered steps or YAML format.
     ```
     Then stop.

**Otherwise (normal auto-extraction):**

Read the test file. Always build the steps list yourself before running the
script — do NOT rely on the script's internal extraction (which produces
generic "Step completes successfully." expected results).

Extract step text:
- **If `steps-from-code` was given:** skip the docstring entirely. Read the
  test function body (and any autouse fixture bodies) and derive logical
  steps from the actual code — write what a human tester would do at each
  step, not what the code calls. This is useful when the docstring `Steps:`
  section is outdated or incomplete compared to the code.
- If the target function's docstring has a `Steps:` section (numbered lines
  under `Steps:`), use those as the step text verbatim.
- Otherwise, read the test function body (and any autouse fixture bodies) and
  derive logical steps — write what a human tester would do at each step, not
  what the code calls.

Generate expected results for each step — write a concrete, specific expected
result that describes what the user would observe if the step succeeded. Do NOT
use generic phrases like "Step completes successfully." Examples:
- Step: "Verify ODF console plugin pod is in Running state."
  → Expected: "ODF console plugin pod(s) are found in openshift-storage and all are in Running phase."
- Step: "Navigate to Storage Cluster > Block and File tab."
  → Expected: "Block and File tab is active and visible in the Storage Cluster page."
- Step: "Verify the subvolume card is visible."
  → Expected: "CephFS subvolume metrics card title is present and rendered on the page."
- Step: "Switch to 'Total IOPS' and verify column header."
  → Expected: "Last column header reads 'Total IOPS' and all 3 test namespace rows are present with non-zero values."

**Parametrized tests (`param=all` or `param=<N>`) — use `{argname}` placeholders:**

When the test is parametrized, write steps and expected results using
`{argname}` placeholders wherever the parametrized value should appear.
The script substitutes these with the actual param value per work item.

For example, if `argnames=["metric"]` and the param sets are
`Total IOPS`, `Total Latency`, `Total Throughput`:

- Step: `"Switch to '{metric}'."` (NOT `"Switch to the parametrized metric
  (Total IOPS / Total Latency / Total Throughput)."`)
- Expected: `"The last column header reads '{metric}'."`

The placeholder must match the `argnames` exactly, wrapped in braces:
`{metric}`, `{mon_timeout}`, etc. Use placeholders in step text, expected
results, and description wherever the per-param value should appear.

**Also derive:**
- **Description**: function docstring text before the `Steps:` section (first
  paragraph), or the class docstring first sentence, or a one-sentence summary
  derived from the test name. For parametrized tests, use `{argname}`
  placeholders where the description should mention the specific param value.
- **Setup**: summarise the autouse `setup` / `init_sanity` fixture body in one
  or two plain-text sentences (if any). Skip if user passed `setup=`.
- **Teardown**: summarise the autouse `teardown` fixture body in one or two
  plain-text sentences (if any). Skip if user passed `teardown=`.

**Show preview and wait for confirmation:**

Display the full step list to the user. For parametrized tests, show the
template with placeholders and an example substitution for the first param set:

```
Title:       <base title> (each param set appends its values)
Description: <description with {argname} placeholders>

Steps template (placeholders will be substituted per param set):
  1. <step text with {argname} placeholders>
     Expected: <expected result with {argname} placeholders>
  ...

Example for param set [0] (<argname>=<first_value>):
  Title:       <base title> (<argname>=<first_value>)
  Description: <description with substituted value>
  1. <step text with substituted value>
     Expected: <expected result with substituted value>

Setup:       <setup text or "(none)">
Teardown:    <teardown text or "(none)">

Proceed with creating the Polarion test case? [y/N]
```

For non-parametrized tests, show the plain step list without template info:

```
Title:       <title>
Description: <description>

Steps to be created in Polarion:
  1. <step text>
     Expected: <expected result>
  ...
  (none — no-steps was set)   ← shown when no-steps flag given

Setup:       <setup text or "(none)">
Teardown:    <teardown text or "(none)">

Proceed with creating the Polarion test case? [y/N]
```

Wait for the user's response. If `n` or empty, stop. If `y`, continue.

### Step 3U: Extract Steps for Update Mode (UPDATE MODE only)

Skip this step entirely if mode is `create`.

**If only `related=` was given (no test file, no steps-file):** skip this step.

**If a `file_path::test_name` was provided:**

1. Resolve the test file (same as Step 2 for create mode).
2. Read the file and find the test function.
3. Extract steps (same as Step 3 for create mode — read the docstring Steps
   section, or derive steps from the test function body). Generate expected
   results for each step.
4. Show preview and confirm:
   ```
   Steps to post to OCS-8221:
     1. <step text>
        Expected: <expected result>
     ...

   Post these steps to OCS-8221? [y/N]
   ```
   Wait for response. If `n` or empty, stop. If `y`, continue.

**If `steps-file=<path>` was given (no test file):**

1. Validate and load the file (same validation as Step 3 for create mode).
2. Show preview and confirm (same format as above).

### Step 4: Run the Python Script (CREATE MODE)

**Note:** For update mode, skip to Step 4U below.

**CONF FILE MODE** — skip step extraction, run the script directly and let it
run interactively (do not pipe stdin). Shell-quote all interpolated values:
```bash
python3 "$POLARION_SCRIPT_PATH" \
    --test-path <conf_file> \
    --caseimportance <importance> \
    --caseautomation <automation> \
    [--title '<TITLE>'] \
    [--description '<DESCRIPTION>'] \
    [--status '<STATUS>'] \
    [--related-work-item <related_work_item>]
```
The script handles description extraction, title generation, preview,
creation, and writing `deployment_id` back to the YAML file. Stop after
the script exits — no Step 5.

---

**TEST FILE MODE** — determine the steps source and build the script
invocation:

**Case A — `no-steps` flag given:**
Pass `--no-generate-steps` and do NOT pass `--test-steps-file`. No steps YAML
is written.

**Case B — `steps-file=<path>` given (already validated in Step 3):**
Pass `--no-generate-steps --test-steps-file <path>` using the user's file
directly (works for both `.yaml` and `.txt` files — the script handles both).
Do NOT write a separate `/tmp/polarion_steps.yaml`.
If AI fallback was used (freeform `.txt` converted in Step 3), pass
`/tmp/polarion_steps_converted.yaml` as the `<path>` instead.

**Case C — auto-extracted steps (default):**
Write the confirmed steps to `/tmp/polarion_steps.yaml`:
```yaml
steps:
  - step: "Do X"
    expected: "X happens successfully."
  - step: "Do Y"
    expected: "Y completes successfully."
```
Pass `--no-generate-steps --test-steps-file /tmp/polarion_steps.yaml`.

Then run (**shell-quote all interpolated values** — titles, descriptions,
setup, and teardown text may contain quotes, parentheses, or other shell
metacharacters; always use single-quoted arguments or `printf '%s'` to avoid
shell injection):
```bash
printf 'y\nn\nn\n' | python3 "$POLARION_SCRIPT_PATH" \
    --test-path <file_path> \
    --test-name <test_name> \
    [--class-name <class_name>] \
    --caseimportance <importance> \
    --caseautomation <automation> \
    [--no-generate-steps] \
    [--test-steps-file <steps_path>] \
    [--title '<TITLE>'] \
    [--description '<DESCRIPTION>'] \
    [--setup '<SETUP_TEXT>'] \
    [--teardown '<TEARDOWN_TEXT>'] \
    [--status '<STATUS>'] \
    [--related-work-item <related_work_item>] \
    [--parametrize-all] \
    [--param-index <N>]
```

Only include a flag when the corresponding value is non-empty. For `--setup`
and `--teardown`: use the user-provided value if given via `setup=`/`teardown=`
args; otherwise use the auto-extracted text from Step 3.

**Parametrize flags:**
- If `param=all` was set in Step 2.5 → pass `--parametrize-all`.
  The stdin pipe becomes `printf 'y\n'` (one confirmation for all items,
  no decorator/docstring offers).
- If `param=<N>` was set → pass `--param-index <N>`.
  The stdin pipe remains `printf 'y\nn\nn\n'` (same as non-parametrized).
- Neither → normal non-parametrized flow.

The `y/n` answers for non-parametrized correspond to:
1. "Create this Polarion test case?" → `y`
2. "Add @polarion_id(...) decorator?" → `n`  (we handle this correctly in Step 5)
3. "Update test docstring Steps section?" → `n`

Capture and display the full output.

For non-parametrized: extract the new work item ID from `Created : OCS-XXXX`.

For `--parametrize-all`: extract all created IDs from the
`PARAMETRIZED WORK ITEMS SUMMARY` block. Each line has the format
`[N] OCS-XXXX — param_str`.

If the script exits non-zero, show the error and stop.

### Step 5: Report Result and Ask What to Update in the Test File (CREATE MODE)

**Note:** For update mode, skip to Step 5U below.

---

**Non-parametrized tests (or single `param=<N>`):**

Print the creation summary, then ask the user what they want applied to the
source file:

```
Created Polarion test case: OCS-XXXX
Title:  <title>
Steps:  <N> test step(s)
Linked: <related_id> (if provided)
URL:    https://polarion.engineering.redhat.com/polarion/redirect/project/OpenShiftContainerStorage/workitem?id=OCS-XXXX

What would you like to update in <file_path>?
  1. Add docstring (Steps section) and @polarion_id decorator
  2. Add docstring only
  3. Add @polarion_id decorator only
  4. Do nothing
```

Wait for the user's response, then apply the chosen option(s):

**Option 1 or 2 — Add / update the docstring Steps section:**
Using the Edit tool, insert or replace the `Steps:` section in the test
function's docstring. If the function has no docstring, create one. Format:
```python
    def test_foo(self, ...):
        """
        <one-line summary derived from the description>.

        Steps:
        1. <step 1 text>
        2. <step 2 text>
        ...
        """
```

**Option 1 or 3 — Add @polarion_id decorator:**
Using the Edit tool:
- Ensure `polarion_id` is in the `from ocs_ci.framework.testlib import (...)`
  block (insert alphabetically if missing).
- For a **non-parametrized** test or `param=<N>`: place `@polarion_id("<NEW_ID>")`
  as the **last** decorator on the test method, just before `def`.
- For a **single param set** (`param=<N>`): place the `polarion_id` inside the
  specific `pytest.param(marks=...)` entry instead.

Example result (non-parametrized):
```python
from ocs_ci.framework.testlib import (
    ManageTest,
    polarion_id,
    tier1,
    ui,
)

    @tier1
    @ui
    @polarion_id("OCS-8010")
    def test_cephfs_subvolume_metrics_section_reachable(self, setup_ui_class):
```

**Option 4 — Do nothing:** skip file edits entirely.

---

**Parametrized tests (`param=all`):**

The script output already contains the full summary. Print the summary from
the script's `PARAMETRIZED WORK ITEMS SUMMARY` block and ask the user:

```
Created <N> parametrized work items:
  [0] OCS-XXXX — mon_timeout=3m, mon_interval=20s
      URL: https://...
  [1] OCS-YYYY — mon_timeout=12m, mon_interval=30s
      URL: https://...

What would you like to update in <file_path>?
  1. Add polarion_id marks to pytest.param() entries
  2. Do nothing
```

**Option 1 — Add polarion_id marks to pytest.param() entries:**
Using the Edit tool, update each `pytest.param(...)` entry in the
`@pytest.mark.parametrize` decorator to include or replace the
`marks=pytest.mark.polarion_id("OCS-XXXX")` keyword.

Example result:
```python
    @pytest.mark.parametrize(
        "mon_timeout, mon_interval",
        [
            pytest.param(
                "3m",
                "20s",
                marks=pytest.mark.polarion_id("OCS-XXXX"),
            ),
            pytest.param(
                "12m",
                "30s",
                marks=pytest.mark.polarion_id("OCS-YYYY"),
            ),
        ],
    )
    def test_patch_and_verify_mon_healthcheck(self, ...):
```

If the argvalues are plain tuples (not `pytest.param()`), wrap them:
- Before: `("3m", "20s"),`
- After:  `pytest.param("3m", "20s", marks=pytest.mark.polarion_id("OCS-XXXX")),`

**Option 2 — Do nothing:** skip file edits entirely.

### Step 4U: Run the Python Script (UPDATE MODE)

Skip this step if mode is `create`.

Determine the steps source and build the script invocation. The update script
is at `$POLARION_UPDATE_SCRIPT_PATH` (derived in Step 0).

**Case A — only `related=` given (no steps):**
```bash
python3 "$POLARION_UPDATE_SCRIPT_PATH" \
    --work-item-id <OCS-ID> \
    --related-work-item <related_id>
```
No stdin pipe needed — the script does not prompt when only linking.

**Case B — `steps-file=<path>` given (no test file):**
```bash
printf 'y\n' | python3 "$POLARION_UPDATE_SCRIPT_PATH" \
    --work-item-id <OCS-ID> \
    --no-generate-steps \
    --test-steps-file <steps_path> \
    [--related-work-item <related_id>]
```

**Case C — `file_path::test_name` given (auto-extracted steps):**
Write the confirmed steps from Step 3U to `/tmp/polarion_steps.yaml` and run:
```bash
printf 'y\n' | python3 "$POLARION_UPDATE_SCRIPT_PATH" \
    --work-item-id <OCS-ID> \
    --test-path <file_path> \
    --test-name <test_name> \
    [--class-name <class_name>] \
    --no-generate-steps \
    --test-steps-file /tmp/polarion_steps.yaml \
    [--related-work-item <related_id>]
```

The `printf 'y\n'` answers the "Post N step(s) to OCS-XXXX?" prompt.

Capture and display the full output.
If the script exits non-zero, show the error and stop.

### Step 5U: Report Result (UPDATE MODE)

Print the update summary. No decorator/docstring offers since the test case
already exists.

```
Updated Polarion test case: OCS-XXXX
Steps:  <N> test step(s) posted (if steps were posted)
Linked: OCS-YYYY (if a link was added)
URL:    https://polarion.engineering.redhat.com/polarion/redirect/project/OpenShiftContainerStorage/workitem?id=OCS-XXXX
```

Then stop.
