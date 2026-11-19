"""Version-one data contracts shared by the registry and the control-plane result boundary."""

from typing import Literal

from pydantic import BaseModel, Field, StrictBool, ValidationError

from .store import Fault


class Contract(BaseModel):
    version: str
    endpoint: Literal["/inventory"]
    required: list[str] = Field(min_length=1, max_length=32)
    types: dict[str, Literal["string", "integer", "boolean", "number"]]


class PrimaryEvidence(BaseModel):
    contract: Contract
    sample: dict


class Report(BaseModel):
    compatible: StrictBool
    findings: list[dict | str]
    method: str
    revision: int


class Review(BaseModel):
    pass_: StrictBool = Field(alias="pass")
    source_matches: StrictBool
    findings: list[dict]
    method: str
    reviewer: str


class Advice(BaseModel):
    statement: str = Field(min_length=1, max_length=2400)
    model: str


class Turn(Advice):
    position: Literal["proposal", "dissent", "commitment"]


class Plan(BaseModel):
    playbook: str
    scope: str
    acceptance: str


class Receipt(BaseModel):
    id: str
    status: Literal["open"]


OUTPUTS = {
    "contract.read": PrimaryEvidence,
    "contract.verify": Review,
    "report.write": Report,
    "meeting.speak": Turn,
    "request.reply": Advice,
    "assignment.plan": Plan,
    "ticket.create": Receipt,
}


def validate(tool, result):
    try:
        OUTPUTS[tool].model_validate(result)
    except ValidationError as exc:
        raise Fault(
            "Worker output violates the registered " + tool + " contract", 422
        ) from exc
