#!/usr/bin/env python3
"""Create a Polarion test case from an OCS-CI test function or conf YAML.

Test file mode:
    python create_polarion_tc.py \\
        --test-path tests/functional/my_test.py \\
        --test-name test_my_feature \\
        [--class-name TestMyClass] \\
        [--title "My Title"] \\
        [--description "HTML or plain text"] \\
        [--caseimportance high] \\
        [--caseautomation automated] \\
        [--status draft] \\
        [--automationscript test_my_feature] \\
        [--setup "HTML or plain text"] \\
        [--teardown "HTML or plain text"] \\
        [--test-steps-file path/to/steps.yaml|.txt] \\
        [--no-generate-steps] \\
        [--steps-from-code] \\
        [--related-work-item OCS-7430] \\
        [--parametrize-all] \\
        [--param-index N]

Conf file mode (.yaml/.yml):
    python create_polarion_tc.py \\
        --test-path conf/deployment/vsphere/my_config.yaml \\
        [--title "My deployment title"] \\
        [--description "HTML or plain text"] \\
        [--caseimportance high] \\
        [--caseautomation automated] \\
        [--status draft] \\
        [--related-work-item OCS-7430]
"""

import argparse
import ast
import re
import sys
from pathlib import Path

from constants import (
    POLARION_REDIRECT,
    PROJECT,
    STEPS_FILE_EXAMPLE,
    TXT_STEPS_EXAMPLE,
    VALID_CASEAUTOMATION,
    VALID_CASEIMPORTANCE,
)
from polarion_tc_helpers import (
    ai_add_polarion_decorator,
    ai_update_docstring,
    ask,
    auto_extract_steps,
    build_title,
    build_title_from_conf,
    claude_available,
    create_parametrized_work_items,
    create_work_item,
    extract_parametrize_info,
    extract_yaml_header_comments,
    find_class_for_function,
    find_function_node,
    get_docstring,
    get_project_dir,
    get_token,
    link_work_item,
    load_steps_file,
    post_test_steps,
    print_preview,
    steps_to_html,
    substitute_params_in_attrs,
    substitute_params_in_steps,
    to_html,
    work_item_url,
    write_deployment_id_to_yaml,
)


# ── Conf file workflow ───────────────────────────────────────────────────────


def conf_main(args, test_path: Path) -> None:
    """Create a description-only Polarion test case from a conf file."""
    print(f"Conf file mode: {test_path.name}")
    if claude_available():
        print(f"Claude CLI available (AI features enabled)")
    else:
        print("Claude CLI: not found (AI features disabled)")

    description = args.description
    if not description:
        description = extract_yaml_header_comments(
            test_path
        )
        if description:
            print(
                "  Extracted description from"
                " header comments."
            )
        else:
            print(
                "  No header comments found"
                " — description will be empty."
            )

    title = args.title
    if not title:
        print("  Generating title...")
        title = build_title_from_conf(
            test_path.stem, description
        )

    attrs: dict = {
        "type": "testcase",
        "title": title,
        "status": args.status,
        "caseautomation": args.caseautomation,
        "caseimportance": args.caseimportance,
    }
    if description:
        attrs["description"] = {
            "type": "text/html",
            "value": to_html(description),
        }

    print_preview(attrs, [], [], [])
    if args.related_work_item:
        print(f"  Will link to: {args.related_work_item}")
        print()

    if not ask("Create this Polarion test case?"):
        sys.exit("Aborted.")

    token = get_token()
    print("\nCreating work item...")
    wi_id, err = create_work_item(token, attrs)
    if err:
        sys.exit(f"ERROR creating work item:\n{err}")
    print(f"  Created: {wi_id}")

    if args.related_work_item:
        print(
            f"  Linking to {args.related_work_item}..."
        )
        err = link_work_item(
            token, wi_id, args.related_work_item
        )
        if err:
            print(
                f"  WARNING: Failed to link:\n{err}"
            )

    wi_url = work_item_url(wi_id)
    print()
    print("=" * 70)
    print(f"  Created : {wi_id}")
    print(f"  Title   : {title}")
    if args.related_work_item:
        print(f"  Linked  : {args.related_work_item}")
    print(f"  URL     : {wi_url}")
    print("=" * 70)

    print()
    if ask(
        f"Write 'deployment_id: {wi_id}' to"
        f" REPORTING.polarion in {test_path.name}?",
        default=True,
    ):
        write_deployment_id_to_yaml(test_path, wi_id)
        print(f"  Updated {test_path.name}")

    print("\nDone.")


