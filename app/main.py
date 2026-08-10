from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db, poller, profit_taker
from app.auth import BasicAuthMiddleware
from app.routes import news, trading, watchlist

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

NO_CACHE_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}


class NoCacheStaticFiles(StaticFiles):
    """Plain StaticFiles lets browsers reuse a locally cached copy of e.g.
    app.js indefinitely without even checking the server -- that's why a
    plain refresh can keep showing an old version after a deploy. This
    forces the browser to always revalidate (via the ETag/Last-Modified
    StaticFiles already sends), so a normal refresh is enough to pick up
    the latest file -- no hard refresh needed."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE_HEADERS)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    news_task = asyncio.create_task(poller.run_forever())
    profit_task = asyncio.create_task(profit_taker.run_forever())
    yield
    news_task.cancel()
    profit_task.cancel()


app = FastAPI(title="FinSignal", lifespan=lifespan)
app.add_middleware(BasicAuthMiddleware)

app.include_router(news.router, prefix="/api")
app.include_router(trading.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")

app.mount("/static", NoCacheStaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html", headers=NO_CACHE_HEADERS)


@app.get("/trades")
async def trades_page():
    return FileResponse("static/trades.html", headers=NO_CACHE_HEADERS)
