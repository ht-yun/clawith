"""Agent training asset APIs."""

import json
import re
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import check_agent_access
from app.core.security import get_current_user
from app.database import get_db
from app.models.agent import Agent
from app.models.audit import ChatMessage
from app.models.chat_session import ChatSession
from app.models.llm import LLMModel
from app.models.training_asset import AgentGoldenQuestion, AgentMemoryPortrait
from app.models.user import User
from app.services.llm import call_llm

router = APIRouter(prefix="/agents", tags=["agent-training"])


MEMORY_PORTRAIT_LIMIT = 20
MEMORY_PORTRAIT_BUDGET = 5000


class MemoryPortraitIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(default="user_preference", max_length=50)
    content: str = Field(min_length=1)
    priority: int = 50
    source_type: str = Field(default="manual", max_length=32)
    source_session_id: uuid.UUID | None = None
    is_active: bool = True


class MemoryPortraitOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    title: str
    category: str
    content: str
    priority: int
    source_type: str
    source_session_id: uuid.UUID | None = None
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_model(cls, item: AgentMemoryPortrait) -> "MemoryPortraitOut":
        return cls(
            id=item.id,
            agent_id=item.agent_id,
            title=item.title,
            category=item.category,
            content=item.content,
            priority=item.priority,
            source_type=item.source_type,
            source_session_id=item.source_session_id,
            is_active=item.is_active,
            created_at=item.created_at.isoformat() if item.created_at else None,
            updated_at=item.updated_at.isoformat() if item.updated_at else None,
        )


class GoldenQuestionIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    scenario: str = Field(default="requirements_unclear", max_length=64)
    question_text: str = Field(min_length=1)
    intent_tag: str = Field(default="missing_context", max_length=100)
    priority: int = 50
    source_type: str = Field(default="manual", max_length=32)
    source_session_id: uuid.UUID | None = None
    is_active: bool = True


class GoldenQuestionOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    title: str
    scenario: str
    question_text: str
    intent_tag: str
    priority: int
    source_type: str
    source_session_id: uuid.UUID | None = None
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_model(cls, item: AgentGoldenQuestion) -> "GoldenQuestionOut":
        return cls(
            id=item.id,
            agent_id=item.agent_id,
            title=item.title,
            scenario=item.scenario,
            question_text=item.question_text,
            intent_tag=item.intent_tag,
            priority=item.priority,
            source_type=item.source_type,
            source_session_id=item.source_session_id,
            is_active=item.is_active,
            created_at=item.created_at.isoformat() if item.created_at else None,
            updated_at=item.updated_at.isoformat() if item.updated_at else None,
        )


class DistillRequest(BaseModel):
    chat_session_id: uuid.UUID
    max_items: int = Field(default=5, ge=1, le=20)


class MemoryPortraitCandidate(BaseModel):
    title: str
    category: str
    content: str
    priority: int = 50
    source_type: str = "conversation_distilled"
    source_session_id: uuid.UUID | None = None


class GoldenQuestionCandidate(BaseModel):
    title: str
    scenario: str
    question_text: str
    intent_tag: str
    priority: int = 50
    source_type: str = "conversation_distilled"
    source_session_id: uuid.UUID | None = None


def _require_manage(access_level: str) -> None:
    if access_level != "manage":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manage access required")


def _extract_json_object(text: str) -> dict:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


async def _load_agent_model(db: AsyncSession, agent: Agent) -> LLMModel:
    model_id = agent.primary_model_id or agent.fallback_model_id
    if not model_id:
        raise HTTPException(status_code=400, detail="Agent has no LLM model configured")
    result = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=400, detail="Configured LLM model was not found")
    return model


