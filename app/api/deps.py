"""Shared FastAPI dependencies. Tests override these, never the code behind them."""

from datetime import date
from typing import Annotated

from fastapi import Depends

from app.ai.client import GeminiClient, get_ai_client
from app.clock import today_ist
from app.config import Settings, get_settings
from app.data.loader import ReferenceData, get_reference_data


def get_today() -> date:
    return today_ist()


SettingsDep = Annotated[Settings, Depends(get_settings)]
AIDep = Annotated[GeminiClient | None, Depends(get_ai_client)]
ReferenceDep = Annotated[ReferenceData, Depends(get_reference_data)]
TodayDep = Annotated[date, Depends(get_today)]
