"""Tests for the /nutrition Mini App page shell, including GYM-15's
"Статистика" sub-tab and GYM-16's insight line.
"""

from aiohttp.test_utils import TestClient, TestServer

from src.webapp.server import create_webapp


class TestNutritionPage:
    async def test_served_at_nutrition_route(self):
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/nutrition')
            body = await response.text()

            assert response.status == 200
            assert response.content_type == 'text/html'
            # GYM-15's "Статистика" sub-tab: chart (vendored Chart.js,
            # GYM-17, not a CDN), period switcher, calorie/macro charts.
            assert 'Статистика' in body
            assert '/static/chart.umd.min.js' in body
            assert '/api/nutrition/statistics' in body
            assert 'statsPeriodSelector' in body
            assert 'caloriesTrendChart' in body
            assert 'macrosTrendChart' in body
            # GYM-16's insight line.
            assert 'statsInsight' in body
            assert 'avg_vs_goal' in body

    async def test_reads_telegram_webapp_js_like_other_pages(self):
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/nutrition')
            body = await response.text()

            assert 'https://telegram.org/js/telegram-web-app.js' in body

    async def test_photo_flow_has_a_distinct_daily_limit_message(self):
        """GYM-43: a 429 from POST /api/nutrition/meal/photo (daily
        recognition limit) gets its own message, not the generic
        "не вдалося розпізнати" shown for 502/503."""
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/nutrition')
            body = await response.text()

            assert "response.status === 429" in body
            assert 'Вичерпано денний ліміт фото-розпізнавань' in body


class TestWorkoutProgramDayCard:
    """GYM-44: the expandable "День N" card in the "Тренування" section,
    styled after /statistics's "Історія" cards. No JS runner in this
    environment (see GYM-22/25/26/30/31/37/41/46) — smoke-checks the
    served HTML/inline JS for the pieces the AC calls for, same approach
    as those tickets' tests.
    """

    async def test_history_style_card_markup_and_functions_are_present(self):
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/nutrition')
            body = await response.text()

            # CSS, copied from statistics.html's `.history-card*` under a
            # distinct `.program-day-card*` prefix — `.workout-day-card`
            # (GYM-40's "Тренування сьогодні" card) is left untouched.
            assert '.program-day-card {' in body
            assert '.program-day-card-header {' in body
            assert '.program-day-card.expanded .program-day-card-details {' in body
            assert '.program-day-card-chevron {' in body

            # Rendering functions.
            assert 'function renderProgramDayCard(day, exerciseList)' in body
            assert 'function renderProgramDayDetails(exerciseList)' in body
            assert 'function groupExercisesByMuscleGroup(exerciseList)' in body
            assert 'function countTotalSets(exerciseList)' in body
            assert 'const expandedProgramDays = new Set();' in body

            # Header contents: day title, muscle badges, summary, chevron,
            # add-exercise button, and the separate arrow that navigates
            # straight to /workout.
            assert 'program-day-card-title">День' in body
            assert 'program-day-card-muscle' in body
            assert 'вправ · ${totalSets} підходів' in body
            assert 'program-day-card-chevron">▾' in body
            assert 'program-day-card-add-btn">➕ Вправа' in body
            assert 'program-day-card-arrow">→' in body

            # Expanded details: "Почати тренування" and the ported "ⓘ"
            # exercise-details modal (GYM-31, previously workout.html-only).
            assert '🏋️ Почати тренування' in body
            assert 'async function showExerciseDetails(event, exerciseId)' in body
            assert 'showExerciseDetails(event, ${ex.exercise_id})' in body

    async def test_parse_sets_reps_matches_the_backend_separator_set(self):
        """GYM-46 sync: nutrition.html's own copy of parseSetsReps accepts
        the same separators as the backend/workout.html (`/`, `|`,
        `x`/`X`/`х`/`Х`), not just `/`/`x` like the pre-GYM-46 original."""
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/nutrition')
            body = await response.text()

            assert 'function parseSetsReps(setsReps)' in body
            assert r'/^(\d+)\s*[/|xXхХ]\s*(\d+)$/' in body
