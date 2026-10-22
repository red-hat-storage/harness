"""Shared helpers for polarion-testcase create and update scripts."""

import ast
import copy
import difflib
import html as html_mod
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

from constants import (
    ACRONYMS,
    CONF_FILE,
    CONF_TITLE_PROMPT,
    DEFAULT_EXPECTED,
    DOCSTRING_PROMPT,
    EXTRACT_PROMPT,
    MARKS_MODULE,
    MAX_LINE,
    POLARION_BASE,
    POLARION_REDIRECT,
    PROJECT,
    TESTLIB_MODULE,
    TOKEN_FILE,
)

# ── Claude CLI ───────────────────────────────────────────────────────────────

_CLAUDE_CLI = shutil.which("claude")


def claude_available() -> bool:
    """Return True if the claude CLI is available in PATH."""
    return _CLAUDE_CLI is not None


def call_claude(prompt: str, timeout: int = 120) -> str:
    """Call the claude CLI in print mode and return its stdout."""
    if not _CLAUDE_CLI:
        raise RuntimeError("claude CLI not found in PATH")
    print("  [calling Claude…]")
    result = subprocess.run(
        [_CLAUDE_CLI, "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude exited {result.returncode}:\n{result.stderr}"
        )
    return result.stdout.strip()


def parse_json_from_output(text: str) -> dict:
    """Strip optional markdown fences and parse JSON."""
    text = re.sub(
        r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.M
    )
    text = re.sub(r"\n?```\s*$", "", text, flags=re.M)
    return json.loads(text.strip())


def show_diff(label: str, original: str, updated: str) -> None:
    """Print a unified diff between two strings."""
    diff = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"{label} (before)",
            tofile=f"{label} (after)",
        )
    )
    if not diff:
        print("  (no changes)")
        return
    print(f"\n--- diff: {label} ---")
    for line in diff:
        print(line, end="")
    print()


# ── Token & config ───────────────────────────────────────────────────────────


def get_token() -> str:
    """Retrieve the Polarion bearer token from env or file."""
    token = os.environ.get("POLARION_TOKEN")
    if token:
        return token
    if os.path.exists(TOKEN_FILE):
        token = Path(TOKEN_FILE).read_text().strip()
        if token:
            return token
    sys.exit(
        "ERROR: No Polarion token found.\n"
        "Set POLARION_TOKEN env var or put the token in "
        f"{TOKEN_FILE}"
    )


def get_project_dir() -> str | None:
    """Read POLARION_PROJECT_DIR from ~/.polarion-testcase.conf."""
    if not os.path.exists(CONF_FILE):
        return None
    for line in Path(CONF_FILE).read_text().splitlines():
        if line.startswith("POLARION_PROJECT_DIR="):
            return line.split("=", 1)[1].strip('"')
    return None


# ── Python AST helpers ───────────────────────────────────────────────────────


def get_node_source(source: str, node) -> str:
    """Extract the exact source lines for an AST node."""
    lines = source.splitlines(keepends=True)
    return "".join(lines[node.lineno - 1 : node.end_lineno])


def find_function_node(
    source: str, name: str, class_name: str | None = None
):
    """Find a FunctionDef AST node by name, optionally scoped to a class."""
    tree = ast.parse(source)
    if class_name:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == class_name
            ):
                for child in ast.walk(node):
                    if isinstance(
                        child,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    ) and child.name == name:
                        return child
        return None
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if node.name == name:
                return node
    return None


