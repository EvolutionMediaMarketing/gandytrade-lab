"""Backup status: when the last nightly backup worked, and whether copies are kept off the server."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import backup
from ..db import get_session
from ..deps import current_user
from ..models import User

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("/status")
def status(db: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return backup.status(db)
