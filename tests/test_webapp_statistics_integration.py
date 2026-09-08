"""GYM-19: integration tests for the `/api/statistics/*` endpoints, hit as
real HTTP requests through `create_webapp()` via aiohttp's test client.

Each endpoint's own business logic (aggregation, PR math, pagination, …) is
already unit-tested against the handler function directly in its own
ticket's test file (`test_webapp_volume_statistics.py`,
`test_webapp_records.py`, `test_webapp_history.py`, …) — that's this
project's convention for a task's DoD, not duplicated here. This file
instead covers what only shows up once requests go through the real
`aiohttp.web.Application`: routing (including the `{session_id}` path
param and method restrictions), the `Authorization` header / query-string
wiring end to end, and one full "log a workout, then read it back through
every statistics endpoint" flow tying the endpoints together.
"""

from datetime import datetime

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.database.models import Base
from src.database.repository import UserRepository, WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import create_webapp
from tests.test_webapp_auth import build_init_data

# settings.timezone defaults to Europe/Kyiv (src/config.py).

STATISTICS_GET_ENDPOINTS = (
    '/api/statistics/volume',
    '/api/statistics/summary',
    '/api/statistics/exercises',
    '/api/statistics/exercise-progress?exercise=Жим+лежачи',
    '/api/statistics/records',
    '/api/statistics/history',
)


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def client():
    app = create_webapp()
    async with TestClient(TestServer(app)) as test_client:
        yield test_client


async def _make_user(username: str, telegram_id: int):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name='Test', username=username
        )
        await session.commit()
        return user


async def _add_completed_session(
    user_id, performed_at: datetime, sets: list[dict], **kwargs
):
    async with async_session_maker() as session:
        workout_session = await WorkoutSessionRepository(
            session
        ).create_session_with_sets(
            user_id=user_id, performed_at=performed_at, sets=sets, **kwargs
        )
        await session.commit()
        return workout_session.id


def _auth_header(telegram_id: int) -> dict:
    return {'Authorization': build_init_data({'id': telegram_id, 'first_name': 'Test'})}


class TestAuthWiring:
    """Every /api/statistics/* endpoint rejects a real request with no (or
    a bad) Authorization header — same check as the unit tests, but through
    the actual aiohttp routing/middleware stack rather than a handler call.
    """

    @pytest.mark.parametrize('path', STATISTICS_GET_ENDPOINTS)
    async def test_missing_auth_header_returns_401(self, client, path):
        response = await client.get(path)
        assert response.status == 401

    async def test_history_detail_missing_auth_header_returns_401(self, client):
        response = await client.get('/api/statistics/history/1')
        assert response.status == 401

    @pytest.mark.parametrize('path', STATISTICS_GET_ENDPOINTS)
    async def test_garbage_auth_header_returns_401(self, client, path):
        response = await client.get(path, headers={'Authorization': 'garbage'})
        assert response.status == 401


class TestRoutingWiring:
    async def test_unknown_route_returns_404(self, client):
        await _make_user('lifter', telegram_id=1)
        response = await client.get(
            '/api/statistics/nonexistent', headers=_auth_header(1)
        )
        assert response.status == 404

    async def test_unsupported_method_returns_405(self, client):
        await _make_user('lifter', telegram_id=1)
        response = await client.post(
            '/api/statistics/volume', headers=_auth_header(1)
        )
        assert response.status == 405

    async def test_history_detail_path_param_is_parsed_from_url(self, client):
        user = await _make_user('lifter', telegram_id=1)
        session_id = await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                'exercise_name': 'Жим лежачи', 'muscle_group': 'Груди',
                'set_number': 1, 'weight': 80.0, 'reps': 5,
            }],
        )

        response = await client.get(
            f'/api/statistics/history/{session_id}', headers=_auth_header(1)
        )
        payload = await response.json()

        assert response.status == 200
        assert payload['data']['session_id'] == session_id

    async def test_history_detail_non_numeric_path_segment_returns_400(self, client):
        await _make_user('lifter', telegram_id=1)
        response = await client.get(
            '/api/statistics/history/not-a-number', headers=_auth_header(1)
        )
        assert response.status == 400

    async def test_history_detail_unknown_id_returns_404(self, client):
        await _make_user('lifter', telegram_id=1)
        response = await client.get(
            '/api/statistics/history/999999', headers=_auth_header(1)
        )
        assert response.status == 404


