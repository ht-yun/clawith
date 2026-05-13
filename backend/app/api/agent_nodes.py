"""Agent Node API — manage multi-user OpenCode node instances.

Permission model:
- Creator + admin: see/delete/regen all nodes
- Any user with agent access: create their own node, see/manage their own nodes
"""

import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import check_agent_access, is_agent_creator
from app.core.security import get_current_user
from app.database import get_db
from app.models.agent import Agent
from app.models.agent_node import AgentNode
from app.models.user import User
from app.schemas.schemas import AgentNodeCreate, AgentNodeOut

router = APIRouter(prefix="/agents", tags=["agent-nodes"])


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _is_node_owner(user: User, node: AgentNode) -> bool:
    return node.owner_user_id == user.id


def _can_manage_all(user: User, agent: Agent) -> bool:
    """Creator or admin can manage all nodes of this agent."""
    return is_agent_creator(user, agent) or user.role in ("platform_admin", "org_admin")


async def _get_agent_node_or_404(db: AsyncSession, node_id: uuid.UUID, agent_id: uuid.UUID) -> AgentNode:
    result = await db.execute(
        select(AgentNode).where(
            AgentNode.id == node_id,
            AgentNode.agent_id == agent_id,
        )
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Agent node not found")
    return node


async def _node_to_out(db: AsyncSession, node: AgentNode) -> AgentNodeOut:
    owner_username = None
    if node.owner_user_id:
        r = await db.execute(select(User).where(User.id == node.owner_user_id))
        user = r.scalar_one_or_none()
        owner_username = user.username if user else None

    return AgentNodeOut(
        id=node.id,
        agent_id=node.agent_id,
        owner_user_id=node.owner_user_id,
        owner_username=owner_username,
        node_name=node.node_name,
        status=node.status or "idle",
        last_seen=node.last_seen,
        version=node.version,
        created_at=node.created_at,
        updated_at=node.updated_at,
        api_key=None,
    )


# ─── List nodes ──────────────────────────────────────────

@router.get("/{agent_id}/nodes", response_model=list[AgentNodeOut])
async def list_nodes(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List OpenCode nodes for an agent.

    - Creator/admin: see all nodes
    - Other users: see only their own nodes
    """
    agent, _access = await check_agent_access(db, current_user, agent_id)

    query = select(AgentNode).where(AgentNode.agent_id == agent.id)
    if not _can_manage_all(current_user, agent):
        query = query.where(AgentNode.owner_user_id == current_user.id)

    result = await db.execute(query.order_by(AgentNode.created_at.desc()))
    nodes = result.scalars().all()
    return [await _node_to_out(db, n) for n in nodes]


# ─── Create node ─────────────────────────────────────────

@router.post("/{agent_id}/nodes", response_model=AgentNodeOut)
async def create_node(
    agent_id: uuid.UUID,
    body: AgentNodeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new OpenCode node for the current user on this agent.

    Any user with access to the agent can create their own node.
    """
    agent, _access = await check_agent_access(db, current_user, agent_id)
    if getattr(agent, "agent_type", "native") != "opencode":
        raise HTTPException(status_code=400, detail="Nodes are only available for OpenCode agents")

    # Check: maximum 3 nodes per user per agent
    existing = await db.execute(
        select(AgentNode).where(
            AgentNode.agent_id == agent.id,
            AgentNode.owner_user_id == current_user.id,
        )
    )
    existing_nodes = existing.scalars().all()
    if len(existing_nodes) >= 3:
        raise HTTPException(
            status_code=409,
            detail="Maximum 3 nodes per agent reached. Delete an existing node first.",
        )

    raw_key = f"code-{secrets.token_urlsafe(32)}"
    node = AgentNode(
        agent_id=agent.id,
        owner_user_id=current_user.id,
        tenant_id=agent.tenant_id,
        node_name=body.node_name or f"Node-{secrets.token_hex(4)}",
        api_key_hash=_hash_key(raw_key),
        status="idle",
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)

    out = await _node_to_out(db, node)
    out.api_key = raw_key
    return out


# ─── Delete node ─────────────────────────────────────────

@router.delete("/{agent_id}/nodes/{node_id}")
async def delete_node(
    agent_id: uuid.UUID,
    node_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a node (revoke its API key).

    - Creator/admin: can delete any node
    - Node owner: can delete their own node
    """
    agent, _access = await check_agent_access(db, current_user, agent_id)
    node = await _get_agent_node_or_404(db, node_id, agent.id)

    if not _can_manage_all(current_user, agent) and not _is_node_owner(current_user, node):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own node")

    await db.delete(node)
    await db.commit()
    return {"status": "ok", "message": "Node deleted successfully"}


# ─── Regenerate API key ──────────────────────────────────

@router.post("/{agent_id}/nodes/{node_id}/regenerate-key", response_model=AgentNodeOut)
async def regenerate_node_key(
    agent_id: uuid.UUID,
    node_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate API key for a specific node. Old key is immediately invalidated.

    - Creator/admin: can regenerate any node's key
    - Node owner: can regenerate their own node's key
    """
    agent, _access = await check_agent_access(db, current_user, agent_id)
    node = await _get_agent_node_or_404(db, node_id, agent.id)

    if not _can_manage_all(current_user, agent) and not _is_node_owner(current_user, node):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only regenerate your own node's key")

    raw_key = f"code-{secrets.token_urlsafe(32)}"
    node.api_key_hash = _hash_key(raw_key)
    await db.commit()
    await db.refresh(node)

    out = await _node_to_out(db, node)
    out.api_key = raw_key
    return out


# ─── Admin: all nodes overview ───────────────────────────

admin_router = APIRouter(prefix="/admin", tags=["admin-nodes"])


@admin_router.get("/nodes", response_model=list[AgentNodeOut])
async def admin_list_all_nodes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin endpoint: list all agent nodes across the platform or tenant."""
    if current_user.role not in ("platform_admin", "org_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")

    query = select(AgentNode).order_by(AgentNode.last_seen.desc().nulls_last())
    result = await db.execute(query)
    nodes = result.scalars().all()
    return [await _node_to_out(db, n) for n in nodes]
