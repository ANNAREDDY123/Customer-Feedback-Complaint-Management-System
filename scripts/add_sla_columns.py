
import sqlite3

from app.core.config import settings


def main():
    database_url = settings.database_url

    if not database_url.startswith("sqlite:///"):
        raise RuntimeError(
            "This migration script supports SQLite databases only."
        )

    database_path = database_url.removeprefix("sqlite:///")

    if database_path == ":memory:":
        raise RuntimeError(
            "An in-memory database cannot be migrated by this script."
        )

    connection = sqlite3.connect(database_path)

    columns_to_add = {
        "first_response_at": "DATETIME",
        "response_due_at": "DATETIME",
        "resolution_due_at": "DATETIME",
        "sla_response_breached_at": "DATETIME",
        "sla_resolution_breached_at": "DATETIME",
    }

    try:
        existing_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(complaints)"
            ).fetchall()
        }

        if not existing_columns:
            raise RuntimeError(
                "The complaints table was not found. "
                "Start the application or create the database first."
            )

        for column_name, column_type in columns_to_add.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE complaints "
                    f"ADD COLUMN {column_name} {column_type}"
                )
                print(f"Added column: {column_name}")
            else:
                print(f"Already exists: {column_name}")

        connection.commit()
        print("SLA schema update completed successfully.")

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
