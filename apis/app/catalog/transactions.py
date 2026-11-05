from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession


async def run_in_transaction[T](db: AsyncSession, work: Callable[[], Awaitable[T]]) -> T:
    """Commit ``work``'s changes, or roll all of them back if anything fails.

    Audit events are added inside ``work``, so a failed change leaves no success event.
    Errors are re-raised unchanged; callers translate only the ones they expect.
    """
    try:
        result = await work()
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    return result
