"""Marking bookings: one budget line's status and actual cost per request."""

from typing import Literal

from app.models.common import DomainModel, Id, Rupees
from app.models.plan import Plan

BookingStatus = Literal["planned", "booked", "paid"]
"""Cancelled is not offered here: a cancellation goes through Something changed."""


class LineUpdate(DomainModel):
    line_item_id: Id
    status: BookingStatus
    actual: Rupees | None = None


class LineRequest(DomainModel):
    plan: Plan
    change: LineUpdate
