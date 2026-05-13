"""OpenCode Agent Node — per-user node instances of an OpenCode agent."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentNode(Base):
    """User-owned OpenCode node instance.

    A single Agent (agent_type='opencode') can have multiple AgentNodes,
    each owned by a different user with its own API key. This enables
    unified management of multiple users' OpenCode deployments under
    one agent template.
    """

    __tablename__ = "agent_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id")
    )
    node_name: Mapped[str] = mapped_column(String(200), default="")
    api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="idle", nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[str | None] = mapped_column(String(50))
    config: Mapped[dict] = mapped_column(JSON, default={})

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="nodes", foreign_keys=[agent_id])
    owner: Mapped["User"] = relationship(foreign_keys=[owner_user_id])


# Late imports for relationship resolution
from app.models.agent import Agent  # noqa: E402, F401
from app.models.user import User  # noqa: E402, F401