def find_class_for_function(
    source: str, fn_name: str, class_name: str | None = None
):
    """Find the ClassDef that contains a function."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if class_name and node.name != class_name:
                continue
            for child in ast.walk(node):
                if isinstance(
                    child,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    if child.name == fn_name:
                        return node
    return None


def get_docstring(node) -> str:
    """Extract the docstring from a function or class node."""
    if (
        node
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        return textwrap.dedent(
            node.body[0].value.value
        ).strip()
    return ""


def find_method_in_class(cls_node, method_name: str):
    """Find a method by name within a class node."""
    for node in cls_node.body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if node.name == method_name:
                return node
    return None


def find_autouse_fixtures(cls_node) -> list:
    """Return methods decorated with @pytest.fixture(autouse=True)."""
    fixtures = []
    for node in cls_node.body:
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        for dec in node.decorator_list:
            is_autouse = False
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "fixture"
            ):
                for kw in dec.keywords:
                    if kw.arg == "autouse" and isinstance(
                        kw.value, ast.Constant
                    ) and kw.value.value is True:
                        is_autouse = True
            elif (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Name)
                and dec.func.id == "fixture"
            ):
                for kw in dec.keywords:
                    if kw.arg == "autouse" and isinstance(
                        kw.value, ast.Constant
                    ) and kw.value.value is True:
                        is_autouse = True
            if is_autouse:
                fixtures.append(node)
                break
    return fixtures


def get_class_context_source(
    source: str,
    test_name: str,
    class_name: str | None = None,
) -> str:
    """Return autouse fixtures + test function source from a class."""
    cls_node = find_class_for_function(
        source, test_name, class_name
    )
    fn_node = find_function_node(
        source, test_name, class_name
    )
    if not cls_node or not fn_node:
        return source

    parts = []
    class_lines = source.splitlines(keepends=True)
    parts.append(class_lines[cls_node.lineno - 1])

    for fx in find_autouse_fixtures(cls_node):
        parts.append(get_node_source(source, fx))

    for name in (
        "setup_method",
        "teardown_method",
        "setup",
        "teardown",
    ):
        m = find_method_in_class(cls_node, name)
        if m:
            parts.append(get_node_source(source, m))

    parts.append(get_node_source(source, fn_node))
    return "\n\n".join(parts)


# ── Parametrize extraction ───────────────────────────────────────────────────


def _resolve_module_constant(
    module_alias, attr_name, source
):
    """Resolve a module-level constant to its literal value."""
    tree = ast.parse(source)
    module_path = None
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.ImportFrom) and stmt.module:
            for alias in stmt.names:
                imported_name = alias.asname or alias.name
                if imported_name == module_alias:
                    module_path = (
                        f"{stmt.module}.{alias.name}"
                    )
                    break
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                imported_name = alias.asname or alias.name
                if imported_name == module_alias:
                    module_path = alias.name
                    break
        if module_path:
            break

    if not module_path:
        return None

    rel = module_path.replace(".", "/")
    candidates = [Path(rel + ".py"), Path(rel) / "__init__.py"]

    project_dir = get_project_dir()
    if project_dir:
        candidates = (
            [Path(project_dir) / c for c in candidates]
            + candidates
        )

    file_path = None
    for c in candidates:
        if c.is_file():
            file_path = c
            break
    if file_path is None:
        return None

    try:
        mod_source = file_path.read_text(encoding="utf-8")
        mod_tree = ast.parse(mod_source)
    except (OSError, SyntaxError):
        return None

    for stmt in ast.iter_child_nodes(mod_tree):
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == attr_name
                    and isinstance(stmt.value, ast.Constant)
                ):
                    return stmt.value.value
    return None


def _get_constant_value(node, source=None):
    """Get a Python value from an AST node."""
    if isinstance(node, ast.Constant):
        return node.value
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        pass

    if (
        source
        and isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
    ):
        resolved = _resolve_module_constant(
            node.value.id, node.attr, source
        )
        if resolved is not None:
            return resolved

    try:
        return ast.unparse(node)
    except (AttributeError, TypeError):
        return "<expr>"


def _extract_polarion_id_from_marks(marks_node):
    """Extract polarion_id string from a marks= keyword."""
    nodes = []
    if isinstance(marks_node, (ast.List, ast.Tuple)):
        nodes = marks_node.elts
    else:
        nodes = [marks_node]

    for node in nodes:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "polarion_id"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            return node.args[0].value
    return None


def extract_parametrize_info(
    source, test_name, class_name=None
):
    """Extract @pytest.mark.parametrize info from a test function.

    Returns None if not parametrized, or a list of dicts with
    index, params, and existing_polarion_id.
    """
    fn_node = find_function_node(
        source, test_name, class_name
    )
    if not fn_node:
        return None

    for dec in _parametrize_decorators(fn_node):
        kw_map = {
            kw.arg: kw.value for kw in dec.keywords
        }
        argnames_node = (
            dec.args[0]
            if len(dec.args) >= 1
            else kw_map.get("argnames")
        )
        argvalues_node = _argvalues(dec)
        if argnames_node is None or argvalues_node is None:
            continue

        if isinstance(
            argnames_node, ast.Constant
        ) and isinstance(argnames_node.value, str):
            argnames = [
                n.strip()
                for n in argnames_node.value.split(",")
            ]
        elif isinstance(
            argnames_node, (ast.List, ast.Tuple)
        ):
            argnames = [
                elt.value
                for elt in argnames_node.elts
                if isinstance(elt, ast.Constant)
            ]
        else:
            continue

        if not isinstance(
            argvalues_node, (ast.List, ast.Tuple)
        ):
            continue

        param_sets = []
        for idx, item in enumerate(argvalues_node.elts):
            params = {}
            existing_id = None

            if isinstance(item, ast.Call):
                values = [
                    _get_constant_value(a, source)
                    for a in item.args
                ]
                for kw in item.keywords:
                    if kw.arg == "marks":
                        existing_id = (
                            _extract_polarion_id_from_marks(
                                kw.value
                            )
                        )
            elif isinstance(item, (ast.Tuple, ast.List)):
                values = [
                    _get_constant_value(e, source)
                    for e in item.elts
                ]
            else:
                values = [
                    _get_constant_value(item, source)
                ]

            for i, name in enumerate(argnames):
                params[name] = (
                    values[i]
                    if i < len(values)
                    else "<missing>"
                )

            param_sets.append(
                {
                    "index": idx,
                    "params": params,
                    "existing_polarion_id": existing_id,
                }
            )

        return param_sets

    return None


# ── Docstring parsing ────────────────────────────────────────────────────────


def extract_section(docstring: str, section: str) -> str:
    """Extract a named section from a docstring."""
    lines = docstring.splitlines()
    in_section = False
    collected = []
    section_re = re.compile(
        rf"^\s*{re.escape(section)}\s*:\s*$", re.IGNORECASE
    )
    new_section_re = re.compile(r"^\s*[A-Za-z][\w ]*\s*:\s*$")
    for line in lines:
        if section_re.match(line):
            in_section = True
            continue
        if in_section:
            if new_section_re.match(line) and line.strip():
                break
            collected.append(line)
    return "\n".join(collected).strip()


def parse_numbered_steps(text: str) -> list:
    """Parse numbered step lines into a list of step dicts."""
    steps = []
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if m:
            if current:
                steps.append(current)
            step_text = m.group(2)
            exp_m = re.search(r"\s+-\s+(.+)$", step_text)
            if exp_m:
                current = {
                    "step": step_text[
                        : exp_m.start()
                    ].strip(),
                    "expected": exp_m.group(1).strip(),
                }
            else:
                current = {
                    "step": step_text,
                    "expected": DEFAULT_EXPECTED,
                }
        elif stripped and current:
            if re.match(
                r"^(expected|result)\s*:",
                stripped,
                re.IGNORECASE,
            ):
                current["expected"] = re.sub(
                    r"^[^:]+:\s*", "", stripped
                )
            else:
                current["step"] += " " + stripped
    if current:
        steps.append(current)
    return steps


# ── Step extraction ──────────────────────────────────────────────────────────


def regex_extract_steps(
    source: str,
    test_name: str,
    class_name: str | None = None,
) -> tuple:
    """Fast regex-based step extraction from docstrings."""
    fn_node = find_function_node(
        source, test_name, class_name
    )
    cls_node = find_class_for_function(
        source, test_name, class_name
    )

    fn_doc = get_docstring(fn_node) if fn_node else ""
    steps_text = extract_section(
        fn_doc, "Steps"
    ) or extract_section(fn_doc, "Test Steps")
    test_steps = parse_numbered_steps(steps_text)

    setup_steps: list = []
    teardown_steps: list = []

    if cls_node:
        for name in ("setup_method", "init_sanity", "setup"):
            m = find_method_in_class(cls_node, name)
            if m:
                doc = get_docstring(m)
                text = extract_section(
                    doc, "Setup"
                ) or extract_section(doc, "Steps")
                if text:
                    setup_steps = parse_numbered_steps(text)
                elif doc:
                    summary = doc.split("\n\n")[0].strip()
                    if summary:
                        setup_steps = [
                            {
                                "step": summary,
                                "expected": (
                                    "Setup completes"
                                    " successfully."
                                ),
                            }
                        ]
                break

        for name in ("teardown_method", "teardown"):
            m = find_method_in_class(cls_node, name)
            if m:
                doc = get_docstring(m)
                text = extract_section(
                    doc, "Teardown"
                ) or extract_section(doc, "Steps")
                if text:
                    teardown_steps = parse_numbered_steps(
                        text
                    )
                elif doc:
                    summary = doc.split("\n\n")[0].strip()
                    if summary:
                        teardown_steps = [
                            {
                                "step": summary,
                                "expected": (
                                    "Teardown completes"
                                    " successfully."
                                ),
                            }
                        ]
                break

        if not setup_steps and not teardown_steps:
            autouse = find_autouse_fixtures(cls_node)
            if autouse:
                return test_steps, [], []

    return test_steps, setup_steps, teardown_steps


def ai_extract_steps(
    source: str,
    test_name: str,
    class_name: str | None = None,
) -> tuple:
    """Use Claude to extract steps from the test class code."""
    context = get_class_context_source(
        source, test_name, class_name
    )
    prompt = EXTRACT_PROMPT.format(
        test_name=test_name, code=context
    )
    try:
        output = call_claude(prompt)
        data = parse_json_from_output(output)
        return (
            data.get("test_steps", []),
            data.get("setup_steps", []),
            data.get("teardown_steps", []),
        )
    except Exception as e:
        print(f"  WARNING: AI extraction failed: {e}")
        return [], [], []


def auto_extract_steps(
    source: str,
    test_name: str,
    offer_ai: bool = True,
    class_name: str | None = None,
    steps_from_code: bool = False,
) -> tuple:
    """Try regex first, then offer AI extraction if needed."""
    if steps_from_code:
        print(
            "\n  NOTE: --steps-from-code set;"
            " ignoring docstring Steps section."
        )
        if not claude_available():
            print(
                "  ERROR: claude CLI not available"
                " — cannot derive steps from code."
            )
            return [], [], []
        return ai_extract_steps(
            source, test_name, class_name
        )

    (
        test_steps,
        setup_steps,
        teardown_steps,
    ) = regex_extract_steps(
        source, test_name, class_name
    )

    cls_node = find_class_for_function(
        source, test_name, class_name
    )
    has_autouse = bool(
        cls_node and find_autouse_fixtures(cls_node)
    )

    regex_incomplete = has_autouse and (
        not setup_steps or not teardown_steps
    )
    steps_missing = not test_steps

    if (regex_incomplete or steps_missing) and offer_ai:
        reasons = []
        if steps_missing:
            reasons.append(
                "no test steps found in docstring"
            )
        if regex_incomplete:
            reasons.append(
                "autouse fixture(s) found but content"
                " requires AI to interpret"
            )
        print(f"\n  NOTE: {'; '.join(reasons)}.")
        if not claude_available():
            print(
                "  (claude CLI not available"
                " — skipping AI extraction)"
            )
            return test_steps, setup_steps, teardown_steps
        if ask(
            "Use AI to extract steps from the test code?"
        ):
            ai_test, ai_setup, ai_teardown = (
                ai_extract_steps(
                    source, test_name, class_name
                )
            )
            if not test_steps and ai_test:
                test_steps = ai_test
            if not setup_steps and ai_setup:
                setup_steps = ai_setup
            if not teardown_steps and ai_teardown:
                teardown_steps = ai_teardown

    return test_steps, setup_steps, teardown_steps


# ── Steps file parsing ───────────────────────────────────────────────────────

_RE_SECTION = re.compile(
    r"^\s*(setup|steps|teardown)\s*:\s*$", re.IGNORECASE
)
_RE_STEP = re.compile(r"^\s*(\d+)\.\s+(.+)$")
_RE_EXPECTED = re.compile(
    r"^\s*expected\s*:\s*(.+)$", re.IGNORECASE
)


def parse_steps_txt(text):
    """Parse a plain-text steps file.

    Returns (ok, msg, test_steps, setup_steps, teardown_steps).
    """
    sections = {
        "steps": [],
        "setup": [],
        "teardown": [],
    }
    current = "steps"
    last_step = None
    last_field = "step"

    for line in text.splitlines():
        m_sec = _RE_SECTION.match(line)
        if m_sec:
            current = m_sec.group(1).lower()
            last_step = None
            last_field = "step"
            continue

        m_exp = _RE_EXPECTED.match(line)
        if m_exp:
            if last_step is not None:
                last_step["expected"] = (
                    m_exp.group(1).strip()
                )
                last_field = "expected"
            continue

        m_step = _RE_STEP.match(line)
        if m_step:
            last_step = {
                "step": m_step.group(2).strip(),
                "expected": DEFAULT_EXPECTED,
            }
            sections[current].append(last_step)
            last_field = "step"
            continue

        stripped = line.strip()
        if stripped and last_step is not None:
            last_step[last_field] += " " + stripped

    total = sum(len(v) for v in sections.values())
    if total == 0:
        return (
            False,
            "No numbered steps found in text file.",
            [],
            [],
            [],
        )

    return (
        True,
        (
            f"OK — {len(sections['steps'])} step(s), "
            f"{len(sections['setup'])} setup, "
            f"{len(sections['teardown'])} teardown"
        ),
        sections["steps"],
        sections["setup"],
        sections["teardown"],
    )


def _load_yaml_steps(path):
    """Load steps from a YAML file.

    Returns (ok, msg, test_steps, setup_steps, teardown_steps).
    """
    try:
        import yaml
    except ImportError:
        return (
            False,
            "pyyaml not installed. Run: pip install pyyaml",
            [],
            [],
            [],
        )

    try:
        data = yaml.safe_load(path.read_text())
    except Exception as e:
        return False, f"Cannot parse YAML: {e}", [], [], []

    if not isinstance(data, dict):
        return (
            False,
            "Steps file must be a YAML mapping with "
            "'steps' key.",
            [],
            [],
            [],
        )

    if "steps" not in data:
        return (
            False,
            "Steps file missing required top-level "
            "'steps' key.",
            [],
            [],
            [],
        )

    def normalize(entries, section_name):
        result = []
        for i, e in enumerate(entries or [], 1):
            if not isinstance(e, dict):
                return (
                    None,
                    f"{section_name}[{i}] must be"
                    " a mapping.",
                )
            if "step" not in e:
                return (
                    None,
                    f"{section_name}[{i}] missing"
                    " required 'step' field.",
                )
            result.append(
                {
                    "step": str(e["step"]),
                    "expected": str(
                        e.get(
                            "expected",
                            DEFAULT_EXPECTED,
                        )
                    ),
                }
            )
        return result, ""

    test_steps, err = normalize(
        data.get("steps", []), "steps"
    )
    if err:
        return False, err, [], [], []
    setup_steps, err = normalize(
        data.get("setup", []), "setup"
    )
    if err:
        return False, err, [], [], []
    teardown_steps, err = normalize(
        data.get("teardown", []), "teardown"
    )
    if err:
        return False, err, [], [], []

    return (
        True,
        (
            f"OK — {len(test_steps)} step(s), "
            f"{len(setup_steps or [])} setup, "
            f"{len(teardown_steps or [])} teardown"
        ),
        test_steps,
        setup_steps or [],
        teardown_steps or [],
    )


def load_steps_file(path: Path) -> tuple:
    """Load a steps file (YAML or plain text).

    Returns (ok, msg, test_steps, setup_steps, teardown_steps).
    """
    if not path.exists():
        return (
            False,
            f"Steps file not found: {path}",
            [],
            [],
            [],
        )

    if path.suffix.lower() == ".txt":
        return parse_steps_txt(path.read_text())

    return _load_yaml_steps(path)


# ── Polarion API ─────────────────────────────────────────────────────────────


def api_call(method: str, url: str, token: str, body=None):
    """Make an authenticated Polarion REST API call."""
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}


def create_work_item(token: str, attrs: dict) -> tuple:
    """Create a Polarion work item. Returns (wi_id, error)."""
    url = f"{POLARION_BASE}/projects/{PROJECT}/workitems"
    body = {
        "data": [
            {"type": "workitems", "attributes": attrs}
        ]
    }
    status, resp = api_call("POST", url, token, body)
    if status in (200, 201):
        wi_id = resp["data"][0]["id"].split("/")[-1]
        return wi_id, ""
    return "", json.dumps(resp, indent=2)


def post_test_steps(
    token: str, wi_id: str, steps: list
) -> str:
    """Post test steps to an existing work item. Returns error string."""
    if not steps:
        return ""
    url = (
        f"{POLARION_BASE}/projects/{PROJECT}"
        f"/workitems/{wi_id}/teststeps"
    )
    data = [
        {
            "type": "teststeps",
            "attributes": {
                "keys": ["step", "expectedResult"],
                "values": [
                    {
                        "type": "text/html",
                        "value": html_mod.escape(
                            s["step"]
                        ),
                    },
                    {
                        "type": "text/html",
                        "value": html_mod.escape(
                            s["expected"]
                        ),
                    },
                ],
            },
        }
        for s in steps
    ]
    status, resp = api_call(
        "POST", url, token, {"data": data}
    )
    if status in (200, 201):
        return ""
    return json.dumps(resp, indent=2)


def link_work_item(
    token: str, wi_id: str, related_id: str
) -> str:
    """Link two Polarion work items. Returns error string."""
    url = (
        f"{POLARION_BASE}/projects/{PROJECT}"
        f"/workitems/{wi_id}/linkedworkitems"
    )
    body = {
        "data": [
            {
                "type": "linkedworkitems",
                "attributes": {"role": "relates_to"},
                "relationships": {
                    "workItem": {
                        "data": {
                            "type": "workitems",
                            "id": (
                                f"{PROJECT}/"
                                f"{related_id}"
                            ),
                        }
                    }
                },
            }
        ]
    }
    status, resp = api_call("POST", url, token, body)
    if status in (200, 201):
        return ""
    return json.dumps(resp, indent=2)


def create_single_work_item(
    token, attrs, test_steps, related_work_item=None
):
    """Create one work item, post steps, and optionally link.

    Returns (wi_id, error_message).
    """
    wi_id, err = create_work_item(token, attrs)
    if err:
        return "", err

    if test_steps:
        err = post_test_steps(token, wi_id, test_steps)
        if err:
            print(
                f"  WARNING: Failed to post steps"
                f" for {wi_id}:\n{err}"
            )

    if related_work_item:
        err = link_work_item(
            token, wi_id, related_work_item
        )
        if err:
            print(
                f"  WARNING: Failed to link {wi_id}"
                f" to {related_work_item}:\n{err}"
            )

    return wi_id, ""


# ── Param substitution ───────────────────────────────────────────────────────


def substitute_params(text, params):
    """Replace {argname} placeholders with param values."""
    for k, v in params.items():
        text = text.replace(f"{{{k}}}", str(v))
    return text


def substitute_params_in_steps(test_steps, params):
    """Deep-copy steps and substitute {argname} placeholders."""
    steps = copy.deepcopy(test_steps)
    for step in steps:
        step["step"] = substitute_params(
            step["step"], params
        )
        step["expected"] = substitute_params(
            step["expected"], params
        )
    return steps


def substitute_params_in_attrs(attrs, params):
    """Substitute {argname} placeholders in description."""
    attrs = dict(attrs)
    desc = attrs.get("description")
    if isinstance(desc, dict) and "value" in desc:
        attrs["description"] = dict(desc)
        attrs["description"]["value"] = substitute_params(
            desc["value"], params
        )
    elif isinstance(desc, str):
        attrs["description"] = substitute_params(
            desc, params
        )
    return attrs


def create_parametrized_work_items(
    token,
    base_attrs,
    test_steps,
    param_sets,
    base_test_name,
    related_work_item=None,
):
    """Create one Polarion work item per parametrize set.

    Returns list of result dicts with index, wi_id, params, error.
    """
    results = []
    base_title = base_attrs.get("title", "")
    total = len(param_sets)

    for ps in param_sets:
        idx = ps["index"]
        params = ps["params"]

        param_str = ", ".join(
            f"{k}={v}" for k, v in params.items()
        )
        param_id = "-".join(
            str(v) for v in params.values()
        )

        attrs = substitute_params_in_attrs(
            base_attrs, params
        )
        attrs["title"] = f"{base_title} ({param_str})"
        attrs["automationscript"] = (
            f"{base_test_name}[{param_id}]"
        )

        ps_steps = substitute_params_in_steps(
            test_steps, params
        )

        print(
            f"\n  [{idx + 1}/{total}]"
            f" Creating: {attrs['title']}"
        )

        wi_id, err = create_single_work_item(
            token, attrs, ps_steps, related_work_item
        )

        if wi_id:
            print(f"  Created: {wi_id}")
            if ps_steps:
                print(
                    f"  Posted {len(ps_steps)}"
                    " test step(s)"
                )
        else:
            print(f"  FAILED: {err}")

        results.append(
            {
                "index": idx,
                "params": params,
                "wi_id": wi_id,
                "error": err,
            }
        )

    return results


# ── File editing ─────────────────────────────────────────────────────────────


def _defined_names(tree: ast.AST) -> set:
    """Return every function and class name defined in a parsed tree."""
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        )
    }


def validate_edit(
    source: str, updated: str, check_size: bool = True
) -> str:
    """Return an error string if an edited file looks unsafe to write.

    Guards against a truncated or summarised rewrite silently destroying
    the file. Returns "" when the edit is safe.
    """
    if not updated.strip():
        return "the new content is empty"
    if updated.lstrip().startswith("```"):
        return "the new content is wrapped in markdown fences"
    try:
        new_tree = ast.parse(updated)
        # ast.parse alone accepts things the compiler rejects, such as
        # a repeated keyword argument, so compile it too.
        compile(updated, "<edit>", "exec")
    except SyntaxError as e:
        return f"the new content is not valid Python ({e})"

    dropped = _defined_names(ast.parse(source)) - _defined_names(new_tree)
    if dropped:
        return (
            "the new content is missing "
            f"{len(dropped)} definition(s): {', '.join(sorted(dropped))}"
        )
    # Only meaningful when the whole file was rewritten. A splice is
    # confined to one node, so shrinking there is a legitimate edit.
    if check_size and len(updated) < len(source) * 0.9:
        shrink = 100 - int(len(updated) / len(source) * 100)
        return f"the new content is {shrink}% smaller than the original"
    return ""


def apply_edit(
    file_path: Path,
    source: str,
    updated: str,
    confirm: bool = True,
    check_size: bool = True,
) -> bool:
    """Validate, show, confirm and write an edited file."""
    if updated == source:
        print("  No changes needed.")
        return False

    problem = validate_edit(source, updated, check_size=check_size)
    if problem:
        print(f"  REFUSING to write {file_path.name}: {problem}.")
        print("  The file has been left untouched.")
        return False

    show_diff(file_path.name, source, updated)
    if confirm and not ask("Apply this change?"):
        return False

    file_path.write_text(updated)
    return True


def _load_target(file_path: Path, test_name: str, class_name: str = None):
    """Read a file and locate a test function.

    Returns (source, function node), or (None, None) after reporting
    why the edit cannot proceed.
    """
    source = file_path.read_text()
    try:
        ast.parse(source)
    except SyntaxError as e:
        print(f"  Cannot parse {file_path.name}: {e}")
        return None, None

    func = find_function_node(source, test_name, class_name)
    if func is None:
        print(f"  Function {test_name} not found in {file_path.name}.")
        return None, None
    return source, func


def _decorator_name(node: ast.AST) -> str:
    """Return the dotted name of a decorator expression."""
    target = node.func if isinstance(node, ast.Call) else node
    parts = []
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    return ".".join(reversed(parts))


def _existing_polarion_ids(func: ast.AST) -> list:
    """Return the IDs of any polarion_id decorators already present.

    Matches on the last dotted segment so that both the bare
    `@polarion_id(...)` and the `@pytest.mark.polarion_id(...)` form
    are recognised.
    """
    ids = []
    for dec in func.decorator_list:
        if _decorator_name(dec).split(".")[-1] != "polarion_id":
            continue
        ids += [
            arg.value
            for arg in getattr(dec, "args", [])
            if isinstance(arg, ast.Constant)
        ]
    return ids


def _imports_polarion_id(tree: ast.AST) -> bool:
    """Return True if polarion_id is already imported anywhere."""
    return any(
        isinstance(node, ast.ImportFrom)
        and any(a.name == "polarion_id" for a in node.names)
        for node in ast.walk(tree)
    )


def _import_from(tree: ast.AST, module: str):
    """Return the top-level `from <module> import ...` node, or None."""
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            return node
    return None


def _add_to_import(lines: list, node: ast.ImportFrom) -> None:
    """Add polarion_id to an existing import, in place."""
    start, end = node.lineno - 1, node.end_lineno - 1
    if end > start:
        # Parenthesised import: add one name line before the closing ")".
        indent = re.match(r"\s*", lines[start + 1]).group(0) or "    "
        lines.insert(end, f"{indent}polarion_id,\n")
        return

    names = [a.name for a in node.names] + ["polarion_id"]
    single = f"from {node.module} import {', '.join(names)}\n"
    if len(single.rstrip("\n")) <= MAX_LINE:
        lines[start] = single
        return
    # Too long for one line — switch to the parenthesised form.
    block = [f"from {node.module} import (\n"]
    block += [f"    {n},\n" for n in names]
    block.append(")\n")
    lines[start : start + 1] = block


def _add_import(lines: list, tree: ast.AST) -> None:
    """Make polarion_id importable, reusing the file's own convention."""
    for module in (TESTLIB_MODULE, MARKS_MODULE):
        node = _import_from(tree, module)
        if node is not None:
            _add_to_import(lines, node)
            return

    # No suitable import to extend — add one after the last top-level import.
    last = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node.end_lineno
    lines.insert(last, f"from {MARKS_MODULE} import polarion_id\n")


