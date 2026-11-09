#!/bin/bash
# Quick test script for pipeline operations.
# Can be run from anywhere; resolves paths relative to this script's location.

# Repo root is two directories up from this script (dicom_handler/tests/ -> repo root).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================================================"
echo "Quick Pipeline Test"
echo "========================================================================"
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Activating virtual environment..."
    source "$REPO_ROOT/venv/bin/activate"
fi

# Run the interactive test script
python "$SCRIPT_DIR/run_pipeline_test.py"

echo ""
echo "Test completed!"
