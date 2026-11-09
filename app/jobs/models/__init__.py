"""SQLAlchemy tables for operations, in the `operations` PostgreSQL schema (VEC-41).

What goes here: jobs, exports, audit log, object copies and backup runs.
See Modelo_relacional_VectorEdit §VIII.

How to split: one file per table (e.g. `document.py`) in this folder,
imported here so other code keeps importing from `app.jobs.models`.
`app/auth/models/` is an example.
"""
