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

app = FastAPI(title="올더뮤 검수봇 v3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    # Slack/Figma 모두 읽기+DB 적재만 수행 (외부에 메시지 전송 없음)
    try:
        import asyncio

        asyncio.create_task(poll_slack_loop())
    except Exception as e:
        print(f"[startup] failed to start slack poll loop: {e}")
    try:
        import asyncio

        asyncio.create_task(figma_poll_loop())
    except Exception as e:
        print(f"[startup] failed to start figma poll loop: {e}")


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

    uvicorn.run(app, host="0.0.0.0", port=5000)
