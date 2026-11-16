"""Explicit PostgreSQL settings, independent of application startup and dotenv."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class DatabaseConfigurationError(ValueError):
    """Invalid database configuration; messages never include supplied values."""


@dataclass(frozen=True)
class DatabaseSettings:
    url: URL = field(repr=False)
    pool_size: int = 5
    max_overflow: int = 0
    pool_timeout_seconds: float = 5
    connect_timeout_seconds: int = 5


def load_database_settings(
    environ: Mapping[str, str] | None = None,
    *,
    url_variable: str = "DATABASE_URL",
) -> DatabaseSettings:
    """Read only the requested URL variable; never fall back to another database.

    URL passwords must be percent-encoded. A small query allowlist prevents libpq
    query parameters from overriding the validated host, timeout or UTC setting.
    """
    env = os.environ if environ is None else environ
    if url_variable not in {"DATABASE_URL", "TEST_DATABASE_URL"}:
        raise DatabaseConfigurationError("Unsupported database URL variable.") from None
    raw_url = env.get(url_variable, "")
    try:
        url = make_url(raw_url)
        if (
            url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}
            or not url.username or not url.host or not url.database
            or any(character.isspace() for character in url.host)
            or any(character in url.host for character in "@,/")
            or (url.port is not None and not 1 <= url.port <= 65535)
        ):
            raise ValueError
        allowed_query = {"sslmode", "sslrootcert", "sslcert", "sslkey", "application_name"}
        if set(url.query) - allowed_query or any(not isinstance(v, str) for v in url.query.values()):
            raise ValueError
        if "sslmode" in url.query and url.query["sslmode"] not in {
            "disable", "allow", "prefer", "require", "verify-ca", "verify-full"
        }:
            raise ValueError
        url = url.set(drivername="postgresql+psycopg")
    except (ArgumentError, ValueError, TypeError):
        raise DatabaseConfigurationError(
            f"{url_variable} must be a PostgreSQL URL with user, host and database; "
            "check URL encoding, port and supported TLS query parameters."
        ) from None

    def integer(name: str, default: int, minimum: int) -> int:
        try:
            result = int(env.get(name, str(default)))
            if result < minimum:
                raise ValueError
            return result
        except (TypeError, ValueError):
            raise DatabaseConfigurationError(f"{name} must be an integer >= {minimum}.") from None

    try:
        pool_timeout = float(env.get("DB_POOL_TIMEOUT_SECONDS", "5"))
        if not math.isfinite(pool_timeout) or pool_timeout <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise DatabaseConfigurationError("DB_POOL_TIMEOUT_SECONDS must be finite and positive.") from None

    return DatabaseSettings(
        url=url,
        pool_size=integer("DB_POOL_SIZE", 5, 1),
        max_overflow=integer("DB_MAX_OVERFLOW", 0, 0),
        pool_timeout_seconds=pool_timeout,
        connect_timeout_seconds=integer("DB_CONNECT_TIMEOUT_SECONDS", 5, 1),
    )
