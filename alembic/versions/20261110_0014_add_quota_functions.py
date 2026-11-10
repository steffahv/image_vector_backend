"""Add the quota functions, the only way the agent reserves, settles and releases quotas (VEC-30).

The agent has no write privilege on agent.period_quotas or agent.reservations (migration 0013).
These functions run as their owner (SECURITY DEFINER) to write them, and check balance and
limits in the same statement that changes them:

- reserve_quota(run_id, resource, amount, expires_at): holds `amount` of the account's current
  quota for an active run, or fails if the quota cannot cover it. Returns the reservation id.
- settle_reservation(reservation_id, used): moves `used` (at most what was reserved) to consumed
  and gives back the rest.
- release_reservation(reservation_id): gives back everything that was reserved.

All three are idempotent: retrying a call that already took effect changes nothing, so a retried
request never charges twice. They act only for the session's account: the tables use FORCE ROW
LEVEL SECURITY, so the policies still apply to the owner and the functions cannot see another
account's rows, and they refuse to run with no account set.

The quota row is locked (FOR UPDATE) before checking it, so two runs reserving at once are
checked one after the other and cannot together pass the quota.

Errors use their own SQLSTATE, so the agent service can tell them apart without reading the text:
VQ001 no account set, VQ002 run not found or not active, VQ003 no quota in force for the resource,
VQ004 quota exceeded, VQ005 reservation not found or in a state that does not allow the call.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out instead of imported: a migration must not change if the code changes later.
AGENT = "vectoredit_agent"

# Shared by the three functions: fail before touching anything when no account is set.
REQUIRE_ACCOUNT = """
    account := platform.current_account_id();
    IF account IS NULL THEN
        RAISE EXCEPTION 'no account set for this transaction' USING ERRCODE = 'VQ001';
    END IF;
