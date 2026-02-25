"""Gunicorn configuration for Render deployment.

Key settings:
- preload_app: Load Flask app in master before forking workers.
  Faster worker boot + less memory (shared via copy-on-write).
  Safe because DB init is deferred to first request (not at import time).
- graceful_timeout: How long old workers have to finish during deploys.
  Low value so the old process releases the port quickly for the new one.
- Lifecycle hooks: Log worker fork/exit/abort for debugging deploy issues.
"""

import os
import sys

# --- Server socket ---
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

# --- Timeouts ---
timeout = 120           # Max time for a request to complete
graceful_timeout = 10   # Max time for old workers to finish during shutdown

# --- App loading ---
preload_app = True      # Load app in master, fork lighter workers

# --- Lifecycle hooks for visibility ---

def on_starting(server):
    print(f"[gunicorn] Master starting (pid {os.getpid()})", flush=True)

def post_fork(server, worker):
    print(f"[gunicorn] Worker forked (pid {worker.pid})", flush=True)

def worker_abort(worker):
    print(f"[gunicorn] Worker ABORTED (pid {worker.pid})", flush=True, file=sys.stderr)

def worker_exit(server, worker):
    print(f"[gunicorn] Worker exited (pid {worker.pid})", flush=True)
