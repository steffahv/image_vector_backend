"""SQLAlchemy tables for storage, in the `storage` PostgreSQL schema (VEC-29).

What goes here: stored objects, pending uploads, revision-to-file links and quotas.
See Modelo_relacional_VectorEdit.

How to split: one file per table (e.g. `document.py`) in this folder,
imported here so other code keeps importing from `app.storage.models`.
`app/auth/models/` is an example.
"""
