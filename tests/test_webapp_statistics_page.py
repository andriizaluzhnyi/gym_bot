"""Tests for the /statistics Mini App page shell (GYM-3)."""

from aiohttp.test_utils import TestClient, TestServer

from src.webapp.server import create_webapp


class TestStatisticsPage:
    async def test_served_at_statistics_route(self):
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/statistics')
            body = await response.text()

            assert response.status == 200
            assert response.content_type == 'text/html'
            # The three tabs required by GYM-3's acceptance criteria.
            assert "Об'єм" in body
            assert 'Прогрес по вправі' in body
            assert 'Активність' in body
            # Chart.js is served from /static (vendored, GYM-17), not a CDN.
            assert '/static/chart.umd.min.js' in body
            # GYM-6's summary strip, always visible above the tabs.
            assert '/api/statistics/summary' in body
            assert 'summaryWorkouts' in body

    async def test_reads_telegram_webapp_js_like_other_pages(self):
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/statistics')
            body = await response.text()

            assert 'https://telegram.org/js/telegram-web-app.js' in body
