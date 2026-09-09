"""Tests for the /profile Mini App page shell, including GYM-42's
bidirectional calories ↔ БЖВ auto-recalculation.

Like `test_webapp_nutrition_page.py`, this is a smoke test on the served
HTML/inline JS — the repo has no JS unit-test runner, so the frontend
recalculation logic is exercised only indirectly here (that it's wired to
the right inputs/events) plus the 30/25/45% split math is covered
end-to-end by `test_webapp_user_settings.py` on the backend side
(`daily_calories` derived from БЖВ the same way, GYM-23).
"""

from aiohttp.test_utils import TestClient, TestServer

from src.webapp.server import create_webapp


class TestProfilePage:
    async def test_served_at_profile_route(self):
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/profile')
            body = await response.text()

            assert response.status == 200
            assert response.content_type == 'text/html'
            assert 'caloriesInput' in body
            assert 'proteinInput' in body
            assert 'fatsInput' in body
            assert 'carbsInput' in body

    async def test_reads_telegram_webapp_js_like_other_pages(self):
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/profile')
            body = await response.text()

            assert 'https://telegram.org/js/telegram-web-app.js' in body

    async def test_calories_input_wired_to_macro_recalculation(self):
        """GYM-42: editing "Калорії" redistributes БЖВ at the fixed
        30/25/45% split — same one "Взяти розраховані" (GYM-26) uses."""
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/profile')
            body = await response.text()

            assert 'MACRO_SPLIT' in body
            assert 'applyCaloriesToMacros' in body
            assert "caloriesInput.addEventListener('input'" in body

    async def test_macro_inputs_wired_to_calories_recalculation(self):
        """GYM-42: editing any of the three БЖВ fields sums them back into
        "Калорії" at 4/9/4 kcal/g, matching the backend's derivation of
        daily_calories from БЖВ (GYM-23)."""
        app = create_webapp()
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/profile')
            body = await response.text()

            assert 'protein * 4 + fats * 9 + carbs * 4' in body
            assert "[proteinInput, fatsInput, carbsInput].forEach((input) => {" in body
