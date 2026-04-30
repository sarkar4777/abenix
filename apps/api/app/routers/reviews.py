from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.sanitize import sanitize_input
from app.schemas.marketplace import CreateReviewRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus, AgentType
from models.marketplace import Review
from models.user import User

router = APIRouter(prefix="/api/agents", tags=["reviews"])


def _serialize_review(r: Review, user: User | None = None) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "agent_id": str(r.agent_id),
        "user_id": str(r.user_id),
        "rating": r.rating,
        "comment": r.comment,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "user_name": user.full_name if user else None,
        "user_avatar": user.avatar_url if user else None,
    }


@router.post("/{agent_id}/reviews")
async def create_review(
    agent_id: uuid.UUID,
    body: CreateReviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.status == AgentStatus.ACTIVE,
            Agent.is_published.is_(True),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found or not published", 404)

    existing = await db.execute(
        select(Review).where(
            Review.agent_id == agent_id,
            Review.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        return error("You have already reviewed this agent", 409)

    review = Review(
        agent_id=agent_id,
        user_id=user.id,
        rating=body.rating,
        comment=sanitize_input(body.comment) if body.comment else body.comment,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)

    return success(_serialize_review(review, user), status_code=201)


@router.get("/{agent_id}/reviews")
async def list_reviews(
    agent_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    if not result.scalar_one_or_none():
        return error("Agent not found", 404)

    offset = (page - 1) * per_page

    count_result = await db.execute(
        select(func.count(Review.id)).where(Review.agent_id == agent_id)
    )
    total = count_result.scalar() or 0

    avg_result = await db.execute(
        select(func.avg(Review.rating)).where(Review.agent_id == agent_id)
    )
    avg_rating = avg_result.scalar()

    dist_result = await db.execute(
        select(Review.rating, func.count(Review.id))
        .where(Review.agent_id == agent_id)
        .group_by(Review.rating)
    )
    distribution = {str(i): 0 for i in range(1, 6)}
    for rating, count in dist_result.all():
        distribution[str(rating)] = count

    result = await db.execute(
        select(Review, User)
        .join(User, Review.user_id == User.id)
        .where(Review.agent_id == agent_id)
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = result.all()
    reviews = [_serialize_review(r, u) for r, u in rows]

    return success(
        reviews,
        meta={
            "total": total,
            "page": page,
            "per_page": per_page,
            "avg_rating": round(float(avg_rating), 1) if avg_rating else 0,
            "distribution": distribution,
        },
    )
