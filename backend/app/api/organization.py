"""Organization management API routes (users only)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_admin, get_current_user
from app.database import get_db
from app.models.org import OrgDepartment, OrgMember
from app.models.user import User
from app.schemas.schemas import (
    UserOut, UserUpdate,
    OrgDepartmentCreate, OrgDepartmentUpdate, OrgDepartmentOut,
    OrgMemberCreate, OrgMemberUpdate, OrgMemberOut
)

from sqlalchemy.orm import selectinload

router = APIRouter(prefix="/org", tags=["organization"])


# ─── Users Management ──────────────────────────────────

@router.get("/users", response_model=list[UserOut])
async def list_users(
    tenant_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List users, optionally filtered by tenant."""
    query = (
        select(User)
        .options(selectinload(User.identity))
        .where(User.is_active == True)
    )

    target_tenant_id = current_user.tenant_id
    if current_user.role in ("platform_admin", "org_admin") and tenant_id:
        target_tenant_id = tenant_id
    if target_tenant_id:
        query = query.where(User.tenant_id == target_tenant_id)

    query = query.order_by(User.display_name)
    result = await db.execute(query)
    return [UserOut.model_validate(u) for u in result.scalars().all()]


@router.patch("/users/{user_id}", response_model=UserOut)
async def admin_update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin update user profile."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.identity))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)

    # Validate email uniqueness within tenant if changing
    if "email" in update_data and update_data["email"] != user.email:
        existing = await db.execute(
            select(User)
            .join(Identity, User.identity_id == Identity.id)
            .where(
                Identity.email == update_data["email"],
                User.tenant_id == user.tenant_id,
                User.id != user.id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")

    # Validate mobile uniqueness within tenant if changing
    if "primary_mobile" in update_data and update_data["primary_mobile"] != user.primary_mobile:
        existing = await db.execute(
            select(User)
            .join(Identity, User.identity_id == Identity.id)
            .where(
                Identity.phone == update_data["primary_mobile"],
                User.tenant_id == user.tenant_id,
                User.id != user.id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Mobile already registered")

    for field, value in update_data.items():
        setattr(user, field, value)
    await db.flush()

    # Sync email/phone to OrgMember if changed
    if "email" in update_data or "primary_mobile" in update_data:
        from app.services.registration_service import registration_service
        await registration_service.sync_org_member_contact_from_user(
            db,
            user,
            sync_email="email" in update_data,
            sync_phone="primary_mobile" in update_data,
        )

    return UserOut.model_validate(user)


# ─── Departments Management ───────────────────────────

@router.get("/departments", response_model=list[OrgDepartmentOut])
async def list_departments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all departments in the current tenant."""
    result = await db.execute(
        select(OrgDepartment)
        .where(OrgDepartment.tenant_id == current_user.tenant_id)
        .order_by(OrgDepartment.path)
    )
    return [OrgDepartmentOut.model_validate(d) for d in result.scalars().all()]


@router.post("/departments", response_model=OrgDepartmentOut)
async def create_department(
    data: OrgDepartmentCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new department manually."""
    dept = OrgDepartment(
        name=data.name,
        parent_id=data.parent_id,
        external_id=data.external_id,
        tenant_id=current_user.tenant_id,
    )
    db.add(dept)
    await db.flush()

    # Recompute path (simple version: parent_path / id)
    if dept.parent_id:
        parent_result = await db.execute(select(OrgDepartment).where(OrgDepartment.id == dept.parent_id))
        parent = parent_result.scalar_one_or_none()
        if parent:
            dept.path = f"{parent.path}/{dept.id}"
        else:
            dept.path = str(dept.id)
    else:
        dept.path = str(dept.id)

    await db.commit()
    await db.refresh(dept)
    return OrgDepartmentOut.model_validate(dept)


@router.patch("/departments/{dept_id}", response_model=OrgDepartmentOut)
async def update_department(
    dept_id: uuid.UUID,
    data: OrgDepartmentUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing department."""
    result = await db.execute(select(OrgDepartment).where(OrgDepartment.id == dept_id))
    dept = result.scalar_one_or_none()
    if not dept or dept.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Department not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(dept, field, value)

    # Note: Moving a department between parents would require recursive path updates.
    # For now, we assume parent_id doesn't change frequently or we'll implement full re-sync logic later.
    if "parent_id" in update_data:
        if dept.parent_id:
            parent_result = await db.execute(select(OrgDepartment).where(OrgDepartment.id == dept.parent_id))
            parent = parent_result.scalar_one_or_none()
            dept.path = f"{parent.path}/{dept.id}" if parent else str(dept.id)
        else:
            dept.path = str(dept.id)

    await db.commit()
    await db.refresh(dept)
    return OrgDepartmentOut.model_validate(dept)


@router.delete("/departments/{dept_id}", status_code=204)
async def delete_department(
    dept_id: uuid.UUID,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a department."""
    result = await db.execute(select(OrgDepartment).where(OrgDepartment.id == dept_id))
    dept = result.scalar_one_or_none()
    if not dept or dept.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Department not found")

    # Check for children
    child_result = await db.execute(select(OrgDepartment).where(OrgDepartment.parent_id == dept_id))
    if child_result.scalars().first():
        raise HTTPException(status_code=400, detail="Cannot delete department with sub-departments")

    # Check for members
    member_result = await db.execute(select(OrgMember).where(OrgMember.department_id == dept_id))
    if member_result.scalars().first():
        raise HTTPException(status_code=400, detail="Cannot delete department with members")

    await db.delete(dept)
    await db.commit()


# ─── Members Management ──────────────────────────────

@router.get("/members", response_model=list[OrgMemberOut])
async def list_members(
    dept_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List org members, optionally filtered by department."""
    query = select(OrgMember).where(OrgMember.tenant_id == current_user.tenant_id)
    if dept_id:
        query = query.where(OrgMember.department_id == dept_id)
    query = query.order_by(OrgMember.name)

    result = await db.execute(query)
    return [OrgMemberOut.model_validate(m) for m in result.scalars().all()]


@router.post("/members", response_model=OrgMemberOut)
async def create_member(
    data: OrgMemberCreate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new org member manually."""
    member = OrgMember(
        name=data.name,
        email=data.email,
        phone=data.phone,
        title=data.title,
        department_id=data.department_id,
        avatar_url=data.avatar_url,
        tenant_id=current_user.tenant_id,
    )

    if member.department_id:
        dept_result = await db.execute(select(OrgDepartment).where(OrgDepartment.id == member.department_id))
        dept = dept_result.scalar_one_or_none()
        if dept:
            member.department_path = dept.path

    db.add(member)
    await db.commit()
    await db.refresh(member)
    return OrgMemberOut.model_validate(member)


@router.patch("/members/{member_id}", response_model=OrgMemberOut)
async def update_member(
    member_id: uuid.UUID,
    data: OrgMemberUpdate,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing org member."""
    result = await db.execute(select(OrgMember).where(OrgMember.id == member_id))
    member = result.scalar_one_or_none()
    if not member or member.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Member not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(member, field, value)

    if "department_id" in update_data:
        if member.department_id:
            dept_result = await db.execute(select(OrgDepartment).where(OrgDepartment.id == member.department_id))
            dept = dept_result.scalar_one_or_none()
            member.department_path = dept.path if dept else ""
        else:
            member.department_path = ""

    await db.commit()
    await db.refresh(member)
    return OrgMemberOut.model_validate(member)


@router.delete("/members/{member_id}", status_code=204)
async def delete_member(
    member_id: uuid.UUID,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an org member."""
    result = await db.execute(select(OrgMember).where(OrgMember.id == member_id))
    member = result.scalar_one_or_none()
    if not member or member.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Member not found")

    await db.delete(member)
    await db.commit()
