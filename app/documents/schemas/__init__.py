"""Pydantic request and response models for the documents API.

What goes here: document, revision, version, folder and share bodies and responses,
including the save request (base revision + idempotency key) and the 409 conflict response.

How to split: one file per topic (e.g. `document.py`) in this folder,
imported here so other code keeps importing from `app.documents.schemas`.
`app/auth/models/` is an example.
"""
