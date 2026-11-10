import operator
from typing import Annotated, TypedDict


class IncidentState(TypedDict, total=False):
    incident_id: str
    alert: dict
    severity: str
    similar: list
    # Parallel investigators each add findings; operator.add merges the lists.
    findings: Annotated[list, operator.add]
    attempt: int
    loop_count: int
    hypothesis: dict
    critic: dict
    proposed_action: dict
    approval: dict
    execution: dict
    verified: bool
