"""Tests for GYM-28's `_resolve_program_owner` (src/webapp/server.py) —
the shared authorization helper behind every `/api/statistics/*` and
workout-program endpoint's `?user=` handling. Exercised directly here so
the full 403/404/self/admin matrix is covered once, precisely, instead of
duplicated across every endpoint's own test file (which each keep just
one "trainer view" happy-path test to prove the wiring, per this file).
"""

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import pytest

from src.database.models import Base
from src.database.repository import UserRepository
from src.database.session import async_session_maker, engine
from src.webapp.auth import TELEGRAM_USER_KEY
from src.webapp.server import _resolve_program_owner, settings


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(username: str | None, telegram_id: int):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name="Test", username=username
        )
        await session.commit()
        return user


def _mock_request(*, telegram_id: int) -> web.Request:
    """A request carrying `TELEGRAM_USER_KEY` directly, as `@webapp_auth`
    would have set it — `_resolve_program_owner` is called *after* that
    decorator in real handlers, so it reads from there, not from a raw
    `Authorization` header.
    """
    request = make_mocked_request("GET", "/api/statistics/volume")
    request[TELEGRAM_USER_KEY] = {"id": telegram_id, "first_name": "Test"}
    return request


class TestNoParamUser:
    async def test_defaults_to_the_caller(self):
        caller = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            owner = await _resolve_program_owner(session, _mock_request(telegram_id=1), None)

        assert not isinstance(owner, web.Response)
        assert owner.id == caller.id

    async def test_unregistered_caller_returns_404(self):
        async with async_session_maker() as session:
            owner = await _resolve_program_owner(
                session, _mock_request(telegram_id=404), None
            )

        assert isinstance(owner, web.Response)
        assert owner.status == 404


class TestParamUserIsSelf:
    async def test_own_username_is_always_allowed_even_for_a_non_admin(self):
        await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            owner = await _resolve_program_owner(
                session, _mock_request(telegram_id=1), "lifter"
            )

        assert not isinstance(owner, web.Response)
        assert owner.username == "lifter"


class TestParamUserIsSomeoneElse:
    async def test_non_admin_is_forbidden(self):
        await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)

        async with async_session_maker() as session:
            owner = await _resolve_program_owner(
                session, _mock_request(telegram_id=999), "lifter"
            )

        assert isinstance(owner, web.Response)
        assert owner.status == 403

    async def test_forbidden_even_when_the_target_username_does_not_exist(self):
        """A non-admin gets the same 403 whether or not `?user=` names a
        real account — the check happens before any lookup, so it can't be
        used to probe which usernames are registered."""
        await _make_user("lifter", telegram_id=1)

        async with async_session_maker() as session:
            owner = await _resolve_program_owner(
                session, _mock_request(telegram_id=1), "ghost"
            )

        assert isinstance(owner, web.Response)
        assert owner.status == 403

    async def test_admin_is_allowed(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_user_id", 999)
        target = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)

        async with async_session_maker() as session:
            owner = await _resolve_program_owner(
                session, _mock_request(telegram_id=999), "lifter"
            )

        assert not isinstance(owner, web.Response)
        assert owner.id == target.id

    async def test_admin_requesting_an_unknown_username_gets_404(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_user_id", 999)
        await _make_user("trainer", telegram_id=999)

        async with async_session_maker() as session:
            owner = await _resolve_program_owner(
                session, _mock_request(telegram_id=999), "ghost"
            )

        assert isinstance(owner, web.Response)
        assert owner.status == 404

    async def test_caller_without_a_username_is_not_treated_as_self(self):
        """A caller with no username set at all can't accidentally match
        `param_user` via a None == None comparison."""
        await _make_user(None, telegram_id=1)
        await _make_user("lifter", telegram_id=2)

        async with async_session_maker() as session:
            owner = await _resolve_program_owner(
                session, _mock_request(telegram_id=1), "lifter"
            )

        assert isinstance(owner, web.Response)
        assert owner.status == 403
