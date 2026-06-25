from __future__ import annotations

from app.config import load_app_config
from app.storage import Storage


def main() -> None:
    config = load_app_config()
    storage = Storage(config.db_path)
    storage.init_db()
    print(f"SQLite 数据库已初始化: {config.db_path}")


if __name__ == "__main__":
    main()
