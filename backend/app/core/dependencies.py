"""PLASTIFY Core Dependency Injection Providers.

Central authentication, Role-Based Access Control (RBAC), and service injection.
"""

from typing import Annotated, Callable, List, Optional
import uuid
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.logging import get_current_request_id
from app.core.redis import get_redis_client
from app.core.security import decode_token
from app.core.malware import (
    BaseMalwareScanner,
    ClamAVScanner,
    MockMalwareScanner,
)
from app.core.storage import (
    IStorageService,
    MockStorageService,
    S3StorageService,
)
from app.models.user import User, UserRole
from app.repositories.audit import AuditRepository
from app.repositories.custody import ChainOfCustodyRepository
from app.repositories.evidence import EvidenceRepository
from app.repositories.organization import (
    OrganizationRepository,
    OrgMemberRepository,
    PartnerRepository,
)
from app.repositories.program import (
    ProgramPartnerRepository,
    ProgramRepository,
)
from app.repositories.logistics import LogisticsRepository
from app.repositories.recovery import (
    RecoveryHistoryRepository,
    RecoveryRepository,
)
from app.repositories.user import RefreshTokenRepository, UserRepository
from app.repositories.verification import VerificationRepository
from app.repositories.sentinel import SentinelRepository
from app.repositories.circular import CircularRepository
from app.services.auth import AuthService
from app.services.custody import ChainOfCustodyService
from app.services.evidence import EvidenceService
from app.services.logistics import LogisticsService
from app.services.organization import OrganizationService
from app.services.program import ProgramService
from app.services.recovery import RecoveryService
from app.services.verification import VerificationService
from app.services.sentinel_service import SentinelService
from app.services.recycling import RecyclingService
from app.services.upcycling import UpcyclingService
from app.services.passport import PassportService
from app.repositories.impact import AssessmentRepository, ImpactRepository, MethodologyRepository
from app.repositories.credit import CreditRepository
from app.services.impact import ImpactService
from app.services.methodology import MethodologyService
from app.services.eligibility import EligibilityService
from app.services.credit import CreditService

# Security scheme for OpenAPI Swagger documentation
security_scheme = HTTPBearer(auto_error=False)


def get_request_id(request: Request) -> str:
    """Extract request correlation ID from request state or context."""
    return getattr(request.state, "request_id", None) or get_current_request_id() or ""


# Type aliases for core dependencies
SettingsDep = Annotated[Settings, Depends(get_settings)]
DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis_client)]
RequestIDDep = Annotated[str, Depends(get_request_id)]


# ------------------------------------------------------------------------------
# Repository Providers
# ------------------------------------------------------------------------------

def get_user_repo(session: DBSessionDep) -> UserRepository:
    return UserRepository(session)


def get_token_repo(session: DBSessionDep) -> RefreshTokenRepository:
    return RefreshTokenRepository(session)


def get_org_repo(session: DBSessionDep) -> OrganizationRepository:
    return OrganizationRepository(session)


def get_member_repo(session: DBSessionDep) -> OrgMemberRepository:
    return OrgMemberRepository(session)


def get_partner_repo(session: DBSessionDep) -> PartnerRepository:
    return PartnerRepository(session)


def get_program_repo(session: DBSessionDep) -> ProgramRepository:
    return ProgramRepository(session)


def get_program_partner_repo(session: DBSessionDep) -> ProgramPartnerRepository:
    return ProgramPartnerRepository(session)


def get_recovery_repo(session: DBSessionDep) -> RecoveryRepository:
    return RecoveryRepository(session)


def get_recovery_history_repo(session: DBSessionDep) -> RecoveryHistoryRepository:
    return RecoveryHistoryRepository(session)


def get_audit_repo(session: DBSessionDep) -> AuditRepository:
    return AuditRepository(session)


def get_evidence_repo(session: DBSessionDep) -> EvidenceRepository:
    return EvidenceRepository(session)


def get_custody_repo(session: DBSessionDep) -> ChainOfCustodyRepository:
    return ChainOfCustodyRepository(session)


def get_logistics_repo(session: DBSessionDep) -> LogisticsRepository:
    return LogisticsRepository(session)


def get_verification_repo(session: DBSessionDep) -> VerificationRepository:
    return VerificationRepository(session)


def get_sentinel_repo(session: DBSessionDep) -> SentinelRepository:
    return SentinelRepository(session)


def get_circular_repo(session: DBSessionDep) -> CircularRepository:
    return CircularRepository(session)


def get_storage_service(settings: SettingsDep) -> IStorageService:
    if settings.ENVIRONMENT == "test" or settings.S3_ENDPOINT_URL == "mock":
        return MockStorageService(bucket_name=settings.S3_BUCKET_NAME)
    return S3StorageService(settings=settings)


