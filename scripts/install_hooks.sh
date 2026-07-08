#!/bin/sh
# Install wikilens hooks from .pre-commit-config.yaml. Run once after cloning.
#
# Usage:
#   sh scripts/install_hooks.sh
set -e

git rev-parse --show-toplevel >/dev/null

if ! command -v pre-commit >/dev/null 2>&1; then
    echo "pre-commit is required. Install it with: python -m pip install pre-commit" >&2
    exit 1
fi

pre-commit install
pre-commit install --hook-type pre-push
echo "installed wikilens pre-commit and pre-push hooks"
