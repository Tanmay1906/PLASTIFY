"""PLASTIFY Chain-of-Custody Pydantic Schemas."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.models.custody import CustodyState


class CustodyTransitionRequest(BaseModel):
    """Payload to advance a resource along the chain-of-custody."""

    new_state: CustodyState = Field(
        ..., description="Target chain-of-custody milestone"
    )
    notes: Optional[str] = Field(
        default=None, description="Operational notes accompanying this state transition"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional context (e.g. GPS, facility ID, vehicle tag)"
    )


class CustodyEventResponse(BaseModel):
    """Public representation of an immutable chain-of-custody transition record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resource: str
    resource_type: str
    resource_id: uuid.UUID
    previous_state: Optional[str] = None
    new_state: str
    actor_id: uuid.UUID
    actor_role: str
    actor_name: Optional[str] = None
    timestamp: datetime
    event_metadata: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class CustodyTimelineResponse(BaseModel):
    """Chronological chain-of-custody audit history for a tracked resource."""

    resource: str
    resource_id: uuid.UUID
    current_state: str
    events: List[CustodyEventResponse] = Field(default_factory=list)
