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
