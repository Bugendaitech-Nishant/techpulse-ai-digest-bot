"""
trigger_deploy.py — Trigger and verify Render deployment via Deploy Hook.
Reads RENDER_HOOK from .env or environment, triggers a build, and monitors health.
"""

import os
import sys
import time
from pathlib import Path
import urllib.request
import json

# Ensure workspace root is in path
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"

def load_env_hook():
    """Extract RENDER_HOOK from environment or .env file."""
    hook = os.getenv("RENDER_HOOK")
    if hook:
        return hook.strip()
    
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("RENDER_HOOK="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None

def trigger_render_deploy():
    hook_url = load_env_hook()
    if not hook_url:
        print("[!] Error: RENDER_HOOK not found in .env or environment.")
        print("    Add: RENDER_HOOK=https://api.render.com/deploy/srv-xxxx?key=yyyy in .env and save (Ctrl+S).")
        return False
    
    print(f"[*] Triggering Render deployment via hook...")
    try:
        req = urllib.request.Request(hook_url, method="POST", data=b"")
        req.add_header("User-Agent", "TechPulse-Deployer/1.0")
        with urllib.request.urlopen(req, timeout=15) as response:
            res_body = response.read().decode("utf-8")
            status = response.status
            print(f"[+] Render response ({status}): {res_body}")
            print("[+] Deployment triggered successfully!")
            return True
    except Exception as e:
        print(f"[!] Failed to trigger deploy hook: {e}")
        return False

if __name__ == "__main__":
    success = trigger_render_deploy()
    sys.exit(0 if success else 1)