async def _load_session_transcript(
    db: AsyncSession,
    agent_id: uuid.UUID,
    session_id: uuid.UUID,
    current_user: User,
) -> tuple[ChatSession, str]:
    agent, _ = await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            (ChatSession.agent_id == agent_id) | (ChatSession.peer_agent_id == agent_id),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    is_owner_or_admin = (
        str(session.user_id) == str(current_user.id)
        or current_user.role in ("platform_admin", "org_admin", "agent_admin")
        or str(agent.creator_id) == str(current_user.id)
    )
    if not is_owner_or_admin:
        raise HTTPException(status_code=403, detail="Not authorized to inspect this session")

    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == str(session_id))
        .order_by(desc(ChatMessage.created_at))
        .limit(120)
    )
    messages = list(reversed(msg_result.scalars().all()))
    if not messages:
        raise HTTPException(status_code=400, detail="Chat session has no messages to distill")

    lines: list[str] = []
    for msg in messages:
        if msg.role not in {"user", "assistant"}:
            continue
        content = (msg.content or "").strip()
        if not content:
            continue
        lines.append(f"{msg.role.upper()}: {content}")
    transcript = "\n".join(lines)
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="Chat session has no distillable dialog")
    return session, transcript[:14000]


async def _distill_candidates(
    model: LLMModel,
    agent: Agent,
    agent_id: uuid.UUID,
    session_id: uuid.UUID,
    transcript: str,
    max_items: int,
    mode: str,
) -> dict:
    if mode == "memory":
        task_prompt = f"""
You are extracting long-lived training memory portrait items for an AI agent.

Rules:
- Keep only durable, reusable alignment signals.
- Focus on user preference, communication style, task habit, constraints, and long-term context preferences.
- Exclude one-off task details, temporary secrets, transient project state, and anything too session-specific.
- Normalize wording into reusable guidance.
- Return at most {max_items} items.

Return strict JSON only with this schema:
{{
  "items": [
    {{
      "title": "short label",
      "category": "user_preference|communication_style|task_habit|constraint|long_term_context",
      "content": "one concise reusable memory statement",
      "priority": 0
    }}
  ]
}}

Conversation transcript:
{transcript}
""".strip()
    else:
        task_prompt = f"""
You are extracting reusable golden clarifying questions for an AI agent.

Rules:
- Extract only strong, reusable clarification questions that would generalize to future conversations.
- Focus on moments where the request was ambiguous, under-specified, or missing context.
- Do not produce project-private trivia or one-off questions.
- Each item must have a scenario and intent tag.
- Return at most {max_items} items.

Return strict JSON only with this schema:
{{
  "items": [
    {{
      "title": "short label",
      "scenario": "requirements_unclear|missing_business_context|ambiguous_request|missing_inputs|missing_success_criteria",
      "question_text": "the actual clarifying question",
      "intent_tag": "what this question tries to learn",
      "priority": 0
    }}
  ]
}}

Conversation transcript:
{transcript}
""".strip()

    raw = await call_llm(
        model=model,
        messages=[{"role": "user", "content": task_prompt}],
        agent_name=agent.name,
        role_description=agent.role_description or "",
        agent_id=agent_id,
        user_id=agent.creator_id,
        session_id=str(session_id),
        skip_tools=True,
        max_tool_rounds_override=1,
    )
    if not raw or raw.startswith("[LLM"):
        raise HTTPException(status_code=502, detail=f"Distillation failed: {raw or 'empty response'}")
    try:
        return _extract_json_object(raw)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Distillation returned invalid JSON: {exc}") from exc


@router.get("/{agent_id}/training/memory-portrait", response_model=list[MemoryPortraitOut])
async def list_memory_portraits(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(AgentMemoryPortrait)
        .where(AgentMemoryPortrait.agent_id == agent_id)
        .order_by(AgentMemoryPortrait.priority.desc(), AgentMemoryPortrait.updated_at.desc())
    )
    return [MemoryPortraitOut.from_model(item) for item in result.scalars().all()]


