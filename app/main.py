from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.market_scanner import router as market_scanner_router
from app.config import settings
from app.db import init_db
from app.robinhood.read_service import robinhood_read_service
from app.market_scanner.worker import market_scan_worker

app = FastAPI(title=settings.app_name)
app.include_router(router)
app.include_router(market_scanner_router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.on_event("startup")
async def startup() -> None:
    init_db()
    robinhood_read_service.start()
    await market_scan_worker.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await market_scan_worker.stop()
    await robinhood_read_service.stop()


@app.get("/")
def dashboard():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    return HTMLResponse(
        """
        <html>
          <body style="background:#080c13;color:#e7eaf0;font-family:system-ui;padding:40px">
            <h1>TradeHub</h1>
            <p>The frontend bundle has not been built yet.</p>
            <p>Run <code>docker compose up -d --build</code> or build the Vite frontend.</p>
          </body>
        </html>
        """,
        status_code=503,
    )


@app.get("/ready")
def ready():
    return {"ready": True}