class TestUserParamWiring:
    """The `?user=` trainer-viewing-a-client query param, decoded from a
    real URL rather than constructed in-process.
    """

    async def test_user_param_round_trips_over_http(self, client):
        owner = await _make_user('lifter', telegram_id=1)
        await _make_user('trainer', telegram_id=999)
        await _add_completed_session(
            owner.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                'exercise_name': 'Жим лежачи', 'muscle_group': 'Груди',
                'set_number': 1, 'weight': 60.0, 'reps': 10,
            }],
        )

        response = await client.get(
            '/api/statistics/history?user=lifter', headers=_auth_header(999)
        )
        payload = await response.json()

        assert response.status == 200
        assert len(payload['data']) == 1


class TestFullFlowAcrossEndpoints:
    """Log one workout through the real POST /api/workout/log endpoint,
    then read it back through every /api/statistics/* endpoint — checking
    the same numbers agree with each other end to end, not re-deriving
    each endpoint's own aggregation rules (already unit-tested per task).
    """

    async def test_logged_workout_is_consistent_across_all_endpoints(self, client):
        owner = await _make_user('lifter', telegram_id=1)

        log_response = await client.post(
            '/api/workout/log',
            headers=_auth_header(1),
            json={
                'user': 'lifter',
                'day': 1,
                'muscle': 'Груди',
                'duration_seconds': 1800,
                'exercises': [{
                    'exercise': 'Жим лежачи',
                    'muscle_group': 'Груди',
                    'planned_sets_reps': '3x10',
                    'sets': [
                        {'set': 1, 'weight': 80, 'reps': 5},
                        {'set': 2, 'weight': 80, 'reps': 4},
                    ],
                }],
            },
        )
        assert log_response.status == 200
        assert (await log_response.json())['success'] is True

        expected_volume = 80 * 5 + 80 * 4

        summary_response = await client.get(
            '/api/statistics/summary?period=all', headers=_auth_header(1)
        )
        summary = (await summary_response.json())['data']
        assert summary_response.status == 200
        assert summary['workouts_count'] == 1
        assert summary['total_volume'] == expected_volume
        assert summary['most_trained_muscle'] == 'Груди'

        volume_response = await client.get(
            '/api/statistics/volume?period=all', headers=_auth_header(1)
        )
        volume = (await volume_response.json())['data']
        assert volume['total_volume'] == expected_volume
        assert volume['by_muscle'] == [
            {'muscle_group': 'Груди', 'volume': expected_volume, 'sets_count': 2}
        ]

        exercises_response = await client.get(
            '/api/statistics/exercises', headers=_auth_header(1)
        )
        exercises = (await exercises_response.json())['data']
        assert exercises == [
            {'exercise_name': 'Жим лежачи', 'muscle_group': 'Груди'}
        ]

        progress_response = await client.get(
            '/api/statistics/exercise-progress?exercise=Жим лежачи',
            headers=_auth_header(1),
        )
        progress = (await progress_response.json())['data']
        assert len(progress) == 1
        assert progress[0]['top_set'] == {'weight': 80.0, 'reps': 5}
        assert progress[0]['total_volume'] == expected_volume

        records_response = await client.get(
            '/api/statistics/records', headers=_auth_header(1)
        )
        records = (await records_response.json())['data']
        assert len(records) == 1
        assert records[0]['exercise'] == 'Жим лежачи'
        assert records[0]['max_weight']['weight'] == 80.0
        assert records[0]['max_weight']['reps'] == 5

        history_response = await client.get(
            '/api/statistics/history', headers=_auth_header(1)
        )
        history = (await history_response.json())['data']
        assert len(history) == 1
        assert history[0]['total_volume'] == expected_volume
        assert history[0]['sets_count'] == 2
        assert history[0]['exercises_count'] == 1
        assert history[0]['duration_minutes'] == 30.0
        session_id = history[0]['session_id']

        detail_response = await client.get(
            f'/api/statistics/history/{session_id}', headers=_auth_header(1)
        )
        detail = (await detail_response.json())['data']
        assert detail['total_volume'] == expected_volume
        assert detail['exercises'] == [{
            'exercise': 'Жим лежачи',
            'muscle_group': 'Груди',
            'sets': [
                {'set': 1, 'weight': 80.0, 'reps': 5},
                {'set': 2, 'weight': 80.0, 'reps': 4},
            ],
        }]

        # Sanity: the session actually belongs to the logging user.
        async with async_session_maker() as session:
            db_session = await WorkoutSessionRepository(session).get_by_id(
                session_id
            )
            assert db_session.user_id == owner.id
