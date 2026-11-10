"""Add billing tables, row isolation and credit functions (VEC-47).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-10 08:43:32.171566
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AGENT = "vectoredit_agent"
PLATFORM = "vectoredit_platform"
ACCOUNT_TABLES = ("subscriptions", "credit_balances", "credit_movements", "credit_reservations")
RESERVE = "billing.reserve_credits(uuid, bigint, timestamptz)"
SETTLE = "billing.settle_credits(uuid, bigint)"


def _protect_billing() -> None:
    rule = "account_id = platform.current_account_id()"
    for table in ACCOUNT_TABLES:
        op.execute(f"ALTER TABLE billing.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE billing.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY account_isolation ON billing.{table} USING ({rule}) WITH CHECK ({rule})"
        )

    # A change to a plan creates a new entitlement version. Movements are append-only.
    op.execute(
        f"REVOKE UPDATE, DELETE ON billing.plan_entitlements, billing.credit_movements"
        f" FROM {PLATFORM}"
    )
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON billing.credit_reservations FROM {PLATFORM}")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON billing.credit_balances FROM {PLATFORM}")
    op.execute(f"GRANT INSERT (account_id, balance) ON billing.credit_balances TO {PLATFORM}")
    op.execute(f"GRANT UPDATE (balance, updated_at) ON billing.credit_balances TO {PLATFORM}")
    # Only the settlement function can post a debit against a reservation.
    op.execute(
        "CREATE POLICY platform_movements ON billing.credit_movements AS RESTRICTIVE"
        f" FOR INSERT TO {PLATFORM} WITH CHECK (reason <> 'agent_usage')"
    )


def _create_credit_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION billing.reserve_credits(
            p_run_id uuid, p_amount bigint, p_expires_at timestamptz
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            v_account uuid := platform.current_account_id();
            v_run_status text;
            v_available bigint;
            v_reservation_id uuid;
            v_amount bigint;
        BEGIN
            IF v_account IS NULL THEN
                RAISE EXCEPTION 'credit operation requires an account' USING ERRCODE = 'VC001';
            END IF;
            IF p_amount IS NULL OR p_amount <= 0 OR p_expires_at IS NULL
                OR NOT isfinite(p_expires_at) THEN
                RAISE EXCEPTION 'invalid credit reservation' USING ERRCODE = 'VC004';
            END IF;

            -- Keep the run active while opening a new reservation.
            SELECT status INTO v_run_status FROM agent.runs
            WHERE id = p_run_id AND account_id = v_account FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'credit run is unavailable' USING ERRCODE = 'VC002';
            END IF;

            -- Serialize decisions for all runs drawing from this wallet.
            SELECT balance - reserved INTO v_available FROM billing.credit_balances
            WHERE account_id = v_account FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'insufficient available credits' USING ERRCODE = 'VC003';
            END IF;

            SELECT id, amount INTO v_reservation_id, v_amount FROM billing.credit_reservations
            WHERE run_id = p_run_id AND account_id = v_account;
            IF FOUND THEN
                IF v_amount <> p_amount THEN
                    RAISE EXCEPTION 'conflicting credit reservation retry' USING ERRCODE = 'VC005';
                END IF;
                RETURN v_reservation_id;
            END IF;

            IF v_run_status NOT IN ('pending', 'running') THEN
                RAISE EXCEPTION 'credit run is unavailable' USING ERRCODE = 'VC002';
            END IF;
            IF p_expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'invalid credit reservation expiry' USING ERRCODE = 'VC004';
            END IF;
            IF p_amount > v_available THEN
                RAISE EXCEPTION 'insufficient available credits' USING ERRCODE = 'VC003';
            END IF;

            INSERT INTO billing.credit_reservations (account_id, run_id, amount, status, expires_at)
            VALUES (v_account, p_run_id, p_amount, 'reserved', p_expires_at)
            RETURNING id INTO v_reservation_id;
            UPDATE billing.credit_balances
            SET reserved = reserved + p_amount, updated_at = now()
            WHERE account_id = v_account;
            RETURN v_reservation_id;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION billing.settle_credits(p_reservation_id uuid, p_used bigint) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            v_account uuid := platform.current_account_id();
            v_reservation billing.credit_reservations%ROWTYPE;
            v_prior_debit bigint;
        BEGIN
            IF v_account IS NULL THEN
                RAISE EXCEPTION 'credit operation requires an account' USING ERRCODE = 'VC001';
            END IF;

            SELECT * INTO v_reservation FROM billing.credit_reservations
            WHERE id = p_reservation_id AND account_id = v_account FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'credit reservation is unavailable' USING ERRCODE = 'VC002';
            END IF;
            IF p_used IS NULL OR p_used < 0 OR p_used > v_reservation.amount THEN
                RAISE EXCEPTION 'invalid credit usage' USING ERRCODE = 'VC004';
            END IF;

            IF v_reservation.status <> 'reserved' THEN
                IF v_reservation.status = 'released' AND p_used = 0 THEN
                    RETURN;
                END IF;
                IF v_reservation.status = 'settled' AND p_used > 0 THEN
                    SELECT amount INTO v_prior_debit FROM billing.credit_movements
                    WHERE account_id = v_account AND reason = 'agent_usage'
                        AND reference = p_reservation_id::text;
                    IF v_prior_debit = -p_used THEN
                        RETURN;
                    END IF;
                END IF;
                RAISE EXCEPTION 'conflicting credit settlement retry' USING ERRCODE = 'VC005';
            END IF;

            UPDATE billing.credit_balances
            SET balance = balance - p_used, reserved = reserved - v_reservation.amount,
                updated_at = now()
            WHERE account_id = v_account AND reserved >= v_reservation.amount;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'credit balance does not match reservation' USING ERRCODE = 'VC006';
            END IF;

            IF p_used > 0 THEN
                INSERT INTO billing.credit_movements (account_id, amount, reason, reference)
                VALUES (v_account, -p_used, 'agent_usage', p_reservation_id::text);
            END IF;

            UPDATE billing.credit_reservations
            SET status = CASE WHEN p_used = 0 THEN 'released' ELSE 'settled' END,
                updated_at = now()
            WHERE id = p_reservation_id AND account_id = v_account;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA billing TO {AGENT}")
    for signature in (RESERVE, SETTLE):
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {AGENT}")


def upgrade() -> None:
    _create_tables()
    _protect_billing()
    _create_credit_functions()


def _create_tables() -> None:
    op.create_table(
        "credit_packs",
        sa.Column("credits", sa.BigInteger(), nullable=False),
        sa.Column("price_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("gateway", sa.Text(), nullable=False),
        sa.Column("gateway_product_id", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("credits > 0", name=op.f("ck_credit_packs_credits_positive")),
        sa.CheckConstraint(
            "price_cents >= 0", name=op.f("ck_credit_packs_price_cents_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_packs")),
        sa.UniqueConstraint(
            "gateway", "gateway_product_id", name=op.f("uq_credit_packs_gateway_gateway_product_id")
        ),
        schema="billing",
    )
    op.create_table(
        "gateway_events",
        sa.Column("gateway", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processed",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gateway_events")),
        sa.UniqueConstraint("gateway", "event_id", name=op.f("uq_gateway_events_gateway_event_id")),
        schema="billing",
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        schema="billing",
    )
    op.create_table(
        "plan_entitlements",
        sa.Column("plan_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "coalesce(jsonb_typeof(limits) = 'object'"
            " AND jsonb_typeof(limits->'max_versions') = 'number'"
            " AND (limits->>'max_versions') ~ '^[1-9][0-9]*$'"
            " AND (limits->'max_versions') <= '2147483647'::jsonb, false)",
            name=op.f("ck_plan_entitlements_limits_contract"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_plan_entitlements_version_positive")),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["billing.plans.id"], name=op.f("fk_plan_entitlements_plan_id_plans")
        ),
        sa.PrimaryKeyConstraint("plan_id", "version", name=op.f("pk_plan_entitlements")),
        schema="billing",
    )
    op.create_table(
        "credit_balances",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("reserved", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reserved >= 0 AND reserved <= balance", name=op.f("ck_credit_balances_within_balance")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["platform.accounts.id"],
            name=op.f("fk_credit_balances_account_id_accounts"),
        ),
        sa.PrimaryKeyConstraint("account_id", name=op.f("pk_credit_balances")),
        schema="billing",
    )
    op.create_table(
        "credit_movements",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount <> 0", name=op.f("ck_credit_movements_amount_non_zero")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["platform.accounts.id"],
            name=op.f("fk_credit_movements_account_id_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_movements")),
        sa.UniqueConstraint(
            "account_id",
            "reason",
            "reference",
            name=op.f("uq_credit_movements_account_id_reason_reference"),
        ),
        schema="billing",
    )
    op.create_index(
        op.f("ix_credit_movements_account_id_created_at"),
        "credit_movements",
        ["account_id", "created_at"],
        unique=False,
        schema="billing",
    )
    op.create_table(
        "subscriptions",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Text(), nullable=False),
        sa.Column("entitlement_version", sa.Integer(), nullable=False),
        sa.Column("gateway", sa.Text(), nullable=False),
        sa.Column("gateway_subscription_id", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "trialing",
                "past_due",
                "cancelled",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("period_end > period_start", name=op.f("ck_subscriptions_period_order")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["platform.accounts.id"],
            name=op.f("fk_subscriptions_account_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["plan_id", "entitlement_version"],
            ["billing.plan_entitlements.plan_id", "billing.plan_entitlements.version"],
            name=op.f("fk_subscriptions_plan_id_entitlement_version_plan_entitlements"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint(
            "gateway",
            "gateway_subscription_id",
            name=op.f("uq_subscriptions_gateway_gateway_subscription_id"),
        ),
        schema="billing",
    )
    op.create_index(
        op.f("ix_subscriptions_account_id_status"),
        "subscriptions",
        ["account_id", "status"],
        unique=False,
        schema="billing",
    )
    op.create_index(
        op.f("ix_subscriptions_plan_id_entitlement_version"),
        "subscriptions",
        ["plan_id", "entitlement_version"],
        unique=False,
        schema="billing",
    )
    op.create_table(
        "credit_reservations",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "reserved",
                "settled",
                "released",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_credit_reservations_amount_positive")),
        sa.ForeignKeyConstraint(
            ["account_id", "run_id"],
            ["agent.runs.account_id", "agent.runs.id"],
            name=op.f("fk_credit_reservations_account_id_run_id_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["platform.accounts.id"],
            name=op.f("fk_credit_reservations_account_id_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_reservations")),
        sa.UniqueConstraint("run_id", name=op.f("uq_credit_reservations_run_id")),
        schema="billing",
    )
    op.create_index(
        op.f("ix_credit_reservations_account_id"),
        "credit_reservations",
        ["account_id"],
        unique=False,
        schema="billing",
    )
    op.create_index(
        op.f("ix_credit_reservations_status_expires_at"),
        "credit_reservations",
        ["status", "expires_at"],
        unique=False,
        schema="billing",
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SETTLE}")
    op.execute(f"DROP FUNCTION {RESERVE}")
    op.execute(f"REVOKE USAGE ON SCHEMA billing FROM {AGENT}")
    op.drop_index(
        op.f("ix_credit_reservations_status_expires_at"),
        table_name="credit_reservations",
        schema="billing",
    )
    op.drop_index(
        op.f("ix_credit_reservations_account_id"),
        table_name="credit_reservations",
        schema="billing",
    )
    op.drop_table("credit_reservations", schema="billing")
    op.drop_index(
        op.f("ix_subscriptions_plan_id_entitlement_version"),
        table_name="subscriptions",
        schema="billing",
    )
    op.drop_index(
        op.f("ix_subscriptions_account_id_status"), table_name="subscriptions", schema="billing"
    )
    op.drop_table("subscriptions", schema="billing")
    op.drop_index(
        op.f("ix_credit_movements_account_id_created_at"),
        table_name="credit_movements",
        schema="billing",
    )
    op.drop_table("credit_movements", schema="billing")
    op.drop_table("credit_balances", schema="billing")
    op.drop_table("plan_entitlements", schema="billing")
    op.drop_table("plans", schema="billing")
    op.drop_table("gateway_events", schema="billing")
    op.drop_table("credit_packs", schema="billing")
