"""Add agent_nodes table for multi-node OpenCode management.

Revision: add_agent_nodes
Create Date: 2026-05-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "add_agent_nodes"
down_revision = "user_refactor"
branch_labels = None
depends_on = None


def upgrade():
    # ── Create agent_nodes table ──
    op.create_table(
        "agent_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("node_name", sa.String(200), server_default="", nullable=False),
        sa.Column("api_key_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), server_default="idle", nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.String(50), nullable=True),
        sa.Column("config", postgresql.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_nodes_agent_id", "agent_nodes", ["agent_id"])
    op.create_index("ix_agent_nodes_tenant_id", "agent_nodes", ["tenant_id"])
    op.create_index("ix_agent_nodes_api_key_hash", "agent_nodes", ["api_key_hash"])

    # ── Add agent_node_id columns to gateway_messages ──
    op.add_column("gateway_messages", sa.Column("agent_node_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("gateway_messages", sa.Column("sender_agent_node_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_gateway_messages_agent_node_id", "gateway_messages", "agent_nodes", ["agent_node_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_gateway_messages_sender_agent_node_id", "gateway_messages", "agent_nodes", ["sender_agent_node_id"], ["id"]
    )

    # ── Migrate existing opencode agents: create a default AgentNode for each ──
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, creator_id, tenant_id, api_key_hash FROM agents "
            "WHERE agent_type = 'opencode' AND api_key_hash IS NOT NULL"
        )
    ).fetchall()

    import uuid as _uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    for row in rows:
        node_id = _uuid.uuid4()
        conn.execute(
            sa.text(
                "INSERT INTO agent_nodes (id, agent_id, owner_user_id, tenant_id, node_name, api_key_hash, "
                "status, created_at, updated_at) "
                "VALUES (:id, :agent_id, :owner_user_id, :tenant_id, :node_name, :api_key_hash, "
                ":status, :created_at, :updated_at)"
            ),
            {
                "id": node_id,
                "agent_id": row.id,
                "owner_user_id": row.creator_id,
                "tenant_id": row.tenant_id,
                "node_name": "Default",
                "api_key_hash": row.api_key_hash,
                "status": "idle",
                "created_at": now,
                "updated_at": now,
            },
        )

    if rows:
        print(f"[migration] Created default AgentNode for {len(rows)} existing opencode agents")


def downgrade():
    op.drop_constraint("fk_gateway_messages_sender_agent_node_id", "gateway_messages", type_="foreignkey")
    op.drop_constraint("fk_gateway_messages_agent_node_id", "gateway_messages", type_="foreignkey")
    op.drop_column("gateway_messages", "sender_agent_node_id")
    op.drop_column("gateway_messages", "agent_node_id")
    op.drop_index("ix_agent_nodes_api_key_hash", table_name="agent_nodes")
    op.drop_index("ix_agent_nodes_tenant_id", table_name="agent_nodes")
    op.drop_index("ix_agent_nodes_agent_id", table_name="agent_nodes")
    op.drop_table("agent_nodes")