"""

RESERVE_QUOTA = f"""
CREATE FUNCTION agent.reserve_quota(
    run_id uuid, resource text, amount bigint, expires_at timestamptz
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    account uuid;
    quota agent.period_quotas%ROWTYPE;
    existing agent.reservations%ROWTYPE;
    reservation_id uuid;
BEGIN
    {REQUIRE_ACCOUNT}
    IF amount IS NULL OR amount <= 0 THEN
        RAISE EXCEPTION 'amount must be positive' USING ERRCODE = 'check_violation';
    END IF;

    -- RLS hides other accounts' runs, so another account's run is simply not found.
    PERFORM 1 FROM agent.runs r
    WHERE r.id = reserve_quota.run_id AND r.account_id = account
      AND r.status IN ('pending', 'running');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'run not found or not active' USING ERRCODE = 'VQ002';
    END IF;

    -- A retry of the same reservation returns it instead of holding the amount twice.
    SELECT * INTO existing FROM agent.reservations res
    WHERE res.run_id = reserve_quota.run_id AND res.resource = reserve_quota.resource;
    IF FOUND THEN
        IF existing.amount <> reserve_quota.amount OR existing.status <> 'reserved' THEN
            RAISE EXCEPTION 'run already has a different reservation for this resource'
                USING ERRCODE = 'VQ005';
        END IF;
        RETURN existing.id;
    END IF;

    -- Locked until the transaction ends: concurrent reservations wait and then see this one.
    SELECT * INTO quota FROM agent.period_quotas q
    WHERE q.account_id = account AND q.resource = reserve_quota.resource
      AND q.starts_at <= pg_catalog.now() AND q.ends_at > pg_catalog.now()
    ORDER BY q.starts_at DESC
    LIMIT 1
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no quota in force for resource %', reserve_quota.resource
            USING ERRCODE = 'VQ003';
    END IF;
    IF quota.reserved + quota.consumed + reserve_quota.amount > quota.allocated THEN
        RAISE EXCEPTION 'quota exceeded for resource %', reserve_quota.resource
            USING ERRCODE = 'VQ004';
    END IF;

    UPDATE agent.period_quotas q
    SET reserved = q.reserved + reserve_quota.amount, updated_at = pg_catalog.now()
    WHERE q.account_id = quota.account_id AND q.period_id = quota.period_id
      AND q.resource = quota.resource;
    INSERT INTO agent.reservations
        (run_id, account_id, period_id, resource, amount, status, expires_at)
    VALUES (reserve_quota.run_id, account, quota.period_id, quota.resource,
            reserve_quota.amount, 'reserved', reserve_quota.expires_at)
    RETURNING id INTO reservation_id;
    RETURN reservation_id;
END
$$
"""

# Locks the reservation and its quota, in that order in both functions, so they never deadlock.
LOCK_RESERVATION = """
    SELECT * INTO reservation FROM agent.reservations res
    WHERE res.id = {name}.reservation_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reservation not found' USING ERRCODE = 'VQ005';
    END IF;
    PERFORM 1 FROM agent.period_quotas q
    WHERE q.account_id = reservation.account_id AND q.period_id = reservation.period_id
      AND q.resource = reservation.resource
    FOR UPDATE;
"""

SETTLE_RESERVATION = f"""
CREATE FUNCTION agent.settle_reservation(reservation_id uuid, used bigint) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    account uuid;
    reservation agent.reservations%ROWTYPE;
BEGIN
    {REQUIRE_ACCOUNT}
    {LOCK_RESERVATION.format(name="settle_reservation")}
    IF reservation.status = 'settled' THEN
        RETURN;  -- already done: a retry changes nothing
    END IF;
    IF reservation.status <> 'reserved' THEN
        RAISE EXCEPTION 'reservation was released and cannot be settled' USING ERRCODE = 'VQ005';
    END IF;
    IF used IS NULL OR used < 0 OR used > reservation.amount THEN
        RAISE EXCEPTION 'used must be between 0 and the reserved amount'
            USING ERRCODE = 'check_violation';
    END IF;

    UPDATE agent.period_quotas q
    SET reserved = q.reserved - reservation.amount,
        consumed = q.consumed + settle_reservation.used,
        updated_at = pg_catalog.now()
    WHERE q.account_id = reservation.account_id AND q.period_id = reservation.period_id
      AND q.resource = reservation.resource;
    UPDATE agent.reservations res
    SET status = 'settled', updated_at = pg_catalog.now()
    WHERE res.id = reservation.id;
END
$$
"""

RELEASE_RESERVATION = f"""
CREATE FUNCTION agent.release_reservation(reservation_id uuid) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    account uuid;
    reservation agent.reservations%ROWTYPE;
BEGIN
    {REQUIRE_ACCOUNT}
    {LOCK_RESERVATION.format(name="release_reservation")}
    IF reservation.status = 'released' THEN
        RETURN;  -- already done: a retry changes nothing
    END IF;
    IF reservation.status <> 'reserved' THEN
        RAISE EXCEPTION 'reservation was settled and cannot be released' USING ERRCODE = 'VQ005';
    END IF;

    UPDATE agent.period_quotas q
    SET reserved = q.reserved - reservation.amount, updated_at = pg_catalog.now()
    WHERE q.account_id = reservation.account_id AND q.period_id = reservation.period_id
      AND q.resource = reservation.resource;
    UPDATE agent.reservations res
    SET status = 'released', updated_at = pg_catalog.now()
    WHERE res.id = reservation.id;
END
$$
"""

SIGNATURES = (
    "agent.reserve_quota(uuid, text, bigint, timestamptz)",
    "agent.settle_reservation(uuid, bigint)",
    "agent.release_reservation(uuid)",
)


def upgrade() -> None:
    for definition in (RESERVE_QUOTA, SETTLE_RESERVATION, RELEASE_RESERVATION):
        op.execute(definition)
    # New functions of the migrator are executable by nobody (migration 0010): only the agent.
    for signature in SIGNATURES:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {AGENT}")


def downgrade() -> None:
    for signature in SIGNATURES:
        op.execute(f"DROP FUNCTION {signature}")
