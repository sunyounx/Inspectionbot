from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from db.database import init_db
from routers import approval
from routers import copybank
from routers import figma
from routers import files
from routers import gdrive, history, inspect, manual
from services.figma_polling import figma_poll_loop
from services.polling import poll_slack_loop


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(init_db)
    print("[startup] init_db ok", flush=True)

    poll_tasks: list[asyncio.Task[None]] = []
    try:
        poll_tasks.append(asyncio.create_task(poll_slack_loop()))
        poll_tasks.append(asyncio.create_task(figma_poll_loop()))
        print("[startup] poll loops started", flush=True)
    except Exception as e:
        print(f"[startup] failed to start poll loops: {e}", flush=True)

    yield

    for task in poll_tasks:
        task.cancel()
    if poll_tasks:
        await asyncio.gather(*poll_tasks, return_exceptions=True)


app = FastAPI(title="올더뮤 검수봇 v3", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(approval.router)
app.include_router(inspect.router)
app.include_router(history.router)
app.include_router(files.router)
app.include_router(gdrive.router)
app.include_router(figma.router)
app.include_router(copybank.router)
app.include_router(manual.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/admin")
def admin():
    return RedirectResponse(url="/static/admin.html")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "5000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