def get_malware_scanner(settings: SettingsDep) -> BaseMalwareScanner:
    if settings.MALWARE_SCANNER_TYPE == "clamav":
        return ClamAVScanner()
    return MockMalwareScanner()


UserRepoDep = Annotated[UserRepository, Depends(get_user_repo)]
TokenRepoDep = Annotated[RefreshTokenRepository, Depends(get_token_repo)]
OrgRepoDep = Annotated[OrganizationRepository, Depends(get_org_repo)]
MemberRepoDep = Annotated[OrgMemberRepository, Depends(get_member_repo)]
PartnerRepoDep = Annotated[PartnerRepository, Depends(get_partner_repo)]
ProgramRepoDep = Annotated[ProgramRepository, Depends(get_program_repo)]
ProgramPartnerRepoDep = Annotated[ProgramPartnerRepository, Depends(get_program_partner_repo)]
RecoveryRepoDep = Annotated[RecoveryRepository, Depends(get_recovery_repo)]
RecoveryHistoryRepoDep = Annotated[RecoveryHistoryRepository, Depends(get_recovery_history_repo)]
AuditRepoDep = Annotated[AuditRepository, Depends(get_audit_repo)]
EvidenceRepoDep = Annotated[EvidenceRepository, Depends(get_evidence_repo)]
CustodyRepoDep = Annotated[ChainOfCustodyRepository, Depends(get_custody_repo)]
LogisticsRepoDep = Annotated[LogisticsRepository, Depends(get_logistics_repo)]
VerificationRepoDep = Annotated[VerificationRepository, Depends(get_verification_repo)]
SentinelRepoDep = Annotated[SentinelRepository, Depends(get_sentinel_repo)]
CircularRepoDep = Annotated[CircularRepository, Depends(get_circular_repo)]
StorageServiceDep = Annotated[IStorageService, Depends(get_storage_service)]
MalwareScannerDep = Annotated[BaseMalwareScanner, Depends(get_malware_scanner)]

def get_impact_repo(session: DBSessionDep) -> ImpactRepository:
    return ImpactRepository(session)

def get_methodology_repo(session: DBSessionDep) -> MethodologyRepository:
    return MethodologyRepository(session)

def get_assessment_repo(session: DBSessionDep) -> AssessmentRepository:
    return AssessmentRepository(session)

def get_credit_repo(session: DBSessionDep) -> CreditRepository:
    return CreditRepository(session)

ImpactRepoDep = Annotated[ImpactRepository, Depends(get_impact_repo)]
MethodologyRepoDep = Annotated[MethodologyRepository, Depends(get_methodology_repo)]
AssessmentRepoDep = Annotated[AssessmentRepository, Depends(get_assessment_repo)]
CreditRepoDep = Annotated[CreditRepository, Depends(get_credit_repo)]


# ------------------------------------------------------------------------------
# Service Providers
# ------------------------------------------------------------------------------

def get_auth_service(
    settings: SettingsDep,
    user_repo: UserRepoDep,
    token_repo: TokenRepoDep,
    org_repo: OrgRepoDep,
    member_repo: MemberRepoDep,
) -> AuthService:
    return AuthService(
        settings=settings,
        user_repo=user_repo,
        token_repo=token_repo,
        org_repo=org_repo,
        org_member_repo=member_repo,
    )


def get_org_service(
    settings: SettingsDep,
    org_repo: OrgRepoDep,
    member_repo: MemberRepoDep,
    partner_repo: PartnerRepoDep,
    user_repo: UserRepoDep,
) -> OrganizationService:
    return OrganizationService(
        settings=settings,
        org_repo=org_repo,
        member_repo=member_repo,
        partner_repo=partner_repo,
        user_repo=user_repo,
    )


def get_program_service(
    settings: SettingsDep,
    program_repo: ProgramRepoDep,
    partner_repo: ProgramPartnerRepoDep,
    org_repo: OrgRepoDep,
    member_repo: MemberRepoDep,
) -> ProgramService:
    return ProgramService(
        settings=settings,
        program_repo=program_repo,
        partner_repo=partner_repo,
        org_repo=org_repo,
        member_repo=member_repo,
    )


def get_recovery_service(
    settings: SettingsDep,
    recovery_repo: RecoveryRepoDep,
    history_repo: RecoveryHistoryRepoDep,
    program_repo: ProgramRepoDep,
    program_partner_repo: ProgramPartnerRepoDep,
    member_repo: MemberRepoDep,
) -> RecoveryService:
    return RecoveryService(
        settings=settings,
        recovery_repo=recovery_repo,
        history_repo=history_repo,
        program_repo=program_repo,
        program_partner_repo=program_partner_repo,
        member_repo=member_repo,
    )


