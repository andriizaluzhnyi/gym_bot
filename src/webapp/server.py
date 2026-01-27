"""Web server for Telegram Mini App."""

import logging
from pathlib import Path

from aiohttp import web

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / 'templates'


async def nutrition_handler(request: web.Request) -> web.Response:
    """Serve the nutrition tracking Mini App."""
    html_path = TEMPLATES_DIR / 'nutrition.html'
    return web.FileResponse(html_path)


def create_webapp() -> web.Application:
    """Create and configure the web application."""
    app = web.Application()

    app.router.add_get('/nutrition', nutrition_handler)
    app.router.add_static('/static', TEMPLATES_DIR, name='static')

    return app


async def start_webapp(host: str = '0.0.0.0', port: int = 8080) -> web.AppRunner | None:
    """
    Start the web application server.

    Returns None if the server fails to start (e.g., port already in use).
    """
    app = create_webapp()
    runner = web.AppRunner(app)
    await runner.setup()

    try:
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f'Web server started at http://{host}:{port}')
        return runner
    except OSError as e:
        await runner.cleanup()
        logger.error(f'Failed to start web server on port {port}: {e}')
        return None


async def stop_webapp(runner: web.AppRunner) -> None:
    """Stop the web application server."""
    await runner.cleanup()
    logger.info('Web server stopped')
