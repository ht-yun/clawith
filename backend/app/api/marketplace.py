"""Marketplace API routes for agent discovery and access requests."""

import uuid
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.models.agent import Agent, AgentPermission
from app.models.user import User
from app.models.audit import ApprovalRequest, AuditLog
from app.schemas.schemas import AgentOut, ApprovalRequestOut

router = APIRouter(prefix="/marketplace", tags=["marketplace"])

@router.get("/agents", response_model=list[AgentOut])
async def list_marketplace_agents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List agents discoverable in the marketplace for the current tenant.
    
    Agents are discoverable if they have at least one permission with scope_type='company'
    in the same tenant.
    """
    # Find agents in the same tenant that have 'company' scope permission
    # and the user doesn't already have access to.
    
    # 1. Get agents with company scope in the same tenant
    company_shared_stmt = (
        select(Agent.id)
        .join(AgentPermission, Agent.id == AgentPermission.agent_id)
        .where(
            Agent.tenant_id == current_user.tenant_id,
            AgentPermission.scope_type == "company"
        )
    )
    
    # 2. Get agents that are NOT private user-only (optional, but good for discovery)
    # For now, let's just show all agents in the tenant that aren't the user's own
    # and aren't already shared with the user.
    
    stmt = (
        select(Agent)
        .where(
            Agent.tenant_id == current_user.tenant_id,
            Agent.creator_id != current_user.id
        )
        .order_by(Agent.name)
    )
    
    result = await db.execute(stmt)
    agents = result.scalars().all()
    
    # Filter out agents user already has access to
    visible_stmt = select(AgentPermission.agent_id).where(
        or_(
            AgentPermission.scope_type == "company",
            and_(
                AgentPermission.scope_type == "user",
                AgentPermission.scope_id == current_user.id
            )
        )
    )
    res_perm = await db.execute(visible_stmt)
    accessible_ids = {row[0] for row in res_perm.all()}
    
    marketplace_agents = [a for a in agents if a.id not in accessible_ids]
    
    return [AgentOut.model_validate(a) for a in marketplace_agents]

@router.post("/agents/{agent_id}/request", status_code=status.HTTP_201_CREATED)
async def request_agent_access(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request access to an agent."""
    # 1. Check if agent exists
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent or agent.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    if agent.creator_id == current_user.id:
        raise HTTPException(status_code=400, detail="You are the creator of this agent")

    # 2. Check if already have access
    perm_result = await db.execute(
        select(AgentPermission).where(
            AgentPermission.agent_id == agent_id,
            or_(
                AgentPermission.scope_type == "company",
                and_(
                    AgentPermission.scope_type == "user",
                    AgentPermission.scope_id == current_user.id
                )
            )
        )
    )
    if perm_result.scalars().first():
        raise HTTPException(status_code=400, detail="You already have access to this agent")

    # 3. Check for pending requests
    pending_result = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.agent_id == agent_id,
            ApprovalRequest.status == "pending",
            ApprovalRequest.action_type == "agent_access",
            ApprovalRequest.details["requested_by"].as_string() == str(current_user.id)
        )
    )
    if pending_result.scalars().first():
        raise HTTPException(status_code=400, detail="Access request already pending")

    # 4. Create approval request
    approval = ApprovalRequest(
        agent_id=agent_id,
        action_type="agent_access",
        details={
            "requested_by": str(current_user.id),
            "requested_by_name": current_user.display_name,
            "reason": "Marketplace access request"
        }
    )
    db.add(approval)
    
    # 5. Notify creator
    from app.services.notification_service import send_notification
    await send_notification(
        db,
        user_id=agent.creator_id,
        type="approval_pending",
        title=f"[{agent.name}] 访问申请: {current_user.display_name}",
        body=f"用户 {current_user.display_name} 申请使用您的智能体 {agent.name}。",
        link=f"/agents/{agent.id}#approvals",
        ref_id=approval.id,
    )
    
    await db.commit()
    return {"message": "Access request submitted", "approval_id": str(approval.id)}