def _splice(source: str, node: ast.AST, new_text: str) -> str:
    """Replace a node's exact source span with new_text.

    col_offset values from ast are utf-8 byte offsets, so the start and
    end lines are sliced as bytes to stay correct on non-ASCII lines.
    """
    lines = source.splitlines(keepends=True)
    head = lines[node.lineno - 1].encode()[: node.col_offset].decode()
    tail = lines[node.end_lineno - 1].encode()[node.end_col_offset :].decode()
    return "".join(
        lines[: node.lineno - 1]
        + [head + new_text + tail]
        + lines[node.end_lineno :]
    )


def _insert_at(source: str, lineno: int, col: int, text: str) -> str:
    """Insert text at a (1-based line, utf-8 column) position."""
    lines = source.splitlines(keepends=True)
    raw = lines[lineno - 1].encode()
    lines[lineno - 1] = (raw[:col].decode() + text + raw[col:].decode())
    return "".join(lines)


def _segment(source: str, node: ast.AST) -> str:
    """Return the original source text of a node."""
    return ast.get_source_segment(source, node) or ""


def _parametrize_decorators(func: ast.AST) -> list:
    """Return the @pytest.mark.parametrize decorators on a function."""
    found = []
    for dec in func.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        f = dec.func
        if (
            isinstance(f, ast.Attribute)
            and f.attr == "parametrize"
            and isinstance(f.value, ast.Attribute)
            and f.value.attr == "mark"
            and isinstance(f.value.value, ast.Name)
            and f.value.value.id == "pytest"
        ):
            found.append(dec)
    return found


