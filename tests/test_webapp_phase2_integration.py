"""GYM-38: integration tests for this plan's ("Phase 2") endpoints, hit as
real HTTP requests through `create_webapp()` via aiohttp's test client —
same approach and rationale as GYM-19's
`test_webapp_statistics_integration.py` (see that file's module
docstring): each endpoint's own business logic (validation, aggregation,
...) is already unit-tested against the handler function directly in its
own ticket's test file, so this file isn't a second copy of that. It
covers what only shows up once requests go through the real
`aiohttp.web.Application` — routing, the `Authorization` header wired
through real middleware, `?user=` admin-gating over a real query string,
genuine multipart parsing — plus one full flow tying two sprints' worth
of tickets together end to end.

`/api/statistics/*` (Phase 1, GYM-19) isn't repeated here. The workout
session/log endpoints (`/api/workout/session/start`,
`/api/workout/session/exercise`, `/api/workout/log`,
`/api/workout/rest-timer`, `/api/workout/last-log`) predate this plan
(GYM-2c) and aren't "new" either — `/api/workout/log` only appears below
as a step in the full-flow scenario, which is what the AC asks for.
"""

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from src.database.models import Base
from src.database.repository import UserRepository
from src.database.session import async_session_maker, engine
from src.services.food_recognition import FoodEstimate
from src.webapp.server import create_webapp, settings
from tests.test_webapp_auth import build_init_data


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


async def _make_user(telegram_id: int, username: str | None = None):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name='Test', username=username
        )
        await session.commit()
        return user


def _auth_header(telegram_id: int) -> dict:
    return {'Authorization': build_init_data({'id': telegram_id, 'first_name': 'Test'})}


# Every "new" endpoint introduced by this plan (Phase 1's
# /api/statistics/* is GYM-19's job, above), grouped by HTTP method so a
# single auth-wiring loop can hit each with the right verb.
NEW_GET_ENDPOINTS = (
    '/api/user/settings',
    '/api/user/sync-settings',
    '/api/nutrition/daily',
    '/api/nutrition/meals',
    '/api/nutrition/statistics',
    '/api/workout/program',
    '/api/exercises',
    '/api/exercises/1',
    '/api/statistics/today',
)

NEW_POST_ENDPOINTS = (
    '/api/user/settings',
    '/api/user/sync-settings',
    '/api/nutrition/daily',
    '/api/nutrition/meal',
    '/api/nutrition/meal/photo',
    '/api/workout/program/exercise',
)

NEW_DELETE_ENDPOINTS = (
    '/api/nutrition/meal/1',
    '/api/workout/day?day=1',
    '/api/workout/exercise?day=1&exercise=X',
)


class TestAuthWiring:
    """Every new endpoint rejects a real request with no (or a bad)
    Authorization header — through the actual aiohttp routing stack,
    whether the handler uses `@webapp_auth` or (the older endpoints) its
    own inline `validate_telegram_webapp_data` check. No request body is
    attached; the auth check happens before any body/multipart parsing
    for every one of these handlers, so an absent/wrong-shaped body never
    gets the chance to matter.
    """

    @pytest.mark.parametrize('path', NEW_GET_ENDPOINTS)
    async def test_get_missing_auth_header_returns_401(self, client, path):
        response = await client.get(path)
        assert response.status == 401

    @pytest.mark.parametrize('path', NEW_GET_ENDPOINTS)
    async def test_get_garbage_auth_header_returns_401(self, client, path):
        response = await client.get(path, headers={'Authorization': 'garbage'})
        assert response.status == 401

    @pytest.mark.parametrize('path', NEW_POST_ENDPOINTS)
    async def test_post_missing_auth_header_returns_401(self, client, path):
        response = await client.post(path)
        assert response.status == 401

    @pytest.mark.parametrize('path', NEW_DELETE_ENDPOINTS)
    async def test_delete_missing_auth_header_returns_401(self, client, path):
        response = await client.delete(path)
        assert response.status == 401


class TestRoutingWiring:
    async def test_unknown_route_returns_404(self, client):
        await _make_user(1)
        response = await client.get(
            '/api/nutrition/nonexistent', headers=_auth_header(1)
        )
        assert response.status == 404

    async def test_unsupported_method_returns_405(self, client):
        await _make_user(1)
        response = await client.delete(
            '/api/user/settings', headers=_auth_header(1)
        )
        assert response.status == 405

    async def test_exercise_detail_path_param_is_parsed_from_url(self, client):
        await _make_user(1)
        add_response = await client.post(
            '/api/workout/program/exercise',
            headers=_auth_header(1),
            json={
                'day': 1, 'muscle_group': '🏋️ Груди',
                'exercise': 'Жим лежачи', 'sets_reps': '3/10',
            },
        )
        exercise_id = (await add_response.json())['data']['exercise_id']

        response = await client.get(
            f'/api/exercises/{exercise_id}', headers=_auth_header(1)
        )
        payload = await response.json()

        assert response.status == 200
        assert payload['data']['name'] == 'Жим лежачи'

    async def test_exercise_detail_non_numeric_path_segment_returns_400(self, client):
        await _make_user(1)
        response = await client.get(
            '/api/exercises/not-a-number', headers=_auth_header(1)
        )
        assert response.status == 400


