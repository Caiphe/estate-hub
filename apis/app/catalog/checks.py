"""Check-constraint builders shared by catalog tables. Names follow the "ck" convention."""

from sqlalchemy import CheckConstraint


def normalized_check(column: str, *, optional: bool = False) -> CheckConstraint:
    """Not blank, trimmed, and without repeated whitespace (see ``normalize_label``)."""
    rule = f"char_length({column}) > 0 AND {column} = btrim({column}) AND {column} !~ '\\s\\s'"
    if optional:
        rule = f"{column} IS NULL OR ({rule})"
    return CheckConstraint(rule, name=f"{column}_normalized")


def not_blank_check(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IS NULL OR char_length(btrim({column})) > 0", name=f"{column}_not_blank"
    )


def non_negative_check(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} >= 0", name=f"{column}_non_negative")


def postal_code_check() -> CheckConstraint:
    return CheckConstraint(
        "postal_code IS NULL OR (postal_code = upper(btrim(postal_code)) "
        "AND char_length(postal_code) > 0)",
        name="postal_code_normalized",
    )


def country_code_check() -> CheckConstraint:
    return CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code_format")
