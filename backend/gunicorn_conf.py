"""Gunicorn configuration for Render deployment.

Key settings:
- preload_app=True loads app in master before forking workers (critical for Render).
- graceful_timeout: Low value so old workers release port quickly during deploys.
- control_socket_disable: Gunicorn 25 added a control socket that can conflict
  with Render's process management — stale socket files between deploys prevent
  worker forking. Disabled since we don't use the control socket features.
- Lifecycle hooks: Log worker fork/exit/abort for debugging deploy issues.
"""

import os
import sys

# --- Server socket ---
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

# --- Timeouts ---
timeout = 120           # Max time for a request to complete
graceful_timeout = 10   # Max time for old workers to finish during shutdown
keepalive = 5           # Keep connections open for Render's load balancer

# --- Workers ---
workers = int(os.environ.get("WEB_CONCURRENCY", 1))

# --- App loading ---
# preload_app=True loads app in master before forking workers.
# Combined with deferred DB init (first real request triggers init_db),
# this is safe: the master loads Python code only, no DB connections.
preload_app = True

# --- Disable control socket (gunicorn 25+) ---
# The control socket file persists between Render deploys and can prevent
# workers from spawning when a stale socket exists from the old process.
control_socket_disable = True

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
