#!/bin/bash
# Wrapper to pass env vars to the search script
cd "$(dirname "$0")/.."
GETXAPI_KEY="${GETXAPI_KEY}" python3 scripts/search_tweets.py "$@"
