# File: scripts/run_autonomous_campaign.py
"""
Root entry-point wrapper for run_autonomous_campaign.py.
"""
import os
import sys

# Forward all arguments to ai/scripts/run_autonomous_campaign.py
SCRIPT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai", "scripts", "run_autonomous_campaign.py"))

if __name__ == "__main__":
    import subprocess
    cmd = [sys.executable, SCRIPT_PATH] + sys.argv[1:]
    sys.exit(subprocess.call(cmd))
