from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import get_settings
from app.seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.production and (
        settings.jwt_secret.startswith("development") or settings.admin_password == "change-me-now"
    ):
        raise RuntimeError("生产环境必须设置安全的 JWT_SECRET 和管理员密码")
    seed()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router)

static_dir = Path(__file__).parent / "static"
if (static_dir / "assets").exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "前端尚未构建。开发模式请运行 pnpm dev。"}