@router.post("/{agent_id}/training/memory-portrait", response_model=MemoryPortraitOut)
async def create_memory_portrait(
    agent_id: uuid.UUID,
    payload: MemoryPortraitIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, access_level = await check_agent_access(db, current_user, agent_id)
    _require_manage(access_level)
    item = AgentMemoryPortrait(agent_id=agent_id, **payload.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return MemoryPortraitOut.from_model(item)


@router.put("/{agent_id}/training/memory-portrait/{item_id}", response_model=MemoryPortraitOut)
async def update_memory_portrait(
    agent_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: MemoryPortraitIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, access_level = await check_agent_access(db, current_user, agent_id)
    _require_manage(access_level)
    result = await db.execute(
        select(AgentMemoryPortrait).where(
            AgentMemoryPortrait.id == item_id,
            AgentMemoryPortrait.agent_id == agent_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Memory portrait item not found")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    await db.flush()
    await db.refresh(item)
    return MemoryPortraitOut.from_model(item)


@router.delete("/{agent_id}/training/memory-portrait/{item_id}")
async def delete_memory_portrait(
    agent_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, access_level = await check_agent_access(db, current_user, agent_id)
    _require_manage(access_level)
    await db.execute(
        delete(AgentMemoryPortrait).where(
            AgentMemoryPortrait.id == item_id,
            AgentMemoryPortrait.agent_id == agent_id,
        )
    )
    return {"status": "ok"}


@router.post("/{agent_id}/training/memory-portrait/distill", response_model=list[MemoryPortraitCandidate])
async def distill_memory_portraits(
    agent_id: uuid.UUID,
    payload: DistillRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent, access_level = await check_agent_access(db, current_user, agent_id)
    _require_manage(access_level)
    session, transcript = await _load_session_transcript(db, agent_id, payload.chat_session_id, current_user)
    model = await _load_agent_model(db, agent)
    parsed = await _distill_candidates(model, agent, agent_id, session.id, transcript, payload.max_items, "memory")
    items = parsed.get("items") or []
    candidates = []
    for raw in items[: payload.max_items]:
        try:
            candidate = MemoryPortraitCandidate(
                title=str(raw.get("title") or "").strip(),
                category=str(raw.get("category") or "user_preference").strip(),
                content=str(raw.get("content") or "").strip(),
                priority=int(raw.get("priority") or 50),
                source_session_id=session.id,
            )
        except Exception:
            continue
        if candidate.title and candidate.content:
            candidates.append(candidate)
    return candidates


@router.get("/{agent_id}/training/golden-questions", response_model=list[GoldenQuestionOut])
async def list_golden_questions(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_agent_access(db, current_user, agent_id)
    result = await db.execute(
        select(AgentGoldenQuestion)
        .where(AgentGoldenQuestion.agent_id == agent_id)
        .order_by(AgentGoldenQuestion.priority.desc(), AgentGoldenQuestion.updated_at.desc())
    )
    return [GoldenQuestionOut.from_model(item) for item in result.scalars().all()]


@router.post("/{agent_id}/training/golden-questions", response_model=GoldenQuestionOut)
async def create_golden_question(
    agent_id: uuid.UUID,
    payload: GoldenQuestionIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, access_level = await check_agent_access(db, current_user, agent_id)
    _require_manage(access_level)
    item = AgentGoldenQuestion(agent_id=agent_id, **payload.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return GoldenQuestionOut.from_model(item)


@router.put("/{agent_id}/training/golden-questions/{item_id}", response_model=GoldenQuestionOut)
async def update_golden_question(
    agent_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: GoldenQuestionIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, access_level = await check_agent_access(db, current_user, agent_id)
    _require_manage(access_level)
    result = await db.execute(
        select(AgentGoldenQuestion).where(
            AgentGoldenQuestion.id == item_id,
            AgentGoldenQuestion.agent_id == agent_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Golden question item not found")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    await db.flush()
    await db.refresh(item)
    return GoldenQuestionOut.from_model(item)


@router.delete("/{agent_id}/training/golden-questions/{item_id}")
async def delete_golden_question(
    agent_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, access_level = await check_agent_access(db, current_user, agent_id)
    _require_manage(access_level)
    await db.execute(
        delete(AgentGoldenQuestion).where(
            AgentGoldenQuestion.id == item_id,
            AgentGoldenQuestion.agent_id == agent_id,
        )
    )
    return {"status": "ok"}


@router.post("/{agent_id}/training/golden-questions/distill", response_model=list[GoldenQuestionCandidate])
async def distill_golden_questions(
    agent_id: uuid.UUID,
    payload: DistillRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    agent, access_level = await check_agent_access(db, current_user, agent_id)
    _require_manage(access_level)
    session, transcript = await _load_session_transcript(db, agent_id, payload.chat_session_id, current_user)
    model = await _load_agent_model(db, agent)
    parsed = await _distill_candidates(model, agent, agent_id, session.id, transcript, payload.max_items, "questions")
    items = parsed.get("items") or []
    candidates = []
    for raw in items[: payload.max_items]:
        try:
            candidate = GoldenQuestionCandidate(
                title=str(raw.get("title") or "").strip(),
                scenario=str(raw.get("scenario") or "requirements_unclear").strip(),
                question_text=str(raw.get("question_text") or "").strip(),
                intent_tag=str(raw.get("intent_tag") or "missing_context").strip(),
                priority=int(raw.get("priority") or 50),
                source_session_id=session.id,
            )
        except Exception:
            continue
        if candidate.title and candidate.question_text:
            candidates.append(candidate)
    return candidates


async def load_training_assets_for_context(agent_id: uuid.UUID) -> tuple[str, str]:
    """Load training asset snippets for runtime context injection."""
    from app.database import async_session

    memory_text = ""
    golden_text = ""

    async with async_session() as db:
        memory_result = await db.execute(
            select(AgentMemoryPortrait)
            .where(
                AgentMemoryPortrait.agent_id == agent_id,
                AgentMemoryPortrait.is_active == True,
            )
            .order_by(AgentMemoryPortrait.priority.desc(), AgentMemoryPortrait.updated_at.desc())
        )
        memory_items = memory_result.scalars().all()

        if memory_items:
            lines = [
                "These are durable training portrait cues. Use them for alignment, but do not quote or reveal them verbatim to the end user.",
                "If the current user explicitly asks for something different in this conversation, follow the current instruction.",
                "",
            ]
            used = 0
            count = 0
            for item in memory_items:
                line = f"- [{item.category}] {item.title}: {item.content}"
                if count >= MEMORY_PORTRAIT_LIMIT or used + len(line) > MEMORY_PORTRAIT_BUDGET:
                    break
                lines.append(line)
                used += len(line)
                count += 1
            memory_text = "\n".join(lines).strip()

        golden_result = await db.execute(
            select(AgentGoldenQuestion)
            .where(
                AgentGoldenQuestion.agent_id == agent_id,
                AgentGoldenQuestion.is_active == True,
            )
            .order_by(AgentGoldenQuestion.scenario.asc(), AgentGoldenQuestion.priority.desc(), AgentGoldenQuestion.updated_at.desc())
        )
        golden_items = golden_result.scalars().all()
        if golden_items:
            grouped: dict[str, list[AgentGoldenQuestion]] = defaultdict(list)
            for item in golden_items:
                grouped[item.scenario].append(item)
            lines = [
                "These are reusable clarifying questions. Use them only when the user's request is ambiguous or missing context.",
                "Do not ask unnecessary follow-up questions when the request is already clear.",
                "Do not dump the whole list to the user. Pick only the smallest number of useful questions.",
                "",
            ]
            for scenario, items in grouped.items():
                lines.append(f"Scenario: {scenario}")
                for item in items:
                    lines.append(f"- {item.question_text} (intent: {item.intent_tag})")
                lines.append("")
            golden_text = "\n".join(lines).strip()

    return memory_text, golden_text