# ── Args ─────────────────────────────────────────────────────────────────────


def parse_args():
    """Parse command-line arguments for create mode."""
    p = argparse.ArgumentParser(
        description=(
            "Create a Polarion test case from an "
            "OCS-CI test function (.py) or deployment "
            "conf file (.yaml/.yml)."
        ),
        formatter_class=(
            argparse.RawDescriptionHelpFormatter
        ),
        epilog=(
            f"Steps file format (YAML):\n"
            f"{STEPS_FILE_EXAMPLE}\n"
            f"Steps file format (plain text .txt):\n"
            f"{TXT_STEPS_EXAMPLE}"
        ),
    )
    req = p.add_argument_group("required")
    req.add_argument(
        "--test-path",
        required=True,
        help=(
            "Path to the test .py file or a deployment"
            " conf .yaml/.yml file"
        ),
    )
    req.add_argument(
        "--test-name",
        default=None,
        help=(
            "Test function name "
            "(e.g. test_add_capacity_cli). "
            "Required for .py files; "
            "not used for conf files."
        ),
    )
    req.add_argument(
        "--class-name",
        default=None,
        help=(
            "Test class name to narrow the search "
            "(e.g. TestRbdCBTMetadata). Optional."
        ),
    )
    opt = p.add_argument_group("optional overrides")
    opt.add_argument(
        "--title",
        help="Override auto-generated title",
    )
    opt.add_argument(
        "--description",
        help="Description (HTML or plain text)",
    )
    opt.add_argument(
        "--status",
        default="draft",
        help="Status (default: draft)",
    )
    opt.add_argument(
        "--caseautomation",
        default="automated",
        choices=sorted(VALID_CASEAUTOMATION),
        help="default: automated",
    )
    opt.add_argument(
        "--caseimportance",
        default="high",
        choices=sorted(VALID_CASEIMPORTANCE),
        help="default: high",
    )
    opt.add_argument(
        "--automationscript",
        help=(
            "Automation script name "
            "(default: --test-name value)"
        ),
    )
    opt.add_argument(
        "--setup",
        help=(
            "Setup description (HTML or plain text); "
            "skips auto-extraction"
        ),
    )
    opt.add_argument(
        "--teardown",
        help=(
            "Teardown description (HTML or plain text);"
            " skips auto-extraction"
        ),
    )
    opt.add_argument(
        "--test-steps-file",
        metavar="PATH",
        help=(
            "YAML or plain-text (.txt) file with steps"
        ),
    )
    opt.add_argument(
        "--no-generate-steps",
        action="store_true",
        help=(
            "Skip auto step generation from docstring"
            " or the test body"
        ),
    )
    opt.add_argument(
        "--steps-from-code",
        action="store_true",
        help=(
            "Ignore the docstring Steps section and"
            " derive steps from the test code instead"
        ),
    )
    opt.add_argument(
        "--related-work-item",
        metavar="ID",
        help=(
            "Polarion ID to link as relates_to "
            "(e.g. OCS-7430)"
        ),
    )
    opt.add_argument(
        "--param-index",
        type=int,
        metavar="N",
        help=(
            "Create a work item for a single "
            "parametrize set by 0-based index"
        ),
    )
    opt.add_argument(
        "--parametrize-all",
        action="store_true",
        help=(
            "Create work items for all"
            " parametrize sets"
        ),
    )

    return p.parse_args()


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    """Create a new Polarion test case."""
    args = parse_args()
    generate_steps = not args.no_generate_steps

    # 1. Validate test path and branch on file type
    test_path = Path(args.test_path)
    if not test_path.is_absolute():
        project_dir = get_project_dir()
        if project_dir:
            test_path = Path(project_dir) / test_path
    test_path = test_path.resolve()
    if not test_path.exists():
        sys.exit(f"ERROR: File not found: {test_path}")

    if test_path.suffix in (".yaml", ".yml"):
        conf_main(args, test_path)
        return

    if test_path.suffix != ".py":
        sys.exit(
            "ERROR: Expected a .py or .yaml/.yml file,"
            f" got: {test_path}"
        )

    if not args.test_name:
        sys.exit(
            "ERROR: --test-name is required"
            " for .py test files."
        )

    source = test_path.read_text()
    try:
        ast.parse(source)
    except SyntaxError as e:
        sys.exit(
            f"ERROR: Syntax error in {test_path}: {e}"
        )

    fn_node = find_function_node(
        source, args.test_name, args.class_name
    )
    if not fn_node:
        target = args.test_name
        if args.class_name:
            target = f"{args.class_name}::{target}"
        sys.exit(
            f"ERROR: Function '{target}'"
            f" not found in {test_path}"
        )

    print(
        f"Found '{args.test_name}' in {test_path.name}"
    )
    if claude_available():
        print("Claude CLI available (AI features enabled)")
    else:
        print(
            "Claude CLI: not found"
            " (AI features disabled)"
        )

    # 1.5. Check for parametrize
    param_info = extract_parametrize_info(
        source, args.test_name, args.class_name
    )

    if param_info is not None:
        if (
            args.parametrize_all
            or args.param_index is not None
        ):
            pass
        else:
            n = len(param_info)
            print(
                f"\nParametrized test detected"
                f" with {n} param set(s):"
            )
            for ps in param_info:
                param_str = ", ".join(
                    f"{k}={v}"
                    for k, v in ps["params"].items()
                )
                existing = (
                    f" (existing:"
                    f" {ps['existing_polarion_id']})"
                    if ps["existing_polarion_id"]
                    else ""
                )
                print(
                    f"  [{ps['index']}]"
                    f" {param_str}{existing}"
                )

            print()
            try:
                resp = (
                    input(
                        "Create for (a)ll param sets"
                        " or (o)ne? [a/o]: "
                    )
                    .strip()
                    .lower()
                )
            except (EOFError, KeyboardInterrupt):
                print()
                sys.exit("Aborted.")

            if resp in ("o", "one"):
                print(
                    "\nRerun with --param-index <N>"
                    " for a specific param set."
                    " Example:"
                )
                print(
                    f"  python {sys.argv[0]}"
                    f" --test-path {args.test_path}"
                    f" --test-name {args.test_name}"
                    f" --param-index 0"
                )
                sys.exit(0)
            elif resp not in ("a", "all", ""):
                sys.exit("Aborted.")
            args.parametrize_all = True

        if args.param_index is not None:
            if (
                args.param_index < 0
                or args.param_index >= len(param_info)
            ):
                sys.exit(
                    f"ERROR: --param-index"
                    f" {args.param_index} out of range"
                    f" (0-{len(param_info) - 1})"
                )
    elif (
        args.parametrize_all
        or args.param_index is not None
    ):
        print(
            "WARNING: --parametrize-all / --param-index"
            " ignored — test is not parametrized."
        )
        args.parametrize_all = False
        args.param_index = None

    # 2. Load steps from file if provided
    test_steps: list = []
    setup_steps: list = []
    teardown_steps: list = []

    if args.test_steps_file:
        steps_file = Path(
            args.test_steps_file
        ).resolve()
        (
            ok,
            msg,
            test_steps,
            setup_steps,
            teardown_steps,
        ) = load_steps_file(steps_file)
        if not ok:
            print(
                f"\nWARNING: Steps file problem: {msg}"
            )
            if steps_file.suffix.lower() == ".txt":
                print("Expected text format:")
                print(TXT_STEPS_EXAMPLE)
            else:
                print("Expected YAML format:")
                print(STEPS_FILE_EXAMPLE)
            if not ask(
                "Continue and auto-generate"
                " steps instead?"
            ):
                sys.exit(1)
            test_steps = []
            setup_steps = []
            teardown_steps = []
        else:
            print(f"Steps file: {msg}")

    # 3. Auto-generate any missing steps
    if generate_steps:
        auto_test, auto_setup, auto_teardown = (
            auto_extract_steps(
                source,
                args.test_name,
                offer_ai=True,
                class_name=args.class_name,
                steps_from_code=args.steps_from_code,
            )
        )
        if not test_steps and auto_test:
            print(
                f"Extracted {len(auto_test)}"
                " test step(s)."
            )
            test_steps = auto_test
        elif not test_steps:
            print(
                "WARNING: No test steps found."
                " Work item will be created"
                " without steps."
            )
        if (
            not setup_steps
            and not args.setup
            and auto_setup
        ):
            print(
                f"Extracted {len(auto_setup)}"
                " setup step(s)."
            )
            setup_steps = auto_setup
        if (
            not teardown_steps
            and not args.teardown
            and auto_teardown
        ):
            print(
                f"Extracted {len(auto_teardown)}"
                " teardown step(s)."
            )
            teardown_steps = auto_teardown

    # 4. Build work item attributes
    title = args.title or build_title(args.test_name)
    automationscript = (
        args.automationscript or args.test_name
    )

    description = args.description
    if not description:
        fn_doc = get_docstring(fn_node)
        cls_node = find_class_for_function(
            source, args.test_name, args.class_name
        )
        cls_doc = (
            get_docstring(cls_node) if cls_node else ""
        )
        base = fn_doc or cls_doc
        if base:
            first_para = re.split(
                r"\n\s*(Steps|Test Steps|Setup"
                r"|Teardown|Args|Returns"
                r"|Raises)\s*:",
                base,
            )[0].strip()
            description = first_para.replace("\n", " ")

    attrs: dict = {
        "type": "testcase",
        "title": title,
        "status": args.status,
        "caseautomation": args.caseautomation,
        "caseimportance": args.caseimportance,
        "automationscript": automationscript,
    }
    if description:
        attrs["description"] = {
            "type": "text/html",
            "value": to_html(description),
        }

    if args.setup:
        attrs["setup"] = {
            "type": "text/html",
            "value": to_html(args.setup),
        }
    elif setup_steps:
        attrs["setup"] = {
            "type": "text/html",
            "value": steps_to_html(setup_steps),
        }

    if args.teardown:
        attrs["teardown"] = {
            "type": "text/html",
            "value": to_html(args.teardown),
        }
    elif teardown_steps:
        attrs["teardown"] = {
            "type": "text/html",
            "value": steps_to_html(teardown_steps),
        }

    # 5. Handle parametrize-all
    if param_info is not None and args.parametrize_all:
        print_preview(
            attrs,
            test_steps,
            setup_steps,
            teardown_steps,
        )
        n = len(param_info)
        print(
            f"\n  Will create {n}"
            " parametrized work item(s):"
        )
        for ps in param_info:
            param_str = ", ".join(
                f"{k}={v}"
                for k, v in ps["params"].items()
            )
            print(
                f"    [{ps['index']}]"
                f" {title} ({param_str})"
            )
        if args.related_work_item:
            print(
                f"  Will link each to:"
                f" {args.related_work_item}"
            )
        print()

        if not ask(
            "Create all parametrized work items?"
        ):
            sys.exit("Aborted.")

        token = get_token()
        print("\nCreating parametrized work items...")
        results = create_parametrized_work_items(
            token,
            attrs,
            test_steps,
            param_info,
            args.test_name,
            args.related_work_item,
        )

        hr = "=" * 70
        print(f"\n{hr}")
        print("PARAMETRIZED WORK ITEMS SUMMARY")
        print(hr)
        for r in results:
            param_str = ", ".join(
                f"{k}={v}"
                for k, v in r["params"].items()
            )
            if r["wi_id"]:
                wi_url = work_item_url(r["wi_id"])
                print(
                    f"  [{r['index']}] {r['wi_id']}"
                    f" — {param_str}"
                )
                print(f"       {wi_url}")
            else:
                print(
                    f"  [{r['index']}] FAILED"
                    f" — {param_str}"
                )
                print(f"       {r['error']}")
        print(hr)

        if setup_steps:
            print(
                "\n--- SETUP STEPS"
                " (enter manually in Polarion UI) ---"
            )
            if len(setup_steps) == 1:
                print(
                    f"{setup_steps[0]['step']}"
                    f" | Expected:"
                    f" {setup_steps[0]['expected']}"
                )
            else:
                for i, s in enumerate(setup_steps, 1):
                    print(
                        f"{i}. {s['step']}"
                        f" | Expected: {s['expected']}"
                    )
        if teardown_steps:
            print(
                "\n--- TEARDOWN STEPS"
                " (enter manually in Polarion UI) ---"
            )
            if len(teardown_steps) == 1:
                print(
                    f"{teardown_steps[0]['step']}"
                    f" | Expected:"
                    f" {teardown_steps[0]['expected']}"
                )
            else:
                for i, s in enumerate(teardown_steps, 1):
                    print(
                        f"{i}. {s['step']}"
                        f" | Expected: {s['expected']}"
                    )

        print("\nDone.")
        return

    # 5.5. Adjust attrs for single param set
    if (
        param_info is not None
        and args.param_index is not None
    ):
        ps = param_info[args.param_index]
        params = ps["params"]
        param_str = ", ".join(
            f"{k}={v}" for k, v in params.items()
        )
        param_id = "-".join(
            str(v) for v in params.values()
        )
        attrs = substitute_params_in_attrs(
            attrs, params
        )
        if not args.title:
            attrs["title"] = f"{title} ({param_str})"
        attrs["automationscript"] = (
            f"{args.test_name}[{param_id}]"
        )
        test_steps = substitute_params_in_steps(
            test_steps, params
        )

    # 6. Preview and confirm
    print_preview(
        attrs, test_steps, setup_steps, teardown_steps
    )
    if args.related_work_item:
        print(
            f"  Will link to: {args.related_work_item}"
        )
        print()

    if not ask("Create this Polarion test case?"):
        sys.exit("Aborted.")

    # 7. Create work item
    token = get_token()
    print("\nCreating work item...")
    wi_id, err = create_work_item(token, attrs)
    if err:
        sys.exit(f"ERROR creating work item:\n{err}")
    print(f"  Created: {wi_id}")

    # 8. Post test steps
    if test_steps:
        print(
            f"  Posting {len(test_steps)}"
            " test step(s)..."
        )
        err = post_test_steps(token, wi_id, test_steps)
        if err:
            print(
                f"  WARNING: Failed to post"
                f" steps:\n{err}"
            )
            print(
                "  Add them manually in the"
                " Polarion UI."
            )

    # 9. Link related work item
    if args.related_work_item:
        print(
            f"  Linking to {args.related_work_item}..."
        )
        err = link_work_item(
            token, wi_id, args.related_work_item
        )
        if err:
            print(
                f"  WARNING: Failed to link:\n{err}"
            )

    # 10. Summary
    wi_url = work_item_url(wi_id)
    print()
    print("=" * 70)
    print(f"  Created : {wi_id}")
    print(f"  Title   : {attrs['title']}")
    print(
        f"  Steps   : {len(test_steps)}"
        " test step(s) via API"
    )
    if args.related_work_item:
        print(f"  Linked  : {args.related_work_item}")
    print(f"  URL     : {wi_url}")
    print("=" * 70)

    if setup_steps:
        print(
            "\n--- SETUP STEPS"
            " (enter manually in Polarion UI) ---"
        )
        if len(setup_steps) == 1:
            print(
                f"{setup_steps[0]['step']}"
                f" | Expected:"
                f" {setup_steps[0]['expected']}"
            )
        else:
            for s in setup_steps:
                print(
                    f"- {s['step']}"
                    f" | Expected: {s['expected']}"
                )

    if teardown_steps:
        print(
            "\n--- TEARDOWN STEPS"
            " (enter manually in Polarion UI) ---"
        )
        if len(teardown_steps) == 1:
            print(
                f"{teardown_steps[0]['step']}"
                f" | Expected:"
                f" {teardown_steps[0]['expected']}"
            )
        else:
            for s in teardown_steps:
                print(
                    f"- {s['step']}"
                    f" | Expected: {s['expected']}"
            )

    # 11. Add @polarion decorator (AI-assisted)
    print()
    if ask(
        f'Add @polarion_id("{wi_id}") decorator'
        f" to {test_path.name}?"
    ):
        if not ai_add_polarion_decorator(
            test_path, args.test_name, wi_id
        ):
            print(
                f"  Add manually:\n"
                f'  @polarion_id("{wi_id}")\n'
                f"  def {args.test_name}(..."
            )

    # 12. Update docstring Steps section (AI-assisted)
    if test_steps and ask(
        "Update test docstring Steps section"
        " to match Polarion steps?"
    ):
        if not ai_update_docstring(
            test_path, args.test_name, test_steps
        ):
            print("  Skipped.")

    print("\nDone.")


if __name__ == "__main__":
    main()
