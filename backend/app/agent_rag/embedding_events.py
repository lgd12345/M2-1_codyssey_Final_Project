from __future__ import annotations

from typing import Any, Callable

from app.agent_rag.db import connect_database


def record_embedding_error(event: dict[str, Any], *, database_url: str | None = None,
                           connect: Callable[..., Any] = connect_database) -> None:
    """Persist only content-free provider failure metadata in an independent short transaction."""
    connection = connect(database_url)
    try:
        with connection.transaction():
            connection.execute(
                """INSERT INTO rag_embedding_api_error(provider,model,operation,category,http_status,
                       retry_after_seconds,input_count)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (event["provider"], event["model"], event["operation"], event["category"],
                 event.get("http_status"), event.get("retry_after_seconds"), event["input_count"]),
            )
    finally:
        connection.close()
