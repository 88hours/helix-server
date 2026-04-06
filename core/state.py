"""
Redis state helpers for the Helix agent pipeline.

Incident state keys (7-day TTL, namespaced by incident_id):

    helix:incident:{id}:crash_report   — CrashReport (JSON)
    helix:incident:{id}:test_case      — QAResult (JSON)
    helix:incident:{id}:pr             — PRResult (JSON)
    helix:incident:{id}:status         — current pipeline stage (string)
    helix:incident:{id}:iterations     — Dev Agent retry count (integer)

User state keys (no TTL — permanent user configuration):

    helix:user:{sub}:repos             — JSON list of RepoConfig

Agents never access Redis keys directly — they call the typed read/write
functions here.

Usage:
    import redis.asyncio as redis
    from core.state import write_crash_report, read_crash_report

    client = redis.from_url(os.environ["REDIS_URL"])
    await write_crash_report(client, report)
    report = await read_crash_report(client, incident_id)
"""

import json
import logging
from typing import Optional

import redis.asyncio as redis

from core.models import CrashReport, PRResult, QAResult, RepoConfig

logger = logging.getLogger(__name__)

# All incident keys expire after 7 days.
_TTL_SECONDS = 7 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# Key builders
# ---------------------------------------------------------------------------

def _key(incident_id: str, suffix: str) -> str:
    """Build a namespaced Redis key for the given incident and data type."""
    return f"helix:incident:{incident_id}:{suffix}"


# ---------------------------------------------------------------------------
# Crash report
# ---------------------------------------------------------------------------

async def write_crash_report(client: redis.Redis, report: CrashReport) -> None:
    """
    Persist a CrashReport to Redis.

    Serialises the model to JSON and stores it at:
        helix:incident:{incident_id}:crash_report

    Args:
        client: Async Redis client.
        report: The CrashReport produced by the Crash Handler Agent.
    """
    key = _key(report.incident_id, "crash_report")
    await client.set(key, report.model_dump_json(), ex=_TTL_SECONDS)
    logger.info("crash_report written", extra={"incident_id": report.incident_id, "key": key})


async def read_crash_report(client: redis.Redis, incident_id: str) -> Optional[CrashReport]:
    """
    Read a CrashReport from Redis.

    Args:
        client: Async Redis client.
        incident_id: The incident to look up.

    Returns:
        The CrashReport, or None if the key does not exist (expired or never written).
    """
    key = _key(incident_id, "crash_report")
    raw = await client.get(key)
    if raw is None:
        logger.warning("crash_report not found", extra={"incident_id": incident_id, "key": key})
        return None
    try:
        return CrashReport.model_validate_json(raw)
    except Exception:
        logger.warning(
            "crash_report schema mismatch — skipping stale entry",
            extra={"incident_id": incident_id},
        )
        return None


# ---------------------------------------------------------------------------
# QA result (test case)
# ---------------------------------------------------------------------------

async def write_qa_result(client: redis.Redis, result: QAResult) -> None:
    """
    Persist a QAResult to Redis.

    Stored at: helix:incident:{incident_id}:test_case

    Args:
        client: Async Redis client.
        result: The QAResult produced by the QA Agent.
    """
    key = _key(result.incident_id, "test_case")
    await client.set(key, result.model_dump_json(), ex=_TTL_SECONDS)
    logger.info("qa_result written", extra={"incident_id": result.incident_id, "key": key})


async def read_qa_result(client: redis.Redis, incident_id: str) -> Optional[QAResult]:
    """
    Read a QAResult from Redis.

    Args:
        client: Async Redis client.
        incident_id: The incident to look up.

    Returns:
        The QAResult, or None if the key does not exist.
    """
    key = _key(incident_id, "test_case")
    raw = await client.get(key)
    if raw is None:
        logger.warning("qa_result not found", extra={"incident_id": incident_id, "key": key})
        return None
    return QAResult.model_validate_json(raw)


# ---------------------------------------------------------------------------
# PR result
# ---------------------------------------------------------------------------

async def write_pr_result(client: redis.Redis, result: PRResult) -> None:
    """
    Persist a PRResult to Redis.

    Stored at: helix:incident:{incident_id}:pr

    Args:
        client: Async Redis client.
        result: The PRResult produced by the Dev Agent.
    """
    key = _key(result.incident_id, "pr")
    await client.set(key, result.model_dump_json(), ex=_TTL_SECONDS)
    logger.info("pr_result written", extra={"incident_id": result.incident_id, "key": key})


