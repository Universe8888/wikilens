#!/bin/sh
# Install wikilens git hooks into .git/hooks/. Run once after cloning.
#
# Usage:
#   sh scripts/install_hooks.sh
set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOK_DIR="$REPO_ROOT/.git/hooks"

cat > "$HOOK_DIR/pre-commit" <<'EOF'
#!/bin/sh
# wikilens pre-commit: sanitization gate.
set -e
python scripts/check_sanitization.py
EOF

chmod +x "$HOOK_DIR/pre-commit"
echo "installed: $HOOK_DIR/pre-commit"
