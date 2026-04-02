import os
import sqlite3
import logging
from mcp_server.schema import init_schema
from mcp_server.sample_data import insert_sample_data

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("DATABASE_PATH", "./ai_agent.db")
        self.conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)
        insert_sample_data(self.conn)
        logger.info("Database ready at %s", self.db_path)

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        if self.conn is None:
            raise RuntimeError("Database not initialized")
        cur = self.conn.execute(sql, params or [])
        return [dict(row) for row in cur.fetchall()]

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None
