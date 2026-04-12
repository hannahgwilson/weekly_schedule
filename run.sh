#!/bin/bash
# Wrapper script for the weekly schedule generator.
# Called by launchd on Sunday at 1pm.

cd "$(dirname "$0")"

# Activate venv if it exists
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

echo ""
echo "================================================"
echo "  🗓️  Weekly Schedule Generator"
echo "  $(date '+%A, %B %d %Y at %I:%M %p')"
echo "================================================"
echo ""

python3 generate_schedule.py

echo ""
echo "Press any key to close..."
read -n 1
