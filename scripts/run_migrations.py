import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

async def run_sql_file(conn, file_path: Path):
    print(f"Executing migration: {file_path.name} ...")
    content = file_path.read_text(encoding="utf-8")
    
    # Get raw asyncpg connection for multi-statement execution
    raw_conn = await conn.get_raw_connection()
    await raw_conn.driver_connection.execute(content)
    print(f"Completed {file_path.name} successfully.")

async def main():
    async with engine.begin() as conn:
        for sql_name in ["004_features_completion.sql"]:
            sql_file = MIGRATIONS_DIR / sql_name
            if sql_file.exists():
                await run_sql_file(conn, sql_file)
            else:
                print(f"Warning: {sql_name} not found.")
    print("All base migrations executed successfully on Supabase!")

if __name__ == "__main__":
    asyncio.run(main())