def _argvalues(dec: ast.Call):
    """Return the argvalues node of a parametrize decorator, or None."""
    kw = {k.arg: k.value for k in dec.keywords}
    if len(dec.args) >= 2:
        return dec.args[1]
    return kw.get("argvalues")


def _is_pytest_param(node: ast.AST) -> bool:
    """Return True if node is a pytest.param(...) call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "param"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pytest"
    )


def _marks_keyword(node: ast.AST):
    """Return the marks= keyword node of a pytest.param call, or None."""
    if not isinstance(node, ast.Call):
        return None
    for kw in node.keywords:
        if kw.arg == "marks":
            return kw
    return None


def _polarion_ids_in(node: ast.AST) -> list:
    """Return IDs of any polarion_id marks inside an expression."""
    ids = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else getattr(func, "id", "")
        )
        if name != "polarion_id":
            continue
        ids += [
            a.value for a in sub.args if isinstance(a, ast.Constant)
        ]
    return ids


def _marks_elements(source: str, marks_kw, mark: str) -> list:
    """Return the marks entries, with the new mark appended."""
    if marks_kw is None:
        return [mark]
    value = marks_kw.value
    if isinstance(value, (ast.List, ast.Tuple)):
        return [_segment(source, e) for e in value.elts] + [mark]
    return [_segment(source, value), mark]


def _bare_param_args(source: str, node: ast.AST) -> list:
    """Return the argument parts of an argvalue given without pytest.param.

    A tuple maps to several argnames, so it is unpacked.
    """
    if isinstance(node, ast.Tuple):
        return [_segment(source, e) for e in node.elts]
    return [_segment(source, node)]


def add_param_polarion_id(
    file_path: Path,
    test_name: str,
    param_index: int,
    wi_id: str,
    class_name: str = None,
    confirm: bool = True,
) -> bool:
    """Add a polarion_id mark to one pytest.param of a parametrized test.

    Done with ast, so only the targeted param set is rewritten. Handles
    a param with no marks, an existing single mark, an existing list or
    tuple of marks, and a bare argvalue that is not wrapped in
    pytest.param at all.
    """
    source, func = _load_target(file_path, test_name, class_name)
    if source is None:
        return False

    if _existing_polarion_ids(func):
        print(
            f"  {test_name} already carries a function-level"
            " @polarion_id — refusing to also set a per-param ID."
        )
        return False

    decs = _parametrize_decorators(func)
    if not decs:
        print(f"  {test_name} is not parametrized with pytest.mark.parametrize.")
        return False
    if len(decs) > 1:
        print(
            f"  {test_name} has {len(decs)} parametrize decorators —"
            " a single param index is ambiguous. Edit it by hand."
        )
        return False

    argvalues = _argvalues(decs[0])
    if not isinstance(argvalues, (ast.List, ast.Tuple)):
        print("  argvalues is not a literal list — cannot index it.")
        return False
    if not 0 <= param_index < len(argvalues.elts):
        print(
            f"  param index {param_index} out of range"
            f" (0..{len(argvalues.elts) - 1})."
        )
        return False

    node = argvalues.elts[param_index]
    mark = f'pytest.mark.polarion_id("{wi_id}")'

    present = _polarion_ids_in(node)
    if present:
        print(
            f"  param {param_index} already has polarion_id"
            f"({', '.join(repr(p) for p in present)})"
            " — leaving it alone."
        )
        return False

    marks_kw = _marks_keyword(node)
    elements = _marks_elements(source, marks_kw, mark)

    if not _is_pytest_param(node):
        # A bare value or tuple: wrap it so it can carry marks.
        args = _bare_param_args(source, node)
        updated = _splice(
            source,
            node,
            f"pytest.param({', '.join(args)}, marks={mark})",
        )
    else:
        if marks_kw is None:
            # Insert just after the last argument, which keeps any
            # trailing comma and the existing layout intact.
            tail = (node.args + [k.value for k in node.keywords]) or None
            if tail:
                last = max(
                    tail, key=lambda n: (n.end_lineno, n.end_col_offset)
                )
                updated = _insert_at(
                    source, last.end_lineno, last.end_col_offset,
                    f", marks={mark}",
                )
            else:
                updated = _insert_at(
                    source, node.end_lineno, node.end_col_offset - 1,
                    f"marks={mark}",
                )
        else:
            # Re-render the whole marks value, wrapping it over several
            # lines if the new entry makes it too wide.
            updated = _splice(
                source,
                marks_kw.value,
                "[" + ", ".join(elements) + "]",
            )

    return apply_edit(file_path, source, updated, confirm=confirm)


def add_polarion_decorator(
    file_path: Path, test_name: str, wi_id: str, class_name: str = None
) -> bool:
    """Add @polarion_id("<wi_id>") to a test function.

    This is a purely mechanical edit done with ast, so the rest of the
    file is untouched by construction.
    """
    source, func = _load_target(file_path, test_name, class_name)
    if source is None:
        return False
    tree = ast.parse(source)

    present = _existing_polarion_ids(func)
    if wi_id in present:
        print(f'  {test_name} already has @polarion_id("{wi_id}").')
        return False
    if present:
        print(
            f"  {test_name} already has @polarion_id"
            f"({', '.join(repr(p) for p in present)})"
            " — leaving it alone."
        )
        return False

    lines = source.splitlines(keepends=True)
    # Insert the decorator first: it sits below the imports, so the
    # import line numbers stay valid for the second edit.
    indent = re.match(r"\s*", lines[func.lineno - 1]).group(0)
    lines.insert(func.lineno - 1, f'{indent}@polarion_id("{wi_id}")\n')
    if not _imports_polarion_id(tree):
        _add_import(lines, tree)

    return apply_edit(file_path, source, "".join(lines))


def _docstring_node(func: ast.AST):
    """Return the docstring's Expr node for a function, or None."""
    if not func.body:
        return None
    first = func.body[0]
    if isinstance(first, ast.Expr) and isinstance(
        first.value, ast.Constant
    ) and isinstance(first.value.value, str):
        return first
    return None


