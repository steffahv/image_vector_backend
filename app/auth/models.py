"""SQLAlchemy tables for auth, in the `auth` PostgreSQL schema.

What goes here: user, account, session and verification tables.
Their final columns depend on the identity library that is chosen (VEC-40).
The product account lives in documents (`plataforma` schema), not here.
"""
