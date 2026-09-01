"""Aggregate all v1 API routers."""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.knowledge_bases import router as kbs_router
from app.api.v1.documents import router as documents_router
from app.api.v1.chat import router as chat_router
from app.api.v1.search import router as search_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.eval import router as eval_router
from app.api.v1.config import router as config_router
from app.api.v1.llm_profiles import router as llm_profiles_router
from app.api.v1.monitoring import router as monitoring_router
from app.api.v1.exercises import router as exercises_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(kbs_router)
api_router.include_router(documents_router)
api_router.include_router(chat_router)
api_router.include_router(search_router)
api_router.include_router(feedback_router)
api_router.include_router(eval_router)
api_router.include_router(config_router)
api_router.include_router(llm_profiles_router)
api_router.include_router(monitoring_router)
api_router.include_router(exercises_router)
