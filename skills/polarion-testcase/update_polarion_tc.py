#!/usr/bin/env python3
"""Update an existing Polarion test case: post steps or add a related link.

Usage:
    python update_polarion_tc.py \\
        --work-item-id OCS-8221 \\
        [--test-path tests/functional/my_test.py] \\
        [--test-name test_my_feature] \\
        [--class-name TestMyClass] \\
        [--test-steps-file path/to/steps.yaml|.txt] \\
        [--no-generate-steps] \\
        [--steps-from-code] \\
        [--related-work-item OCS-7430]
"""

import argparse
import ast
import sys
from pathlib import Path

from constants import STEPS_FILE_EXAMPLE, TXT_STEPS_EXAMPLE
from polarion_tc_helpers import (
    ask,
    auto_extract_steps,
    find_function_node,
    get_project_dir,
    get_token,
    link_work_item,
    load_steps_file,
    post_test_steps,
    work_item_url,
)


def parse_args():
    """Parse command-line arguments for update mode."""
    p = argparse.ArgumentParser(
        description=(
            "Update an existing Polarion test case: "
            "post steps or add a related work item link."
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
    p.add_argument(
        "--work-item-id",
        required=True,
        help=(
            "Existing Polarion work item ID "
            "(e.g. OCS-8221)"
        ),
    )
    p.add_argument(
        "--test-path",
        default=None,
        help=(
            "Path to .py test file "
            "(for step extraction)"
        ),
    )
    p.add_argument(
        "--test-name",
        default=None,
        help=(
            "Test function name "
            "(required if --test-path is given)"
        ),
    )
    p.add_argument(
        "--class-name",
        default=None,
        help="Test class name for disambiguation",
    )
    p.add_argument(
        "--test-steps-file",
        metavar="PATH",
        default=None,
        help=(
            "YAML or plain-text (.txt) file with "
            "steps to post"
        ),
    )
    p.add_argument(
        "--no-generate-steps",
        action="store_true",
        help=(
            "Skip auto step generation "
            "(use with --test-steps-file)"
        ),
    )
    p.add_argument(
        "--steps-from-code",
        action="store_true",
        help=(
            "Ignore the docstring Steps section and"
            " derive steps from the test code instead"
        ),
    )
    p.add_argument(
        "--related-work-item",
        metavar="ID",
        default=None,
        help=(
            "Polarion ID to link as relates_to "
            "(e.g. OCS-7430)"
        ),
    )

    args = p.parse_args()

    if (
        not args.related_work_item
        and not args.test_path
        and not args.test_steps_file
    ):
        p.error(
            "At least one of --related-work-item, "
            "--test-path, or --test-steps-file is required."
        )
    if args.test_path and not args.test_name:
        tp = Path(args.test_path)
        if tp.suffix not in (".yaml", ".yml"):
            p.error(
                "--test-name is required when "
                "--test-path is a .py file"
            )

    return args


def main():
    """Update an existing Polarion work item."""
    args = parse_args()
    wi_id = args.work_item_id
    print(f"Update mode: {wi_id}")

    token = get_token()
    test_steps: list = []

    has_steps_source = (
        args.test_path or args.test_steps_file
    )

    if has_steps_source:
        if args.test_steps_file:
            steps_file = Path(
                args.test_steps_file
            ).resolve()
            ok, msg, test_steps, _, _ = load_steps_file(
                steps_file
            )
            if not ok:
                sys.exit(
                    f"ERROR: Steps file problem: {msg}"
                )
            print(f"Steps file: {msg}")

        if args.test_path:
            test_path = Path(args.test_path)
            if not test_path.is_absolute():
                project_dir = get_project_dir()
                if project_dir:
                    test_path = (
                        Path(project_dir) / test_path
                    )
            test_path = test_path.resolve()
            if not test_path.exists():
                sys.exit(
                    f"ERROR: File not found: {test_path}"
                )
            if test_path.suffix in (".yaml", ".yml"):
                sys.exit(
                    "ERROR: update mode does not support"
                    " conf files."
                )
            if test_path.suffix != ".py":
                sys.exit(
                    f"ERROR: Expected a .py file,"
                    f" got: {test_path}"
                )
            if not args.test_name:
                sys.exit(
                    "ERROR: --test-name is required for"
                    " .py test files."
                )

            source = test_path.read_text()
            try:
                ast.parse(source)
            except SyntaxError as e:
                sys.exit(
                    f"ERROR: Syntax error in"
                    f" {test_path}: {e}"
                )

            fn_node = find_function_node(
                source, args.test_name, args.class_name
            )
            if not fn_node:
                target = args.test_name
                if args.class_name:
                    target = (
                        f"{args.class_name}::{target}"
                    )
                sys.exit(
                    f"ERROR: Function '{target}'"
                    f" not found in {test_path}"
                )

            print(
                f"Found '{args.test_name}'"
                f" in {test_path.name}"
            )

            if not test_steps:
                generate_steps = (
                    not args.no_generate_steps
                )
                if generate_steps:
                    auto_test, _, _ = auto_extract_steps(
                        source,
                        args.test_name,
                        offer_ai=True,
                        class_name=args.class_name,
                        steps_from_code=(
                            args.steps_from_code
                        ),
                    )
                    if auto_test:
                        print(
                            f"Extracted"
                            f" {len(auto_test)}"
                            " test step(s)."
                        )
                        test_steps = auto_test

        if not test_steps:
            sys.exit(
                "ERROR: No steps to post. Nothing to do."
            )

        print(f"\nSteps to post to {wi_id}:")
        for i, s in enumerate(test_steps, 1):
            print(f"  {i}. {s['step']}")
            if (
                s["expected"]
                != "Step completes successfully."
            ):
                print(f"     Expected: {s['expected']}")

        if not ask(
            f"Post {len(test_steps)} step(s) to {wi_id}?"
        ):
            sys.exit("Aborted.")

        print(
            f"\nPosting {len(test_steps)} test step(s)"
            f" to {wi_id}..."
        )
        err = post_test_steps(token, wi_id, test_steps)
        if err:
            sys.exit(
                f"ERROR posting steps to {wi_id}:\n{err}"
            )
        print(
            f"  Posted {len(test_steps)} step(s)"
            f" to {wi_id}."
        )

    if args.related_work_item:
        print(
            f"Linking {wi_id} to"
            f" {args.related_work_item}..."
        )
        err = link_work_item(
            token, wi_id, args.related_work_item
        )
        if err:
            sys.exit(
                f"ERROR linking {wi_id} to"
                f" {args.related_work_item}:\n{err}"
            )
        print(
            f"  Linked {wi_id} to"
            f" {args.related_work_item}."
        )

    wi_url = work_item_url(wi_id)
    print()
    print("=" * 70)
    print(f"  Updated : {wi_id}")
    if test_steps:
        print(
            f"  Steps   : {len(test_steps)}"
            " test step(s) posted"
        )
    if args.related_work_item:
        print(f"  Linked  : {args.related_work_item}")
    print(f"  URL     : {wi_url}")
    print("=" * 70)
    print("\nDone.")


if __name__ == "__main__":
    main()
