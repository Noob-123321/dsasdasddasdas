"""Run the background poller as an independent process."""
from ..config import get_settings
from ..db import SessionLocal
from ..poller import Poller

if __name__ == "__main__":
    poller = Poller(SessionLocal, get_settings())
    poller.run()
