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

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/trades")
async def trades_page():
    return FileResponse("static/trades.html")
