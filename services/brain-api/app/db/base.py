# This module is imported by Alembic's env.py to ensure all models are registered
# before autogenerate runs. Do not import Base from here — use app.db.base_class.

from app.db.base_class import Base  # noqa: F401
from app.models import agent, note, note_link, team, user  # noqa: F401
