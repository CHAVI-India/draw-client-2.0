#!/bin/bash
# Quick test script for pipeline operations

echo "========================================================================"
echo "Quick Pipeline Test"
echo "========================================================================"
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Run the interactive test script
python run_pipeline_test.py

echo ""
echo "Test completed!"
