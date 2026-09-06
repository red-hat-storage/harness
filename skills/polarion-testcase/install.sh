#!/bin/bash
# Install polarion-testcase skill via symlink.
# Usage: ./install.sh --project /path/to/python-project [--skills-dir /path/to/skills] [--token <polarion-token>]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR=""
PROJECT_DIR=""
TOKEN=""
TOKEN_FILE="$HOME/.polarion-token"
CONF_FILE="$HOME/.polarion-testcase.conf"

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --skills-dir)
            SKILL_DIR="$2/polarion-testcase"
            shift 2
            ;;
        --project)
            PROJECT_DIR="$(cd "$2" && pwd)"
            shift 2
            ;;
        --token)
            TOKEN="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 --project /path/to/python-project [--skills-dir /path/to/skills] [--token <token>]"
            exit 1
            ;;
    esac
done

if [ -z "$PROJECT_DIR" ]; then
    echo "Error: --project is required"
    echo "Usage: $0 --project /path/to/python-project [--skills-dir /path/to/skills] [--token <token>]"
    exit 1
fi

# Default skill dir: ~/.claude/skills/polarion-testcase
if [ -z "$SKILL_DIR" ]; then
    SKILL_DIR="$HOME/.claude/skills/polarion-testcase"
fi

# Create skill directory if needed
mkdir -p "$SKILL_DIR"

# Symlink SKILL.md
ln -sf "$REPO_DIR/SKILL.md" "$SKILL_DIR/SKILL.md"
echo "Linked: $SKILL_DIR/SKILL.md -> $REPO_DIR/SKILL.md"

# Write config file
cat > "$CONF_FILE" <<EOF
POLARION_SCRIPT_PATH="$REPO_DIR/create_polarion_tc.py"
POLARION_PROJECT_DIR="$PROJECT_DIR"
EOF
echo "Config saved to $CONF_FILE"

# Write token file
if [ -n "$TOKEN" ]; then
    echo "$TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "Token saved to $TOKEN_FILE (mode 600)"
fi

echo ""
echo "Done."
echo "  Skill:   $SKILL_DIR/SKILL.md"
echo "  Script:  $REPO_DIR/create_polarion_tc.py"
echo "  Project: $PROJECT_DIR"
if [ -z "$TOKEN" ] && [ ! -f "$TOKEN_FILE" ]; then
    echo ""
    echo "NOTE: No Polarion token configured."
    echo "Set POLARION_TOKEN env var or rerun with --token <token>"
fi
