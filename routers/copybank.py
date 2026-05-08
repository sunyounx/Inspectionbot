from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.database import delete_copybank, get_copybank, insert_copybank


router = APIRouter(prefix="/api", tags=["copybank"], redirect_slashes=True)


class CopybankCreateBody(BaseModel):
    copy_text: str
    category: str | None = None
    target: str | None = None
    tags: str | None = None
    source: str | None = None


@router.post("/copybank")
def create_copybank(body: CopybankCreateBody):
    ct = (body.copy_text or "").strip()
    if not ct:
        raise HTTPException(status_code=400, detail="copy_text is required")
    new_id = insert_copybank(
        {
            "copy_text": ct,
            "category": (body.category or "").strip() or None,
            "target": (body.target or "").strip() or None,
            "tags": (body.tags or "").strip() or None,
            "source": (body.source or "").strip() or "slack",
        }
    )
    return {"id": new_id}


@router.get("/copybank")
def list_copybank(limit: int = 200):
    return get_copybank(limit=limit)


@router.delete("/copybank/{id}")
def remove_copybank(id: int):
    if not delete_copybank(id):
        raise HTTPException(status_code=404, detail="copybank not found")
    return {"ok": True}

