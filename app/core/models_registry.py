"""Imports every module's models so Alembic sees all tables.

What goes here: one import per module that has a models.py.
Add the import when you create a new module; otherwise
`alembic revision --autogenerate` will not detect its tables.
"""

from app.auth import models as auth_models  # noqa: F401
from app.billing import models as billing_models  # noqa: F401
from app.documents import models as documents_models  # noqa: F401
from app.storage import models as storage_models  # noqa: F401
