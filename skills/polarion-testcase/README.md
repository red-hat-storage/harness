# polarion-testcase

A Claude Code skill for creating and updating Polarion test cases from
Python test functions or deployment conf files.

## What it does

### Create mode
- Extracts test steps and expected results from a test function
- Creates a Polarion test case via the REST API with all fields populated
- Adds the `@polarion_id` decorator back to the source file
- Supports parametrized tests, conf files, and pre-written steps files
  (YAML or plain text)

### Update mode
- Posts test steps to an existing Polarion test case
- Adds `relates_to` links between work items
- Supports the same step sources: test file extraction, YAML, or plain text

## Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed
- Python 3.10+ (no external dependencies beyond stdlib)
- A Polarion API token, set via one of:
  - `POLARION_TOKEN` env var
  - `~/.polarion-token` file (plain text, just the token)

## Configuration

The Polarion API URL and project are controlled by environment variables:

| Variable | Default | Description |
|---|---|---|
| `POLARION_BASE_URL` | `https://polarion.engineering.redhat.com/polarion/rest/v1` | Polarion REST API base URL |
| `POLARION_PROJECT` | `OpenShiftContainerStorage` | Polarion project ID |
| `POLARION_TOKEN` | *(none)* | Bearer token for API auth |

Set these in your shell profile or in Claude Code's `settings.json` env
block.

## Install

Clone this repo and run:

```bash
git clone <repo-url> polarion-testcase
cd polarion-testcase
./install.sh --project /path/to/python-project --token <your-polarion-token>
```

This creates:
- A symlink for the skill definition (`git pull` updates it automatically)
- `~/.polarion-testcase.conf` with the script and project paths
- `~/.polarion-token` with your API token (mode 600)

The `--project` flag is required — it tells the skill where your Python
test project lives. The `--token` flag is optional if you prefer to set
`POLARION_TOKEN` in your shell profile instead.

By default the skill is installed to `~/.claude/skills/polarion-testcase/`.
To use a different Claude skills directory (e.g. a project-scoped one):

```bash
./install.sh --project /path/to/python-project --skills-dir /path/to/skills
```

## Verify Installation

After installation, verify your Polarion API connection:

```bash
cd polarion-testcase
python3 verify_connection.py
```

This script tests:
- ✓ Token configuration (checks `~/.polarion-token` or `POLARION_TOKEN` env var)
- ✓ API connectivity (confirms the Polarion endpoint is reachable)
- ✓ Project access (verifies you can access the configured project)
- ✓ Permissions (tests read access to work items)

**Example output (success):**
```
======================================================================
Polarion API Connection Verification
======================================================================
Checking token configuration...
  ✓ Token found: /home/user/.polarion-token
    Length: 562 characters

Checking API connection...
  Endpoint: https://polarion.engineering.redhat.com/polarion/rest/v1
  ✓ Connected to Polarion API

Checking project access...
  Project: OpenShiftContainerStorage
  ✓ Project accessible: OpenShiftContainerStorage
    ID: OpenShiftContainerStorage

Checking permissions...
  ✓ Read permission: OK
  ℹ Write permission: Not tested (requires actual work item creation)
    Ensure your token has 'read/write' scope

======================================================================
Connection test: PASSED ✓
======================================================================

You're ready to create Polarion test cases!
Try: /polarion-testcase help
```

**Common errors and fixes:**

| Error | Cause | Fix |
|-------|-------|-----|
| `Token file not found` | No token configured | Create `~/.polarion-token` with your API token |
| `Authentication failed (HTTP 401)` | Invalid or expired token | Generate a new token at Polarion → Profile → Personal Access Tokens |
| `Access forbidden (HTTP 403)` | Insufficient permissions | Ensure your token has `read/write` scope |
| `Connection failed` | Network issue | Check VPN connection or network connectivity |
| `Project not found (HTTP 404)` | Wrong project ID | Set `POLARION_PROJECT` env var to the correct project |

## Usage

Inside Claude Code, invoke with `/polarion-testcase`:

### Create mode

