#!/bin/bash

# Exit on any error
set -e

# Start the FastAPI server. `exec` replaces the shell with uvicorn so it runs as
# PID 1: its exit code and stdout/stderr surface directly (a failed startup is a
# real non-zero exit, not swallowed by a pipe), and uvicorn receives SIGTERM for
# graceful shutdown without a manual trap.
exec uvicorn main:app --host "0.0.0.0" --port "8791"
