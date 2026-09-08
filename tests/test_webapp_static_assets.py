"""Tests for statically-served WebApp assets (GYM-17: vendored Chart.js)."""

from aiohttp.test_utils import TestClient, TestServer

from src.webapp.server import create_webapp


class TestChartJsStaticAsset:
    async def test_served_at_static_path(self):
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/static/chart.umd.min.js')
            body = await response.read()

            assert response.status == 200
            # Vendored (not a CDN redirect/proxy): served straight from disk
            # by the existing /static route, so it works even if a CDN is
            # blocked inside the Telegram WebView.
            assert b'Chart.js' in body[:400]
            assert len(body) > 100_000
