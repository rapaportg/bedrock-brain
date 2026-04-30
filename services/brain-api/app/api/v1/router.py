from fastapi import APIRouter

from app.api.v1 import agents, notes, teams

router = APIRouter(prefix="/v1")
router.include_router(notes.router)
router.include_router(agents.router)
router.include_router(teams.router)
