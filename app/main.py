import asyncio
import sys
from contextlib import asynccontextmanager

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_tables
from app.routers import auth, billing, chat, documents, support


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(title="KORTEX API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(documents.router, prefix="/documents", tags=["documents"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(support.router, prefix="/support", tags=["support"])
app.include_router(billing.router, prefix="/api", tags=["billing"])


@app.get("/health")
async def health():
    from app.config import settings

    return {
        "status": "KORTEX is running",
        "llm_enabled": settings.llm_enabled,
        "llm_provider": settings.llm_provider,
        "gemini_enabled": settings.gemini_enabled,
        "claude_enabled": settings.claude_enabled,
    }
