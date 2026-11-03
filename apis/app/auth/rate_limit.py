"""Fixed-window rate limiting with Redis counters shared by every API process."""

from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int


class RateLimitExceeded(Exception):
    def __init__(self, rule: RateLimitRule, retry_after: int, first: bool) -> None:
        super().__init__(rule.name)
        self.rule = rule
        self.retry_after = retry_after
        # True only for the first rejected request in a window, so audit events are
        # written once per key and window rather than once per flood request.
        self.first = first


class RateLimiterUnavailable(Exception):
    """Redis could not be reached; callers decide whether to fail open or closed."""


@dataclass(frozen=True, slots=True)
class AuthRateLimits:
    login_ip: RateLimitRule
    login_email: RateLimitRule
    refresh_ip: RateLimitRule
    password_change_ip: RateLimitRule
    password_change_user: RateLimitRule
    session_ip: RateLimitRule

    @classmethod
    def from_settings(cls, settings: Settings) -> AuthRateLimits:
        login_window = settings.auth_login_window_seconds
        change_limit = settings.auth_password_change_max_attempts
        change_window = settings.auth_password_change_window_seconds
        return cls(
            login_ip=RateLimitRule(
                "login:ip", settings.auth_login_max_attempts_per_ip, login_window
            ),
            login_email=RateLimitRule(
                "login:email", settings.auth_login_max_attempts_per_email, login_window
            ),
            refresh_ip=RateLimitRule(
                "refresh:ip",
                settings.auth_refresh_max_attempts_per_ip,
                settings.auth_refresh_window_seconds,
            ),
            password_change_ip=RateLimitRule("password:ip", change_limit, change_window),
            password_change_user=RateLimitRule("password:user", change_limit, change_window),
            session_ip=RateLimitRule(
                "session:ip",
                settings.auth_session_max_requests_per_ip,
                settings.auth_session_window_seconds,
            ),
        )


class RateLimiter:
    def __init__(self, redis: Redis, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix

    async def hit(self, rule: RateLimitRule, identifier: str) -> None:
        """Count one request and raise when it exceeds the rule.

        ``identifier`` must already be a keyed fingerprint: raw emails and IP addresses
        never appear in Redis keys. Counting happens before the request is processed, so
        concurrent requests cannot race past the limit.
        """
        key = f"{self._prefix}:{rule.name}:{identifier}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, rule.window_seconds, nx=True)
                pipe.ttl(key)
                count, _, ttl = await pipe.execute()
        except (RedisError, OSError) as exc:
            raise RateLimiterUnavailable(rule.name) from exc
        if count > rule.limit:
            retry_after = ttl if isinstance(ttl, int) and ttl > 0 else rule.window_seconds
            raise RateLimitExceeded(rule, retry_after, first=count == rule.limit + 1)
