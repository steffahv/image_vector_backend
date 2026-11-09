"""Business logic for auth.

What goes here:
- Creating users, verifying email, Google sign-in and creating/closing sessions.
- `get_current_user`, the dependency other modules use to know who is calling.

Other modules use auth only through this file, never by reading its tables.
The identity library is still pending (see VEC-40).

How to split: one file per use case (e.g. `save.py`, `open.py`) in this folder,
imported here so other code keeps importing from `app.auth.service`.
`app/auth/models/` is an example.
"""
