"""The Plan: the single document stored in the browser and sent to every endpoint."""

from typing import Literal, Self

from pydantic import Field, model_validator

from app.models.common import DomainModel, Source
from app.models.event import Event, Function, Idea, LineItem, Person, Task

SCHEMA_VERSION: Literal[1] = 1

MAX_FUNCTIONS = 12
MAX_LINE_ITEMS = 300
MAX_TASKS = 500
MAX_PEOPLE = 50
MAX_IDEAS = 100


class Sources(DomainModel):
    """Which sections came from Gemini and which from rule-based fallbacks."""

    brief: Source = "ai"
    plan: Source = "ai"
    options: Source = "ai"


class Plan(DomainModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    event: Event
    functions: list[Function] = Field(default_factory=list, max_length=MAX_FUNCTIONS)
    line_items: list[LineItem] = Field(default_factory=list, max_length=MAX_LINE_ITEMS)
    tasks: list[Task] = Field(default_factory=list, max_length=MAX_TASKS)
    people: list[Person] = Field(default_factory=list, max_length=MAX_PEOPLE)
    ideas: list[Idea] = Field(default_factory=list, max_length=MAX_IDEAS)
    sources: Sources = Field(default_factory=Sources)

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        function_ids = _unique("functions", [f.id for f in self.functions])
        person_ids = _unique("people", [p.id for p in self.people])
        _unique("line_items", [i.id for i in self.line_items])
        _unique("tasks", [t.id for t in self.tasks])
        _unique("ideas", [i.id for i in self.ideas])

        for item in self.line_items:
            _check_ref(item.function_id, function_ids, f"line item {item.id}: unknown function")
            for payer in item.payers:
                _check_ref(payer.person_id, person_ids, f"line item {item.id}: unknown payer")
        for task in self.tasks:
            _check_ref(task.function_id, function_ids, f"task {task.id}: unknown function")
            _check_ref(task.owner_id, person_ids, f"task {task.id}: unknown owner")
        for idea in self.ideas:
            _check_ref(idea.function_id, function_ids, f"idea {idea.id}: unknown function")
        return self

    @model_validator(mode="after")
    def _within_event_dates(self) -> Self:
        start, end = self.event.start_date, self.event.end_date
        for function in self.functions:
            if not start <= function.start.date() <= end:
                raise ValueError(f"function {function.id} starts outside the event dates")
        for task in self.tasks:
            if task.due_date > end:
                raise ValueError(f"task {task.id} is due after the event")
        return self


def _unique(label: str, ids: list[str]) -> set[str]:
    seen = set(ids)
    if len(seen) != len(ids):
        raise ValueError(f"duplicate id in {label}")
    return seen


def _check_ref(ref: str | None, known: set[str], message: str) -> None:
    if ref is not None and ref not in known:
        raise ValueError(message)
