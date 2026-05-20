from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BitrixBaseModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",  # Позволяем лишние поля из Bitrix, но валидируем основные
    )


class BitrixDeal(BitrixBaseModel):
    id: int = Field(alias="ID")
    title: str = Field(alias="TITLE", default="")
    assigned_by_id: int | None = Field(alias="ASSIGNED_BY_ID", default=None)
    stage_id: str = Field(alias="STAGE_ID", default="")
    date_create: datetime | None = Field(alias="DATE_CREATE", default=None)
    opportunity: float = Field(alias="OPPORTUNITY", default=0.0)
    currency_id: str = Field(alias="CURRENCY_ID", default="RUB")
    category_id: int | None = Field(alias="CATEGORY_ID", default=None)
    stage_semantic_id: str | None = Field(alias="STAGE_SEMANTIC_ID", default=None)
    comments: str | None = Field(alias="COMMENTS", default=None)

    @field_validator("id", mode="before")
    @classmethod
    def parse_id(cls, v: Any) -> int:
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return v

    @field_validator("date_create", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime | None:
        if not v:
            return None
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                return None
        return v


class BitrixActivity(BitrixBaseModel):
    id: int = Field(alias="ID")
    created: datetime | None = Field(alias="CREATED", default=None)
    start_time: datetime | None = Field(alias="START_TIME", default=None)
    end_time: datetime | None = Field(alias="END_TIME", default=None)
    subject: str = Field(alias="SUBJECT", default="")
    origin_id: str | None = Field(alias="ORIGIN_ID", default=None)
    direction: int | None = Field(alias="DIRECTION", default=None)
    provider_id: str | None = Field(alias="PROVIDER_ID", default=None)
    provider_type_id: str | None = Field(alias="PROVIDER_TYPE_ID", default=None)
    author_id: int | None = Field(alias="AUTHOR_ID", default=None)
    responsible_id: int | None = Field(alias="RESPONSIBLE_ID", default=None)

    @field_validator("id", mode="before")
    @classmethod
    def parse_id(cls, v: Any) -> int:
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return v

    @field_validator("created", "start_time", "end_time", mode="before")
    @classmethod
    def parse_datetime(cls, v: Any) -> datetime | None:
        if not v:
            return None
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                return None
        return v


class ScoringResult(BitrixBaseModel):
    """Схема для хранения результатов скоринга одного звонка/сделки."""
    overall_score: float = 0.0
    call_quality_score: float = 0.0
    crm_checklist_percent: float | None = None
    emotion_state: str = "Нейтрально"
    risk_level: str = "Низкий"
    recommendations: str = ""
