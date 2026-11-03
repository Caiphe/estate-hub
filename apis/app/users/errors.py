class StaffServiceError(Exception):
    """A staff-management business failure with a stable public code and safe message."""

    code = "staff_error"
    message = "The staff change could not be made."

    def __init__(self, fields: dict[str, list[str]] | None = None) -> None:
        super().__init__(self.code)
        self.fields = fields


class StaffNotFoundError(StaffServiceError):
    code = "not_found"
    message = "Staff member not found."


class EmailAlreadyExistsError(StaffServiceError):
    code = "email_already_exists"
    message = "A staff member with this email already exists."

    def __init__(self) -> None:
        super().__init__({"email": [self.message]})


class UnknownRoleError(StaffServiceError):
    code = "validation_error"
    message = "The request contains invalid data."

    def __init__(self, codes: list[str]) -> None:
        super().__init__({"roles": [f"Unknown role code: {code}." for code in codes]})


class LastAdministratorError(StaffServiceError):
    code = "last_administrator"
    message = "At least one active administrator must remain."


class SelfLockoutError(StaffServiceError):
    code = "self_lockout"
    message = "You cannot disable your own account or remove your own administrator role."
