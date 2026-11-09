"""Business logic for billing (VEC-33, after launch).

What goes here: plans and entitlements, payments, subscriptions and the credit
functions the agent service calls to reserve and settle credits.

How to split: one file per use case (e.g. `save.py`, `open.py`) in this folder,
imported here so other code keeps importing from `app.billing.service`.
`app/auth/models/` is an example.
"""
