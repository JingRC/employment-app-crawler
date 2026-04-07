from fastapi import APIRouter

from app.api.routes import crawler, favorites, featured_companies, jobs, notifications

api_router = APIRouter()
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
api_router.include_router(featured_companies.router, prefix="/featured-companies", tags=["featured-companies"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(crawler.router, prefix="/crawler", tags=["crawler"])