```
# Basic — test file with optional related work item:
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature related=OCS-7430

# Test inside a class:
/polarion-testcase create tests/functional/ui/test_foo.py::TestMyClass::test_my_feature related=OCS-7430

# Search by test name (if unique across tests/):
/polarion-testcase create test_my_feature

# Conf file (deployment YAML):
/polarion-testcase create conf/deployment/vsphere/my_config.yaml

# With overrides:
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature importance=critical
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature setup="Deploy ODF cluster." teardown="Delete all created resources."

# Pre-written steps file (YAML or plain text):
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature steps-file=/tmp/my_steps.yaml
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature steps-file=/tmp/my_steps.txt

# Skip steps or derive from code:
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature no-steps
/polarion-testcase create tests/functional/ui/test_foo.py::test_my_feature steps-from-code

# Parametrized tests:
/polarion-testcase create tests/functional/z_cluster/test_foo.py::test_bar param=all
/polarion-testcase create tests/functional/z_cluster/test_foo.py::test_bar param=0
```

### Update mode

```
# Add a related link only:
/polarion-testcase update OCS-8221 related=OCS-7430

# Post steps from a test function:
/polarion-testcase update OCS-8221 tests/functional/ui/test_foo.py::test_my_feature

# Post steps from a class method with a link:
/polarion-testcase update OCS-8221 tests/functional/ui/test_foo.py::TestMyClass::test_my_feature related=OCS-7430

# Post steps from a pre-written file:
/polarion-testcase update OCS-8221 steps-file=/tmp/my_steps.yaml
```

### Key options

| Option | Description |
|---|---|
| `related=OCS-XXXX` | Link to a related Polarion work item (create or update) |
| `importance=critical` | Set case importance (default: high) |
| `automation=notautomated` | Set automation status (default: automated) |
| `title="..."` | Override auto-generated title |
| `description="..."` | Override description from docstring |
| `setup="..."` | Override auto-extracted setup text |
| `teardown="..."` | Override auto-extracted teardown text |
| `steps-file=/tmp/steps.yaml` | Use pre-written steps (YAML) |
| `steps-file=/tmp/steps.txt` | Use pre-written steps (plain text) |
| `no-steps` | Create without steps |
| `steps-from-code` | Derive steps from code, ignoring docstring |
| `param=all` | Create work items for all parametrize sets |
| `param=<N>` | Create work item for one parametrize set |

Run `/polarion-testcase` with no arguments for full help.

## Important Notes

### What the skill can do:
- ✓ **Create** new Polarion test cases
- ✓ **Update** existing test cases that have no steps (add steps to empty test cases)
- ✓ **Add related links** to existing test cases
- ✓ Add `@polarion_id` decorators to test files
- ✓ Handle parametrized tests (create multiple work items)

### What the skill cannot do:
- ✗ **Modify** existing test case steps (can only add to empty test cases)
- ✗ **Replace** or **delete** existing steps
- ✗ **Modify** other fields (title, description, importance) after creation
- ✗ **Delete** Polarion test cases
- ✗ **Move** test cases between projects
- ✗ **Change** work item status (draft → approved)

**Why?** The Polarion REST API requires different permissions and workflows for modifying/deleting work items. The skill uses the POST steps endpoint which only works on empty test cases.

**Update mode use cases:**
- ✓ Add steps to a test case that was created without steps (empty)
- ✓ Add `relates_to` links between work items
- ✗ Modify steps that already exist in Polarion

**To modify existing steps:** Use the Polarion web UI directly.

## Files

| File | Purpose |
|---|---|
| `SKILL.md` | Skill definition (symlinked to `~/.claude/skills/polarion-testcase/`) |
| `create_polarion_tc.py` | Create mode entry point |
| `update_polarion_tc.py` | Update mode entry point |
| `polarion_tc_helpers.py` | Shared helpers (API, AST, steps, display) |
| `constants.py` | Constants, prompt templates, and validation sets |
| `verify_connection.py` | Connection verification script (tests token, API, permissions) |
| `install.sh` | Skill symlink installer |
| `examples/` | Sample steps files (YAML and plain text) |
| `tests/` | Tests for the scripts |