def ai_update_docstring(
    file_path: Path, test_name: str, steps: list, class_name: str = None
) -> bool:
    """Rewrite the Steps section of a test's docstring.

    The model is asked for the docstring alone, never the whole file.
    Its answer is spliced into the docstring's exact ast span, so no
    edit can land outside those lines.
    """
    if not claude_available():
        print(
            "  claude CLI not available"
            " — cannot update docstring via AI."
        )
        return False

    source, func = _load_target(file_path, test_name, class_name)
    if source is None:
        return False

    node = _docstring_node(func)
    if node is None:
        print(
            f"  {test_name} has no docstring to update."
            " Add one first, then re-run."
        )
        return False

    steps_text = "\n".join(
        f"{i}. {s['step']}"
        + (
            f"\n   Expected: {s['expected']}"
            if s["expected"] != DEFAULT_EXPECTED
            else ""
        )
        for i, s in enumerate(steps, 1)
    )
    prompt = DOCSTRING_PROMPT.format(
        test_name=test_name,
        steps_text=steps_text,
        docstring=_segment(source, node),
    )
    try:
        new_docstring = call_claude(prompt).strip()
    except Exception as e:
        print(f"  AI call failed: {e}")
        return False

    problem = _check_docstring(new_docstring)
    if problem:
        print(f"  Not updating the docstring: {problem}.")
        return False

    # check_size is off because the edit cannot reach past the
    # docstring node, so a shorter docstring is a valid result.
    return apply_edit(
        file_path,
        source,
        _splice(source, node, new_docstring),
        check_size=False,
    )


