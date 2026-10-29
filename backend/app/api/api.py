from fastapi import APIRouter
from app.api.routes import auth, index, search, admin_patents

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(index.router)
api_router.include_router(search.router)
api_router.include_router(admin_patents.router)
