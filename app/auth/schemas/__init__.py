"""Pydantic request and response models for the auth API.

What goes here: sign-up/sign-in bodies, session and current-user responses.
Never return password hashes or tokens other than the session cookie.

How to split: one file per topic (e.g. `document.py`) in this folder,
imported here so other code keeps importing from `app.auth.schemas`.
`app/auth/models/` is an example.
"""
