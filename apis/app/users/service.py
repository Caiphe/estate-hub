import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from pwdlib import PasswordHash
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.events import AuditEventCode
from app.audit.service import record_audit_event
from app.auth.constants import RevocationReason
from app.auth.permissions import Permission
from app.auth.policy import Actor, require_permissions
from app.auth.service import invalidate_user_sessions
from app.core.security.access_tokens import utc_now
from app.core.security.passwords import DEFAULT_PASSWORD_HASHER, hash_password
from app.users.constants import RoleCode, UserStatus
from app.users.errors import (
    AdministratorAlreadyExistsError,
    EmailAlreadyExistsError,
    LastAdministratorError,
    SelfLockoutError,
    StaffNotFoundError,
    UnknownRoleError,
)
from app.users.models import Role, User
from app.users.repository import UserRepository
from app.users.schemas import StaffCreate, StaffListQuery, StaffUpdate

ENTITY_TYPE = "user"
ADMINISTRATOR = RoleCode.ADMINISTRATOR.value


class StaffService:
    """Administrator management of staff accounts.

    Each mutation is one transaction containing the change and exactly one audit event.
    A request that changes nothing (for example disabling a disabled account) succeeds
    without an event. Permissions are checked here as well as on the routes, so non-HTTP
    callers cannot bypass them.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
        password_hasher: PasswordHash = DEFAULT_PASSWORD_HASHER,
    ) -> None:
        self._db = db
        self._users = UserRepository(db)
        self._clock = clock
        self._hasher = password_hasher

    # --- Reads ---------------------------------------------------------------------------

    async def list_staff(self, actor: Actor, query: StaffListQuery) -> tuple[list[User], int]:
        require_permissions(actor, Permission.STAFF_READ)
        return await self._users.list_staff(query)

    async def get_staff(self, actor: Actor, user_id: uuid.UUID) -> User:
        require_permissions(actor, Permission.STAFF_READ)
        return await self._get(user_id)

    # --- Mutations -----------------------------------------------------------------------

    async def create_staff(
        self, actor: Actor, data: StaffCreate, *, request_id: str | None = None
    ) -> User:
        require_permissions(actor, Permission.STAFF_CREATE)
        return await self._unit_of_work(
            lambda: self._create(data, actor.user_id, AuditEventCode.STAFF_CREATED, request_id)
        )

    async def bootstrap_administrator(
        self, email: str, full_name: str, password: str, *, allow_additional: bool = False
    ) -> User:
        """Create an administrator with no acting user, for first-time setup.

        Only the operator CLI calls this. It refuses while any active administrator
        exists unless ``allow_additional`` is set. Input goes through the same schema,
        hashing, and audit path as the API; the event has no actor.
        """
        data = StaffCreate(
            email=email,
            full_name=full_name,
            password=SecretStr(password),
            roles=[RoleCode.ADMINISTRATOR],
        )

        async def work() -> User:
            # The same lock as demotion and disabling, so two bootstraps cannot race.
            await self._users.lock_administrator_set()
            if not allow_additional and await self._users.count_active_administrators():
                raise AdministratorAlreadyExistsError()
            return await self._create(
                data, None, AuditEventCode.STAFF_BOOTSTRAP_ADMIN_CREATED, None
            )

        return await self._unit_of_work(work)

    async def _create(
        self,
        data: StaffCreate,
        actor_id: uuid.UUID | None,
        code: AuditEventCode,
        request_id: str | None,
    ) -> User:
        if await self._users.email_taken(data.email):
            raise EmailAlreadyExistsError()
        roles = await self._roles([role.value for role in data.roles])
        password_hash = await asyncio.to_thread(
            hash_password, data.password.get_secret_value(), self._hasher
        )
        user = User(
            id=uuid.uuid4(),
            email=data.email,
            full_name=data.full_name,
            password_hash=password_hash,
            status=UserStatus.ACTIVE,
            created_by_id=actor_id,
            updated_by_id=actor_id,
        )
        user.roles = roles
        self._db.add(user)
        await self._flush_unique_email()
        record_audit_event(
            self._db,
            code,
            actor_id=actor_id,
            request_id=request_id,
            entity_type=ENTITY_TYPE,
            entity_id=user.id,
            metadata={"roles": sorted(role.code for role in roles)},
        )
        return await self._fresh(user)

    async def update_profile(
        self,
        actor: Actor,
        user_id: uuid.UUID,
        data: StaffUpdate,
        *,
        request_id: str | None = None,
    ) -> User:
        require_permissions(actor, Permission.STAFF_UPDATE)

        async def work() -> User:
            user = await self._get(user_id, for_update=True)
            changes = {
                name: value
                for name, value in data.model_dump(exclude_unset=True).items()
                if getattr(user, name) != value
            }
            if not changes:
                return user
            if "email" in changes and await self._users.email_taken(
                changes["email"], excluding=user.id
            ):
                raise EmailAlreadyExistsError()
            for name, value in changes.items():
                setattr(user, name, value)
            user.updated_by_id = actor.user_id
            await self._flush_unique_email()
            self._audit(
                AuditEventCode.STAFF_PROFILE_UPDATED,
                actor,
                user.id,
                request_id,
                {"changed_fields": sorted(changes)},
            )
            return await self._fresh(user)

        return await self._unit_of_work(work)

    async def replace_roles(
        self,
        actor: Actor,
        user_id: uuid.UUID,
        role_codes: list[RoleCode],
        *,
        request_id: str | None = None,
    ) -> User:
        require_permissions(actor, Permission.STAFF_ASSIGN_ROLES)

        async def work() -> User:
            await self._users.lock_administrator_set()
            user = await self._get(user_id, for_update=True)
            roles = await self._roles([code.value for code in role_codes])
            before = sorted(user.role_codes)
            after = sorted(role.code for role in roles)
            if before == after:
                return user
            if ADMINISTRATOR in before and ADMINISTRATOR not in after:
                if user.id == actor.user_id:
                    raise SelfLockoutError()
                await self._ensure_another_administrator(user)
            user.roles = roles
            user.updated_by_id = actor.user_id
            # Existing access tokens stop working, so the new roles apply immediately.
            await self._users.increment_token_version(user.id)
            self._audit(
                AuditEventCode.STAFF_ROLES_CHANGED,
                actor,
                user.id,
                request_id,
                {"before": before, "after": after},
            )
            return await self._fresh(user)

        return await self._unit_of_work(work)

    async def disable(
        self, actor: Actor, user_id: uuid.UUID, *, request_id: str | None = None
    ) -> User:
        require_permissions(actor, Permission.STAFF_DISABLE)

        async def work() -> User:
            await self._users.lock_administrator_set()
            user = await self._get(user_id, for_update=True)
            if user.id == actor.user_id:
                raise SelfLockoutError()
            if user.status == UserStatus.DISABLED:
                return user
            if ADMINISTRATOR in user.role_codes:
                await self._ensure_another_administrator(user)
            user.status = UserStatus.DISABLED
            user.updated_by_id = actor.user_id
            revoked = await invalidate_user_sessions(
                self._db, user.id, RevocationReason.USER_DISABLED, self._clock()
            )
            self._audit(
                AuditEventCode.STAFF_DISABLED,
                actor,
                user.id,
                request_id,
                {"revoked_sessions": revoked},
            )
            return await self._fresh(user)

        return await self._unit_of_work(work)

    async def reactivate(
        self, actor: Actor, user_id: uuid.UUID, *, request_id: str | None = None
    ) -> User:
        require_permissions(actor, Permission.STAFF_REACTIVATE)

        async def work() -> User:
            user = await self._get(user_id, for_update=True)
            if user.status == UserStatus.ACTIVE:
                return user
            # Old sessions were revoked on disable and stay revoked: the user signs in again.
            user.status = UserStatus.ACTIVE
            user.updated_by_id = actor.user_id
            self._audit(AuditEventCode.STAFF_REACTIVATED, actor, user.id, request_id, {})
            return await self._fresh(user)

        return await self._unit_of_work(work)

    async def revoke_sessions(
        self, actor: Actor, user_id: uuid.UUID, *, request_id: str | None = None
    ) -> int:
        require_permissions(actor, Permission.STAFF_REVOKE_SESSIONS)

        async def work() -> int:
            user = await self._get(user_id, for_update=True)
            revoked = await invalidate_user_sessions(
                self._db, user.id, RevocationReason.ADMIN_REVOKED, self._clock()
            )
            self._audit(
                AuditEventCode.STAFF_SESSIONS_REVOKED,
                actor,
                user.id,
                request_id,
                {"revoked_sessions": revoked},
            )
            return revoked

        return await self._unit_of_work(work)

    # --- Helpers -------------------------------------------------------------------------

    async def _unit_of_work[T](self, work: Callable[[], Awaitable[T]]) -> T:
        try:
            result = await work()
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise
        return result

    async def _get(self, user_id: uuid.UUID, *, for_update: bool = False) -> User:
        user = await self._users.get_by_id(user_id, for_update=for_update)
        if user is None:
            raise StaffNotFoundError()
        return user

    async def _fresh(self, user: User) -> User:
        """Reload after the change so server-set values (updated_at, token_version) and
        roles are current without implicit I/O during serialization."""
        await self._db.flush()
        return await self._get(user.id)

    async def _roles(self, codes: list[str]) -> list[Role]:
        roles = await self._users.roles_by_code(codes)
        missing = sorted(set(codes) - {role.code for role in roles})
        if missing:
            raise UnknownRoleError(missing)
        return sorted(roles, key=lambda role: role.code)

    async def _ensure_another_administrator(self, user: User) -> None:
        if user.status == UserStatus.ACTIVE and not (
            await self._users.count_active_administrators(excluding=user.id)
        ):
            raise LastAdministratorError()

    async def _flush_unique_email(self) -> None:
        try:
            await self._db.flush()
        except IntegrityError as exc:
            # A concurrent request took the email between the check and the write.
            if "uq_users_email" in str(exc.orig):
                raise EmailAlreadyExistsError() from None
            raise

    def _audit(
        self,
        code: AuditEventCode,
        actor: Actor,
        target_id: uuid.UUID,
        request_id: str | None,
        metadata: dict[str, object],
    ) -> None:
        record_audit_event(
            self._db,
            code,
            actor_id=actor.user_id,
            request_id=request_id,
            entity_type=ENTITY_TYPE,
            entity_id=target_id,
            metadata=metadata,
        )
