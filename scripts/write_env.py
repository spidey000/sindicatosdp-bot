#!/usr/bin/env python3
"""Fix .env with actual credentials from environment."""
import os
import sys
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / ".env"

key = os.environ.get("GETXAPI_KEY", "")
token = os.environ.get("X_AUTH_TOKEN", "")

print(f"Key from env: present={bool(key)}, len={len(key)}")
print(f"Token from env: present={bool(token)}, len={len(token)}")

if len(key) < 5 or len(token) < 5:
    print("ERROR: Credentials too short or empty", file=sys.stderr)
    sys.exit(1)

with open(env_path, "w") as f:
    f.write(f"GETXAPI_KEY={key}\n")
    f.write("GETXAPI_BASE_URL=https://api.getxapi.com\n")
    f.write(f"X_AUTH_TOKEN={token}\n")
    f.write("X_USERNAME=sindicatosdpMAD\n")

print(f"Written .env at {env_path}")
sys.exit(0)
