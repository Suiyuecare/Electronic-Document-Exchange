import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import Handler, USE_SUPABASE, migrate


if not USE_SUPABASE:
    migrate()


class handler(Handler):
    """Vercel Python runtime entrypoint."""
