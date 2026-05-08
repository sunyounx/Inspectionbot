from typing import Literal, Optional, Union

from pydantic import BaseModel

FEEDBACK_CATEGORY = Literal["크리에이티브", "프로모션", "CRM", "브랜딩", "퍼포먼스", "기타", "미분류"]


class FeedbackClassification(BaseModel):
    is_feedback: bool
    confidence: float
    reason: str


class RefinedFeedback(BaseModel):
    date: str
    topic: str
    summary: str
    scope: Literal["영상", "이미지DA", "카피", "전체"]
    type: Literal["방향성", "규칙"]
    original_quote: str
    category: FEEDBACK_CATEGORY


class ConflictCheck(BaseModel):
    conflicts: bool
    explanation: str
    recommendation: Literal["replace_old", "keep_both", "keep_old"]


class HistoryItem(BaseModel):
    id: Optional[int] = None
    date: str
    topic: str
    summary: str
    scope: str
    type: str
    full_text: Optional[str] = None
    original_quote: Optional[str] = None
    status: str = "활성"
    changed_date: Optional[str] = None
    slack_link: Optional[str] = None
    category: Optional[str] = "크리에이티브"


class InspectRequest(BaseModel):
    message: str
    # 단일 값(구 클라이언트) 또는 배열(다중 이미지). 둘 다 list면 zip, 한쪽만 있으면 400.
    image_base64: Optional[Union[str, list[str]]] = None
    image_media_type: Optional[Union[str, list[str]]] = None
    mode: Literal["소재검수", "히스토리조회", "용어해석", "원본메시지검색", "카피창작"] = "소재검수"
    # 원본메시지검색: UI 필터와 동일 집합
    raw_kind: Optional[str] = None
    raw_query: Optional[str] = None
    raw_author: Optional[str] = None
    raw_has_files: Optional[bool] = None
    raw_order: Optional[Literal["asc", "desc"]] = None
    raw_limit: Optional[int] = None


class InspectResponse(BaseModel):
    feedback: str
    rules_checked: int

