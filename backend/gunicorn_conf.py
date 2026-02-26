"""Gunicorn configuration for Render deployment.

Key settings:
- preload_app disabled: Render's "New primary port detected" restart kills
  the first boot and starts a second. With preload_app=True the second boot's
  worker fork fails (resource conflict with dying old process). Loading the
  app per-worker avoids this. DB init is still deferred to first request.
- graceful_timeout: How long old workers have to finish during deploys.
  Low value so the old process releases the port quickly for the new one.
- keep_alive: Render's load balancer needs connections kept open.
- Lifecycle hooks: Log worker fork/exit/abort for debugging deploy issues.
"""

import os
import sys

# --- Server socket ---
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

# --- Timeouts ---
timeout = 120           # Max time for a request to complete
graceful_timeout = 10   # Max time for old workers to finish during shutdown

# --- Workers ---
workers = int(os.environ.get("WEB_CONCURRENCY", 1))

# --- App loading ---
# preload_app=True loads app in master before forking workers.
# Combined with deferred DB init (first real request triggers init_db),
# this is safe: the master loads Python code only, no DB connections.
preload_app = True

# --- Lifecycle hooks for visibility ---

def on_starting(server):
    print(f"[gunicorn] Master starting (pid {os.getpid()})", flush=True)

def post_fork(server, worker):
    print(f"[gunicorn] Worker forked (pid {worker.pid})", flush=True)

def post_worker_init(worker):
    print(f"[gunicorn] Worker ready (pid {worker.pid})", flush=True)

def worker_abort(worker):
    print(f"[gunicorn] Worker ABORTED (pid {worker.pid})", flush=True, file=sys.stderr)

def worker_int(worker):
    print(f"[gunicorn] Worker interrupted (pid {worker.pid})", flush=True)

def worker_exit(server, worker):
    print(f"[gunicorn] Worker exited (pid {worker.pid})", flush=True)

def child_exit(server, worker):
    print(f"[gunicorn] Child exited (pid {worker.pid})", flush=True)