def _check_docstring(text: str) -> str:
    """Return a reason the model's docstring is unusable, else ""."""
    if not text:
        return "the model returned nothing"
    if text.startswith("```"):
        return "the model wrapped it in markdown fences"
    if not re.match(r'^[rubfRUBF]*("""|\'\'\')', text):
        return "it does not start with a triple-quote"
    try:
        parsed = ast.parse(text)
    except SyntaxError:
        return "it is not a valid Python string literal"
    body = parsed.body
    if (
        len(body) != 1
        or not isinstance(body[0], ast.Expr)
        or not isinstance(body[0].value, ast.Constant)
        or not isinstance(body[0].value.value, str)
    ):
        return "it is not a single string literal"
    return ""


# ── Display helpers ──────────────────────────────────────────────────────────


def build_title(test_name: str) -> str:
    """Build a human-readable title from a test function name."""
    name = re.sub(r"^test_", "", test_name)
    words = name.split("_")
    parts = ["Test"] + [
        w.upper() if w.lower() in ACRONYMS else w.capitalize()
        for w in words
    ]
    return " ".join(parts)


def to_html(text: str) -> str:
    """Convert plain text to simple HTML paragraphs."""
    if not text:
        return ""
    text = html_mod.escape(text)
    return (
        "<p>"
        + text.replace("\n\n", "</p><p>").replace(
            "\n", " "
        )
        + "</p>"
    )


