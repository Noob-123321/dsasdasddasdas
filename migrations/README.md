# Database migrations

The first local bootstrap uses SQLAlchemy `create_all` so the project can run
without a migration command. Production releases should add Alembic revisions
under `migrations/versions/` and run `python -m alembic upgrade head` before
starting the API and poller.
