#!/usr/bin/env python3
"""Check if GETXAPI_KEY is accessible from terminal Python."""
import os
key = os.environ.get('GETXAPI_KEY')
token = os.environ.get('X_AUTH_TOKEN')
print(f"KEY_PRESENT={key is not None}")
print(f"KEY_LEN={len(key) if key else 0}")
print(f"TOKEN_PRESENT={token is not None}")
print(f"TOKEN_LEN={len(token) if token else 0}")
# Also check all env vars for patterns
all_keys = [k for k in os.environ if 'GETXAPI' in k or 'X_AUTH' in k]
print(f"MATCHING_ENV_KEYS={all_keys}")