def get_evidence_service(
    settings: SettingsDep,
    evidence_repo: EvidenceRepoDep,
    recovery_repo: RecoveryRepoDep,
    program_repo: ProgramRepoDep,
    program_partner_repo: ProgramPartnerRepoDep,
    audit_repo: AuditRepoDep,
    storage_service: StorageServiceDep,
    malware_scanner: MalwareScannerDep,
) -> EvidenceService:
    return EvidenceService(
        settings=settings,
        evidence_repo=evidence_repo,
        recovery_repo=recovery_repo,
        program_repo=program_repo,
        program_partner_repo=program_partner_repo,
        audit_repo=audit_repo,
        storage_service=storage_service,
        malware_scanner=malware_scanner,
    )


def get_custody_service(
    settings: SettingsDep,
    custody_repo: CustodyRepoDep,
    recovery_repo: RecoveryRepoDep,
    program_repo: ProgramRepoDep,
    program_partner_repo: ProgramPartnerRepoDep,
    audit_repo: AuditRepoDep,
) -> ChainOfCustodyService:
    return ChainOfCustodyService(
        settings=settings,
        custody_repo=custody_repo,
        recovery_repo=recovery_repo,
        program_repo=program_repo,
        program_partner_repo=program_partner_repo,
        audit_repo=audit_repo,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
OrgServiceDep = Annotated[OrganizationService, Depends(get_org_service)]
ProgramServiceDep = Annotated[ProgramService, Depends(get_program_service)]
RecoveryServiceDep = Annotated[RecoveryService, Depends(get_recovery_service)]
EvidenceServiceDep = Annotated[EvidenceService, Depends(get_evidence_service)]
CustodyServiceDep = Annotated[ChainOfCustodyService, Depends(get_custody_service)]


def get_logistics_service(
    settings: SettingsDep,
    logistics_repo: LogisticsRepoDep,
    recovery_repo: RecoveryRepoDep,
    organization_repo: OrgRepoDep,
    program_repo: ProgramRepoDep,
    program_partner_repo: ProgramPartnerRepoDep,
    custody_service: CustodyServiceDep,
    audit_repo: AuditRepoDep,
) -> LogisticsService:
    return LogisticsService(
        settings=settings,
        logistics_repo=logistics_repo,
        recovery_repo=recovery_repo,
        organization_repo=organization_repo,
        program_repo=program_repo,
        program_partner_repo=program_partner_repo,
        custody_service=custody_service,
        audit_repo=audit_repo,
    )


LogisticsServiceDep = Annotated[LogisticsService, Depends(get_logistics_service)]


def get_verification_service(
    settings: SettingsDep,
    verification_repo: VerificationRepoDep,
    recovery_repo: RecoveryRepoDep,
    history_repo: RecoveryHistoryRepoDep,
    logistics_repo: LogisticsRepoDep,
    evidence_repo: EvidenceRepoDep,
    organization_repo: OrgRepoDep,
    program_repo: ProgramRepoDep,
    program_partner_repo: ProgramPartnerRepoDep,
    custody_service: CustodyServiceDep,
    audit_repo: AuditRepoDep,
) -> VerificationService:
    return VerificationService(
        settings=settings,
        verification_repo=verification_repo,
        recovery_repo=recovery_repo,
        history_repo=history_repo,
        logistics_repo=logistics_repo,
        evidence_repo=evidence_repo,
        organization_repo=organization_repo,
        program_repo=program_repo,
        program_partner_repo=program_partner_repo,
        custody_service=custody_service,
        audit_repo=audit_repo,
    )


VerificationServiceDep = Annotated[VerificationService, Depends(get_verification_service)]


def get_sentinel_service(
    sentinel_repo: SentinelRepoDep,
    recovery_repo: RecoveryRepoDep,
    program_repo: ProgramRepoDep,
    evidence_repo: EvidenceRepoDep,
    logistics_repo: LogisticsRepoDep,
    custody_repo: CustodyRepoDep,
    audit_repo: AuditRepoDep,
) -> SentinelService:
    return SentinelService(
        sentinel_repo=sentinel_repo,
        recovery_repo=recovery_repo,
        program_repo=program_repo,
        evidence_repo=evidence_repo,
        logistics_repo=logistics_repo,
        custody_repo=custody_repo,
        audit_repo=audit_repo,
    )


SentinelServiceDep = Annotated[SentinelService, Depends(get_sentinel_service)]


def get_recycling_service(
    circular_repo: CircularRepoDep,
    recovery_repo: RecoveryRepoDep,
    custody_service: CustodyServiceDep,
    custody_repo: CustodyRepoDep,
    audit_repo: AuditRepoDep,
    storage_service: StorageServiceDep,
    settings: SettingsDep,
) -> RecyclingService:
    return RecyclingService(
        circular_repo=circular_repo,
        recovery_repo=recovery_repo,
        custody_service=custody_service,
        custody_repo=custody_repo,
        audit_repo=audit_repo,
        storage_service=storage_service,
        settings=settings,
    )


RecyclingServiceDep = Annotated[RecyclingService, Depends(get_recycling_service)]


def get_upcycling_service(
    circular_repo: CircularRepoDep,
    audit_repo: AuditRepoDep,
    storage_service: StorageServiceDep,
    settings: SettingsDep,
) -> UpcyclingService:
    return UpcyclingService(
        circular_repo=circular_repo,
        audit_repo=audit_repo,
        storage_service=storage_service,
        settings=settings,
    )


UpcyclingServiceDep = Annotated[UpcyclingService, Depends(get_upcycling_service)]


def get_passport_service(
    circular_repo: CircularRepoDep,
) -> PassportService:
    return PassportService(circular_repo=circular_repo)


PassportServiceDep = Annotated[PassportService, Depends(get_passport_service)]


def get_impact_service(
    impact_repo: ImpactRepoDep,
    recovery_repo: RecoveryRepoDep,
    circular_repo: CircularRepoDep,
    verification_repo: VerificationRepoDep,
    audit_repo: AuditRepoDep,
) -> ImpactService:
    return ImpactService(
        impact_repo=impact_repo,
        recovery_repo=recovery_repo,
        circular_repo=circular_repo,
        verification_repo=verification_repo,
        audit_repo=audit_repo,
    )


ImpactServiceDep = Annotated[ImpactService, Depends(get_impact_service)]


def get_methodology_service(
    methodology_repo: MethodologyRepoDep,
    audit_repo: AuditRepoDep,
) -> MethodologyService:
    return MethodologyService(
        methodology_repo=methodology_repo,
        audit_repo=audit_repo,
    )


MethodologyServiceDep = Annotated[MethodologyService, Depends(get_methodology_service)]


def get_eligibility_service(
    assessment_repo: AssessmentRepoDep,
    impact_repo: ImpactRepoDep,
    methodology_repo: MethodologyRepoDep,
    audit_repo: AuditRepoDep,
) -> EligibilityService:
    return EligibilityService(
        assessment_repo=assessment_repo,
        impact_repo=impact_repo,
        methodology_repo=methodology_repo,
        audit_repo=audit_repo,
    )


EligibilityServiceDep = Annotated[EligibilityService, Depends(get_eligibility_service)]


def get_credit_service(
    credit_repo: CreditRepoDep,
    impact_repo: ImpactRepoDep,
    assessment_repo: AssessmentRepoDep,
    methodology_repo: MethodologyRepoDep,
    audit_repo: AuditRepoDep,
) -> CreditService:
    return CreditService(
        credit_repo=credit_repo,
        impact_repo=impact_repo,
        assessment_repo=assessment_repo,
        methodology_repo=methodology_repo,
        audit_repo=audit_repo,
    )


CreditServiceDep = Annotated[CreditService, Depends(get_credit_service)]


# ------------------------------------------------------------------------------
# Authentication Dependencies
# ------------------------------------------------------------------------------

async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security_scheme)],
    user_repo: UserRepoDep,
) -> User:
    """Validate Bearer JWT access token and retrieve current active user."""
    if not credentials or not credentials.credentials:
        raise UnauthorizedException("Authentication required: Missing Bearer token.")

    token = credentials.credentials
    payload = decode_token(token, expected_type="access")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedException("Invalid token claims: subject missing.")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise UnauthorizedException("Invalid token claims: invalid user ID format.")

    user = await user_repo.get_with_organization(user_id)
    if not user:
        raise UnauthorizedException("User account associated with token not found.")

    if not user.is_active:
        raise ForbiddenException("Account has been deactivated. Please contact support.")

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


# ------------------------------------------------------------------------------
# Central RBAC Dependency System
# ------------------------------------------------------------------------------

def require_roles(*allowed_roles: UserRole) -> Callable[[User], User]:
    """Dependency factory checking that user holds at least one of the specified roles.

    SUPER_ADMIN always bypasses role checks as superuser.
    Never relies on frontend checks.
    """

    async def role_checker(current_user: CurrentUserDep) -> User:
        if current_user.role == UserRole.SUPER_ADMIN:
            return current_user

        if current_user.role not in allowed_roles:
            role_names = [r.value for r in allowed_roles]
            raise ForbiddenException(
                f"Insufficient permissions. Required roles: {role_names} (Current: {current_user.role.value})."
            )
        return current_user

    return role_checker
