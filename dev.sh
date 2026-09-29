#!/usr/bin/env bash
# Set up the packages for local development and run their tests.
#
#   ./dev.sh              offline suites (a localhost range server; no network)
#   ./dev.sh -m live      also read a real remote h5ad
#   ./dev.sh -q -k obs    any other pytest arguments pass straight through
#
# The eval *cases* are not run here -- they drive a real agent and cost money.
# See evals/README.md.
set -euo pipefail
cd "$(dirname "$0")"

for pkg in h5ad-obs celltype-column-eval paper-access; do
  uv venv -q --allow-existing "packages/$pkg/.venv"
  uv pip install -q --python "packages/$pkg/.venv/bin/python" -e "packages/$pkg[test]"
done

packages/h5ad-obs/.venv/bin/python -m pytest packages/h5ad-obs "$@"
packages/paper-access/.venv/bin/python -m pytest packages/paper-access "$@"
packages/celltype-column-eval/.venv/bin/python -m pytest packages/celltype-column-eval "$@"
# The grader unit tests are free and offline: they keep a rejection check from
# quietly failing the answers it is supposed to pass.
packages/celltype-column-eval/.venv/bin/python -m pytest evals "$@"
