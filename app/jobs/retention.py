"""Run the retention cleanup once (schedule externally in production)."""
from ..db import SessionLocal, init_db
from ..services.retention import prune

if __name__ == "__main__":
    init_db()
    with SessionLocal() as db:
        print(prune(db))
