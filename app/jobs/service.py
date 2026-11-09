"""Scheduled maintenance jobs (VEC-36).

What goes here:
- Empty old trash, prune versions beyond the plan limit, delete unused files
  and release quota from saves that never finished.
- Jobs are claimed in batches with a lease, retried a limited number of times
  and must be idempotent (running twice gives the same result).

No HTTP routes: runs as a separate process of the same app. It calls the
documents and storage services instead of reading their tables. No Redis or queues.
"""
