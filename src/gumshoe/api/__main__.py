import uvicorn

from gumshoe.api.app import create_app
from gumshoe.config import get_settings
from gumshoe.stats import SqliteStatsStore


def main() -> None:
    settings = get_settings()
    app = create_app(SqliteStatsStore(settings.stats_db_path), settings=settings)
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
