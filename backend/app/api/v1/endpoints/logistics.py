"""PLASTIFY Logistics and Delivery API Endpoints.

Exposes physical material movement operations:
- Available pickup assignments
- Partner assignment & carrier acceptance
- Pickup completion, transit updates, and delivery drop-off
- Recycler intake confirmation with configurable weight tolerance verification
- Delivery history and chain-of-custody tracking
"""

from typing import List, Optional
import uuid
from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentUserDep, LogisticsServiceDep
from app.models.logistics import DeliveryStatus
from app.schemas.logistics import (
    AcceptAssignmentRequest,
    AssignLogisticsRequest,
    DeliveryHistoryResponse,
    DeliveryResponse,
    LogisticsAssignmentResponse,
    MarkDeliveredRequest,
    MarkInTransitRequest,
    MarkPickupRequest,
    RecyclerConfirmReceiptRequest,
)

router = APIRouter(prefix="/logistics", tags=["Logistics & Delivery"])


# ------------------------------------------------------------------------------
# 1. Available Pickup Assignments
# ------------------------------------------------------------------------------


@router.get(
    "/assignments/available",
    response_model=List[LogisticsAssignmentResponse],
    summary="List Available Pickup Assignments",
)
async def list_available_pickup_assignments(
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> List[LogisticsAssignmentResponse]:
    """List available transport tasks assigned or open for collection."""
    return await service.list_available_assignments(
        requester=current_user, skip=skip, limit=limit
    )


# ------------------------------------------------------------------------------
# 2. Assign Logistics Partner
# ------------------------------------------------------------------------------


@router.post(
    "/assignments",
    response_model=LogisticsAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign Logistics Partner to Recovery Event",
)
async def assign_logistics_partner(
    data: AssignLogisticsRequest,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> LogisticsAssignmentResponse:
    """Assign a submitted plastic recovery batch to a certified logistics provider."""
    return await service.assign_logistics_partner(data=data, requester=current_user)


# ------------------------------------------------------------------------------
# 3. Accept Assignment
# ------------------------------------------------------------------------------


@router.post(
    "/assignments/{assignment_id}/accept",
    response_model=LogisticsAssignmentResponse,
    summary="Accept Pickup Assignment",
)
async def accept_assignment(
    assignment_id: uuid.UUID,
    data: AcceptAssignmentRequest,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> LogisticsAssignmentResponse:
    """Carrier acknowledges and accepts the transport task."""
    return await service.accept_assignment(
        assignment_id=assignment_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# 4. Mark Pickup Completed
# ------------------------------------------------------------------------------


@router.post(
    "/assignments/{assignment_id}/pickup",
    response_model=LogisticsAssignmentResponse,
    summary="Mark Pickup Completed",
)
async def mark_pickup_completed(
    assignment_id: uuid.UUID,
    data: MarkPickupRequest,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> LogisticsAssignmentResponse:
    """Record physical collection from collector completed and seal custody batch."""
    return await service.mark_pickup_completed(
        assignment_id=assignment_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# 5. Mark In Transit
# ------------------------------------------------------------------------------


@router.post(
    "/assignments/{assignment_id}/in-transit",
    response_model=DeliveryResponse,
    summary="Mark Assignment In Transit",
)
async def mark_assignment_in_transit(
    assignment_id: uuid.UUID,
    data: MarkInTransitRequest,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> DeliveryResponse:
    """Record shipment in-transit along transport corridor."""
    return await service.mark_in_transit(
        identifier=assignment_id, data=data, requester=current_user
    )


@router.post(
    "/deliveries/{delivery_id}/in-transit",
    response_model=DeliveryResponse,
    summary="Mark Delivery In Transit",
)
async def mark_delivery_in_transit(
    delivery_id: uuid.UUID,
    data: MarkInTransitRequest,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> DeliveryResponse:
    """Record delivery in-transit using delivery ID."""
    return await service.mark_in_transit(
        identifier=delivery_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# 6. Mark Delivered
# ------------------------------------------------------------------------------


@router.post(
    "/assignments/{assignment_id}/delivered",
    response_model=DeliveryResponse,
    summary="Mark Assignment Delivered",
)
async def mark_assignment_delivered(
    assignment_id: uuid.UUID,
    data: MarkDeliveredRequest,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> DeliveryResponse:
    """Carrier marks physical drop-off at recipient recycling facility."""
    return await service.mark_delivered(
        identifier=assignment_id, data=data, requester=current_user
    )


@router.post(
    "/deliveries/{delivery_id}/delivered",
    response_model=DeliveryResponse,
    summary="Mark Delivery Delivered",
)
async def mark_delivery_delivered(
    delivery_id: uuid.UUID,
    data: MarkDeliveredRequest,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> DeliveryResponse:
    """Carrier marks arrival and drop-off using delivery ID."""
    return await service.mark_delivered(
        identifier=delivery_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# 7. Recycler Confirms Receipt & Weight Tolerance Verification
# ------------------------------------------------------------------------------


@router.post(
    "/deliveries/{delivery_id}/receive",
    response_model=DeliveryResponse,
    summary="Recycler Confirms Receipt and Weighs Shipment",
)
async def recycler_confirm_receipt(
    delivery_id: uuid.UUID,
    data: RecyclerConfirmReceiptRequest,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> DeliveryResponse:
    """Recipient facility logs intake weight, verifies tolerance (PASS / FLAG_FOR_REVIEW), and accepts custody."""
    return await service.recycler_confirm_receipt(
        delivery_id=delivery_id, data=data, requester=current_user
    )


@router.post(
    "/assignments/{assignment_id}/receive",
    response_model=DeliveryResponse,
    summary="Recycler Confirms Receipt by Assignment ID",
)
async def recycler_confirm_receipt_by_assignment(
    assignment_id: uuid.UUID,
    data: RecyclerConfirmReceiptRequest,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> DeliveryResponse:
    """Recipient facility confirms receipt referencing assignment ID."""
    return await service.recycler_confirm_receipt(
        delivery_id=assignment_id, data=data, requester=current_user
    )


# ------------------------------------------------------------------------------
# 8. View Delivery History & Details
# ------------------------------------------------------------------------------


@router.get(
    "/deliveries/{delivery_id}/history",
    response_model=DeliveryHistoryResponse,
    summary="View Delivery History and Chain-of-Custody Timeline",
)
async def get_delivery_history(
    delivery_id: uuid.UUID,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> DeliveryHistoryResponse:
    """Retrieve full delivery record with chronological append-only chain-of-custody events."""
    return await service.get_delivery_history(
        delivery_id=delivery_id, requester=current_user
    )


@router.get(
    "/assignments/{assignment_id}/history",
    response_model=DeliveryHistoryResponse,
    summary="View Delivery History by Assignment ID",
)
async def get_assignment_history(
    assignment_id: uuid.UUID,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> DeliveryHistoryResponse:
    """Retrieve delivery history referencing assignment ID."""
    return await service.get_delivery_history(
        delivery_id=assignment_id, requester=current_user
    )


# ------------------------------------------------------------------------------
# 9. List and Inspect Deliveries / Assignments
# ------------------------------------------------------------------------------


@router.get(
    "/deliveries",
    response_model=List[DeliveryResponse],
    summary="List Deliveries",
)
async def list_deliveries(
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
    status: Optional[DeliveryStatus] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> List[DeliveryResponse]:
    """List deliveries filtered by tenant organization boundaries."""
    return await service.list_deliveries(
        requester=current_user, status=status, skip=skip, limit=limit
    )


@router.get(
    "/deliveries/{delivery_id}",
    response_model=DeliveryResponse,
    summary="Get Delivery Details",
)
async def get_delivery(
    delivery_id: uuid.UUID,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> DeliveryResponse:
    """Retrieve single delivery record."""
    return await service.get_delivery(
        delivery_id=delivery_id, requester=current_user
    )


@router.get(
    "/assignments/{assignment_id}",
    response_model=LogisticsAssignmentResponse,
    summary="Get Assignment Details",
)
async def get_assignment(
    assignment_id: uuid.UUID,
    service: LogisticsServiceDep,
    current_user: CurrentUserDep,
) -> LogisticsAssignmentResponse:
    """Retrieve single logistics assignment record."""
    return await service.get_assignment(
        assignment_id=assignment_id, requester=current_user
    )