async def read_pr_result(client: redis.Redis, incident_id: str) -> Optional[PRResult]:
    """
    Read a PRResult from Redis.

    Args:
        client: Async Redis client.
        incident_id: The incident to look up.

    Returns:
        The PRResult, or None if the key does not exist.
    """
    key = _key(incident_id, "pr")
    raw = await client.get(key)
    if raw is None:
        logger.warning("pr_result not found", extra={"incident_id": incident_id, "key": key})
        return None
    return PRResult.model_validate_json(raw)


# ---------------------------------------------------------------------------
# Pipeline status
# ---------------------------------------------------------------------------

async def write_status(client: redis.Redis, incident_id: str, status: str) -> None:
    """
    Update the current pipeline stage for an incident.

    Stored at: helix:incident:{incident_id}:status

    Args:
        client: Async Redis client.
        incident_id: The incident being updated.
        status: A short string describing the current stage, e.g. "crash_analysed",
                "test_case_generated", "pr_created", "quality_approved".
    """
    key = _key(incident_id, "status")
    await client.set(key, status, ex=_TTL_SECONDS)
    logger.info("status updated", extra={"incident_id": incident_id, "status": status})


async def read_status(client: redis.Redis, incident_id: str) -> Optional[str]:
    """
    Read the current pipeline status for an incident.

    Args:
        client: Async Redis client.
        incident_id: The incident to look up.

    Returns:
        The status string, or None if not yet set.
    """
    key = _key(incident_id, "status")
    raw = await client.get(key)
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else raw


# ---------------------------------------------------------------------------
# Dev Agent iteration counter
# ---------------------------------------------------------------------------

async def increment_iterations(client: redis.Redis, incident_id: str) -> int:
    """
    Increment the Dev Agent retry counter and return the new value.

    The counter starts at 0 and is incremented before each fix attempt,
    so the first attempt returns 1. The Dev Agent stops at 3.

    Stored at: helix:incident:{incident_id}:iterations

    Args:
        client: Async Redis client.
        incident_id: The incident being retried.

    Returns:
        The new iteration count after incrementing.
    """
    key = _key(incident_id, "iterations")
    count = await client.incr(key)
    await client.expire(key, _TTL_SECONDS)
    logger.info("iteration incremented", extra={"incident_id": incident_id, "iterations": count})
    return count


async def read_iterations(client: redis.Redis, incident_id: str) -> int:
    """
    Read the current Dev Agent iteration count for an incident.

    Args:
        client: Async Redis client.
        incident_id: The incident to look up.

    Returns:
        The current iteration count, or 0 if the key does not exist.
    """
    key = _key(incident_id, "iterations")
    raw = await client.get(key)
    if raw is None:
        return 0
    return int(raw)


# ---------------------------------------------------------------------------
# User repo configuration
# ---------------------------------------------------------------------------

def _user_repos_key(user_id: str) -> str:
    """Build the Redis key for a user's repo configuration list."""
    return f"helix:user:{user_id}:repos"


async def read_user_repos(client: redis.Redis, user_id: str) -> list[RepoConfig]:
    """
    Read all repo configs for a user.

    Stored at: helix:user:{user_id}:repos (no TTL — permanent user data).

    Args:
        client:  Async Redis client.
        user_id: Auth0 subject claim, e.g. "github|12345678".

    Returns:
        List of RepoConfig, empty if the user has not configured any repos.
    """
    key = _user_repos_key(user_id)
    raw = await client.get(key)
    if raw is None:
        return []
    try:
        data = json.loads(raw)
        return [RepoConfig.model_validate(r) for r in data]
    except Exception:
        logger.warning("user repos schema mismatch — returning empty list", extra={"user_id": user_id})
        return []


async def write_user_repos(client: redis.Redis, user_id: str, repos: list[RepoConfig]) -> None:
    """
    Persist the full list of repo configs for a user.

    Overwrites the existing list atomically.  Callers are responsible for
    reading, modifying, and writing back the list (read-modify-write pattern).

    Args:
        client:  Async Redis client.
        user_id: Auth0 subject claim, e.g. "github|12345678".
        repos:   Full list of RepoConfig to persist.
    """
    key = _user_repos_key(user_id)
    payload = json.dumps([r.model_dump(mode="json") for r in repos])
    await client.set(key, payload)
    logger.info("user repos written", extra={"user_id": user_id, "count": len(repos)})