class TestWorkoutProgramOwnershipWiring:
    """`?user=`/body `user` for someone else requires the caller to be an
    admin (`_resolve_program_owner`, GYM-28) — checked over a real query
    string/JSON body for every workout-program endpoint that accepts it.
    """

    async def test_get_program_for_another_user_returns_403(self, client):
        await _make_user(1, username='lifter')
        await _make_user(999, username='trainer')

        response = await client.get(
            '/api/workout/program?user=lifter', headers=_auth_header(999)
        )
        assert response.status == 403

    async def test_delete_day_for_another_user_returns_403(self, client):
        await _make_user(1, username='lifter')
        await _make_user(999, username='trainer')

        response = await client.delete(
            '/api/workout/day?day=1&user=lifter', headers=_auth_header(999)
        )
        assert response.status == 403

    async def test_delete_exercise_for_another_user_returns_403(self, client):
        await _make_user(1, username='lifter')
        await _make_user(999, username='trainer')

        response = await client.delete(
            '/api/workout/exercise?day=1&exercise=X&user=lifter',
            headers=_auth_header(999),
        )
        assert response.status == 403

    async def test_add_program_exercise_for_another_user_returns_403(self, client):
        await _make_user(1, username='lifter')
        await _make_user(999, username='trainer')

        response = await client.post(
            '/api/workout/program/exercise',
            headers=_auth_header(999),
            json={
                'user': 'lifter', 'day': 1, 'muscle_group': '🏋️ Груди',
                'exercise': 'Жим лежачи', 'sets_reps': '3/10',
            },
        )
        assert response.status == 403

    async def test_admin_can_add_to_another_users_program(self, client, monkeypatch):
        monkeypatch.setattr(settings, 'admin_user_id', 999)
        owner = await _make_user(1, username='lifter')
        await _make_user(999, username='trainer')

        response = await client.post(
            '/api/workout/program/exercise',
            headers=_auth_header(999),
            json={
                'user': 'lifter', 'day': 1, 'muscle_group': '🏋️ Груди',
                'exercise': 'Жим лежачи', 'sets_reps': '3/10',
            },
        )
        assert response.status == 200

        program_response = await client.get(
            '/api/workout/program?user=lifter', headers=_auth_header(999)
        )
        assert len((await program_response.json())['data']['exercises']) == 1
        assert owner.username == 'lifter'  # sanity: same owner we queried


class TestMealPhotoMultipartWiring:
    """`POST /api/nutrition/meal/photo` through a genuine multipart
    request body (`recognize_food` itself is mocked — its OpenAI-calling
    behavior has its own full test suite in `test_food_recognition.py`;
    the endpoint's own validation/error-mapping is covered end to end in
    `test_webapp_recognize_meal_photo.py`). This class just confirms the
    route is wired correctly under `create_webapp()`.
    """

    async def test_multipart_upload_is_parsed_and_returns_the_estimate(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(settings, 'openai_api_key', 'test-key')
        await _make_user(1)

        estimate = FoodEstimate(
            meal_name='Плов', portion_grams=300, protein=20, fats=15,
            carbs=60, calories=455, confidence='medium', notes='',
        )
        form = FormData()
        form.add_field(
            'photo', b'\xff\xd8\xff fake jpeg bytes',
            filename='meal.jpg', content_type='image/jpeg',
        )

        with patch(
            'src.webapp.server.recognize_food',
            new_callable=AsyncMock, return_value=estimate,
        ):
            response = await client.post(
                '/api/nutrition/meal/photo', data=form, headers=_auth_header(1)
            )

        assert response.status == 200
        payload = await response.json()
        assert payload['data']['meal_name'] == 'Плов'
        assert payload['data']['calories'] == 455


class TestFullFlowAddProgramExerciseThenLogItAndSeeItInStatistics:
    """AC's named scenario: add an exercise via
    `POST /api/workout/program/exercise` -> see it in
    `GET /api/workout/program` -> log a set for it via the (pre-existing)
    `POST /api/workout/log` -> see it in `GET /api/statistics/exercises` —
    tying GYM-30 (WebApp program editing) back into GYM-5a's statistics
    pipeline, which only ever looked at *logged* sets, never the program
    itself.
    """

    async def test_full_flow(self, client):
        await _make_user(1, username='lifter')

        add_response = await client.post(
            '/api/workout/program/exercise',
            headers=_auth_header(1),
            json={
                'day': 1, 'muscle_group': '🏋️ Груди',
                'exercise': 'Жим лежачи', 'sets_reps': '3/10',
            },
        )
        assert add_response.status == 200
        added = (await add_response.json())['data']
        assert added['exercise'] == 'Жим лежачи'

        program_response = await client.get(
            '/api/workout/program?day=1', headers=_auth_header(1)
        )
        program = (await program_response.json())['data']['exercises']
        assert [e['exercise'] for e in program] == ['Жим лежачи']

        log_response = await client.post(
            '/api/workout/log',
            headers=_auth_header(1),
            json={
                'user': 'lifter', 'day': 1, 'muscle': '🏋️ Груди',
                'duration_seconds': 1200,
                'exercises': [{
                    'exercise': 'Жим лежачи', 'muscle_group': '🏋️ Груди',
                    'planned_sets_reps': '3/10',
                    'sets': [{'set': 1, 'weight': 60, 'reps': 10}],
                }],
            },
        )
        assert log_response.status == 200
        assert (await log_response.json())['success'] is True

        stats_response = await client.get(
            '/api/statistics/exercises', headers=_auth_header(1)
        )
        exercises = (await stats_response.json())['data']
        assert exercises == [
            {'exercise_name': 'Жим лежачи', 'muscle_group': '🏋️ Груди'}
        ]
