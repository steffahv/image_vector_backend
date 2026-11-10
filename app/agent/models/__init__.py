"""SQLAlchemy tables for the agent, in the `agent` PostgreSQL schema (VEC-41).

One file per table. See Modelo_relacional_VectorEdit §VII and docs/base-de-datos.md.

- conversation.py: `conversations` (Conversation), a chat of an account with the agent.
- message.py: `messages` (Message), the ordered messages of a conversation.
- run.py: `runs` (Run), one turn of the agent on a document.
- pending_call.py: `pending_calls` (PendingCall), tool calls waiting for the editor.
- period_quota.py: `period_quotas` (PeriodQuota), what an account may use per period.
- reservation.py: `reservations` (Reservation), quota held by a run.
- rate.py: `rates` (Rate), provider prices; global, no account data.
- usage.py: `usage` (Usage), usage events and their estimated cost.

The agent service (TypeScript) writes these tables with its own database role.
This repo only defines them so Alembic stays the single migrator. No router or service here.

Import every table here: Alembic and other modules import from `app.agent.models`.
"""

from app.agent.models.conversation import Conversation
from app.agent.models.message import Message, MessageRole
from app.agent.models.pending_call import PendingCall, PendingCallStatus
from app.agent.models.period_quota import PeriodQuota
from app.agent.models.rate import Rate
from app.agent.models.reservation import Reservation, ReservationStatus
from app.agent.models.run import Run, RunStatus
from app.agent.models.usage import Usage, UsageResult

__all__ = [
    "Conversation",
    "Message",
    "MessageRole",
    "PendingCall",
    "PendingCallStatus",
    "PeriodQuota",
    "Rate",
    "Reservation",
    "ReservationStatus",
    "Run",
    "RunStatus",
    "Usage",
    "UsageResult",
]
