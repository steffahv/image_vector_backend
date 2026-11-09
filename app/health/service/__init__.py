"""Health logic. Kept separate from the router so it can grow (e.g. a database ping).

One file per topic, imported here.
"""

from app.health.service.status import get_health_status

__all__ = ["get_health_status"]