def html_to_plain(html: str) -> str:
    """Strip HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", html).strip()


def steps_to_html(steps: list) -> str:
    """Convert a step list to HTML. Single step uses <p>, multiple uses <ol>."""
    if len(steps) == 1:
        return f"<p>{html_mod.escape(steps[0]['step'])}</p>"
    items = "".join(
        f"<li>{html_mod.escape(s['step'])}</li>"
        for s in steps
    )
    return f"<ol>{items}</ol>"


def print_preview(
    attrs: dict,
    test_steps: list,
    setup_steps: list,
    teardown_steps: list,
) -> None:
    """Display a formatted preview of the work item to be created."""
    hr = "=" * 70
    print(f"\n{hr}")
    print("POLARION TEST CASE PREVIEW")
    print(hr)
    for key, val in attrs.items():
        if isinstance(val, dict):
            val = html_to_plain(val.get("value", ""))
        print(f"  {key:<20} {val}")

    if test_steps:
        print(
            f"\n  Test steps ({len(test_steps)})"
            " — posted via API:"
        )
        for i, s in enumerate(test_steps, 1):
            print(f"    {i}. {s['step']}")
            if s["expected"] != DEFAULT_EXPECTED:
                print(
                    f"       Expected: {s['expected']}"
                )
    else:
        print(
            "\n  Test steps: (none"
            " — work item will have no steps)"
        )

    if setup_steps:
        print(
            f"\n  Setup ({len(setup_steps)})"
            " — stored as HTML attribute"
            " (NOT API steps):"
        )
        if len(setup_steps) == 1:
            print(f"    {setup_steps[0]['step']}")
        else:
            for i, s in enumerate(setup_steps, 1):
                print(f"    {i}. {s['step']}")

    if teardown_steps:
        print(
            f"\n  Teardown ({len(teardown_steps)})"
            " — stored as HTML attribute"
            " (NOT API steps):"
        )
        if len(teardown_steps) == 1:
            print(f"    {teardown_steps[0]['step']}")
        else:
            for i, s in enumerate(teardown_steps, 1):
                print(f"    {i}. {s['step']}")

    print(hr)


def ask(prompt: str, default: bool = False) -> bool:
    """Prompt the user for a yes/no answer."""
    choices = "[Y/n]" if default else "[y/N]"
    try:
        resp = (
            input(f"{prompt} {choices}: ").strip().lower()
        )
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return resp.startswith("y") if resp else default


# ── Conf file helpers ────────────────────────────────────────────────────────


def extract_yaml_header_comments(path: Path) -> str:
    """Return leading # comment lines from a YAML file."""
    lines = []
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if not stripped or stripped == "---":
            continue
        if stripped.startswith("#"):
            lines.append(stripped[1:].strip())
        else:
            break
    return "\n".join(lines)


