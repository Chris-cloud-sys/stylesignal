"""Personal signal history — SPEC+, see docs/spec-deviations.md and app/insights.py."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..insights import compute_insights
from ..models import User
from ..schemas import InsightsOut

router = APIRouter(prefix="/v1/insights", tags=["insights"])


@router.get("", response_model=InsightsOut)
def get_insights(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InsightsOut:
    return compute_insights(db, user)
