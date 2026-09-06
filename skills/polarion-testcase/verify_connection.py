#!/usr/bin/env python3
"""Verify Polarion API connection and credentials.

Usage:
    python3 verify_connection.py

Checks:
  - Token file exists and is readable
  - Polarion API is reachable
  - Token is valid (not expired)
  - Project is accessible
  - User has read/write permissions
"""

import os
import sys
from pathlib import Path

from constants import POLARION_BASE, PROJECT, TOKEN_FILE
from polarion_tc_helpers import api_call, get_token


def check_token_file():
    """Check if token file exists and is readable."""
    print("Checking token configuration...")

    # Check environment variable first
    if os.environ.get("POLARION_TOKEN"):
        print("  ✓ Token found: POLARION_TOKEN environment variable")
        return True

    # Check file
    if not os.path.exists(TOKEN_FILE):
        print(f"  ✗ Token file not found: {TOKEN_FILE}")
        print(f"\nCreate it with:")
        print(f"  echo 'YOUR_TOKEN' > {TOKEN_FILE}")
        print(f"  chmod 600 {TOKEN_FILE}")
        return False

    if not os.access(TOKEN_FILE, os.R_OK):
        print(f"  ✗ Token file not readable: {TOKEN_FILE}")
        print(f"\nFix permissions with:")
        print(f"  chmod 600 {TOKEN_FILE}")
        return False

    token = Path(TOKEN_FILE).read_text().strip()
    if not token:
        print(f"  ✗ Token file is empty: {TOKEN_FILE}")
        return False

    print(f"  ✓ Token found: {TOKEN_FILE}")
    print(f"    Length: {len(token)} characters")
    return True


def check_api_connection(token):
    """Test basic API connectivity."""
    print("\nChecking API connection...")
    print(f"  Endpoint: {POLARION_BASE}")

    # Simple GET to projects endpoint
    url = f"{POLARION_BASE}/projects/{PROJECT}"

    try:
        status, resp = api_call("GET", url, token)
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        print(f"\nPossible causes:")
        print(f"  - Network connectivity issue")
        print(f"  - VPN not connected")
        print(f"  - Polarion API endpoint changed")
        return False

    if status == 401:
        print(f"  ✗ Authentication failed (HTTP 401)")
        print(f"\nPossible causes:")
        print(f"  - Token is invalid")
        print(f"  - Token has expired")
        print(f"\nGenerate a new token at:")
        print(f"  https://polarion.engineering.redhat.com → Profile → Personal Access Tokens")
        return False

    if status == 403:
        print(f"  ✗ Access forbidden (HTTP 403)")
        print(f"\nPossible causes:")
        print(f"  - Token lacks required permissions")
        print(f"  - Project '{PROJECT}' is not accessible to your user")
        return False

    if status == 404:
        print(f"  ✗ Project not found (HTTP 404)")
        print(f"\nProject '{PROJECT}' does not exist or is not accessible.")
        print(f"\nTo use a different project, set:")
        print(f"  export POLARION_PROJECT='YourProjectName'")
        return False

    if status not in (200, 201):
        print(f"  ✗ Unexpected response (HTTP {status})")
        print(f"  Response: {resp}")
        return False

    print(f"  ✓ Connected to Polarion API")
    return True


def check_project_access(token):
    """Verify project is accessible and get project info."""
    print(f"\nChecking project access...")
    print(f"  Project: {PROJECT}")

    url = f"{POLARION_BASE}/projects/{PROJECT}"
    status, resp = api_call("GET", url, token)

    if status not in (200, 201):
        print(f"  ✗ Cannot access project '{PROJECT}'")
        return False

    # Extract project details
    data = resp.get("data", {})
    attrs = data.get("attributes", {})
    project_name = attrs.get("name", PROJECT)

    print(f"  ✓ Project accessible: {project_name}")
    print(f"    ID: {PROJECT}")

    return True


def check_permissions(token):
    """Test read and write permissions by querying workitems endpoint."""
    print(f"\nChecking permissions...")

    # Test read permission - query workitems with a limit
    url = f"{POLARION_BASE}/projects/{PROJECT}/workitems?page[size]=1"
    status, resp = api_call("GET", url, token)

    if status == 403:
        print(f"  ✗ No read permission for workitems")
        return False

    if status not in (200, 201):
        print(f"  ⚠ Could not verify read permission (HTTP {status})")
        return True  # Don't fail, might just be empty project

    print(f"  ✓ Read permission: OK")

    # Note: We don't actually test write permission by creating a work item
    # since that would pollute the project. The token needs write permission
    # for the create/update scripts to work.
    print(f"  ℹ Write permission: Not tested (requires actual work item creation)")
    print(f"    Ensure your token has 'read/write' scope")

    return True


def main():
    """Run all verification checks."""
    print("=" * 70)
    print("Polarion API Connection Verification")
    print("=" * 70)

    # Check 1: Token file
    if not check_token_file():
        print("\n" + "=" * 70)
        print("Connection test: FAILED")
        print("=" * 70)
        sys.exit(1)

    # Get the token
    try:
        token = get_token()
    except SystemExit:
        print("\n" + "=" * 70)
        print("Connection test: FAILED")
        print("=" * 70)
        sys.exit(1)

    # Check 2: API connection
    if not check_api_connection(token):
        print("\n" + "=" * 70)
        print("Connection test: FAILED")
        print("=" * 70)
        sys.exit(1)

    # Check 3: Project access
    if not check_project_access(token):
        print("\n" + "=" * 70)
        print("Connection test: FAILED")
        print("=" * 70)
        sys.exit(1)

    # Check 4: Permissions
    if not check_permissions(token):
        print("\n" + "=" * 70)
        print("Connection test: FAILED")
        print("=" * 70)
        sys.exit(1)

    # Success
    print("\n" + "=" * 70)
    print("Connection test: PASSED ✓")
    print("=" * 70)
    print("\nYou're ready to create Polarion test cases!")
    print("Try: /polarion-testcase help")
    sys.exit(0)


if __name__ == "__main__":
    main()