def build_title_from_conf(
    file_stem: str, description: str
) -> str:
    """Generate a human-readable title for a conf file test case."""
    if claude_available() and description:
        try:
            prompt = CONF_TITLE_PROMPT.format(
                file_stem=file_stem.replace("_", " "),
                description=description,
            )
            return (
                call_claude(prompt)
                .strip()
                .strip('"')
                .strip("'")
            )
        except Exception as e:
            print(
                f"  WARNING: AI title generation"
                f" failed: {e}"
            )
    words = file_stem.split("_")
    return " ".join(
        w.upper() if w.lower() in ACRONYMS else w.capitalize()
        for w in words
    )


def write_deployment_id_to_yaml(
    path: Path, wi_id: str
) -> None:
    """Write or update REPORTING.polarion.deployment_id in a YAML file."""
    text = path.read_text()

    if re.search(
        r"^\s+deployment_id\s*:", text, re.MULTILINE
    ):
        text = re.sub(
            r"^(\s+deployment_id\s*:)\s*.*$",
            rf"\g<1> '{wi_id}'",
            text,
            flags=re.MULTILINE,
        )
        path.write_text(text)
        return

    m = re.search(
        r"^( +)polarion\s*:\s*$", text, re.MULTILINE
    )
    if m:
        inner_indent = m.group(1) + "  "
        text = re.sub(
            r"^( +polarion\s*:\s*)$",
            rf"\1\n{inner_indent}deployment_id: '{wi_id}'",
            text,
            flags=re.MULTILINE,
        )
        path.write_text(text)
        return

    if re.search(
        r"^REPORTING\s*:", text, re.MULTILINE
    ):
        text = re.sub(
            r"^(REPORTING\s*:\s*)$",
            (
                rf"\1\n  polarion:\n"
                rf"    deployment_id: '{wi_id}'"
            ),
            text,
            flags=re.MULTILINE,
        )
        path.write_text(text)
        return

    if not text.endswith("\n"):
        text += "\n"
    text += (
        f"REPORTING:\n"
        f"  polarion:\n"
        f"    deployment_id: '{wi_id}'\n"
    )
    path.write_text(text)


def work_item_url(wi_id: str) -> str:
    """Build the Polarion redirect URL for a work item."""
    return (
        f"{POLARION_REDIRECT}"
        f"/project/{PROJECT}/workitem?id={wi_id}"
    )
