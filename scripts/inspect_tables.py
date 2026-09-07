import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import engine
from sqlalchemy import text

async def inspect():
    async with engine.connect() as conn:
        res = await conn.execute(text("""
            SELECT atttypmod 
            FROM pg_attribute 
            WHERE attrelid = 'knowledge_chunks'::regclass AND attname = 'embedding';
        """))
        dim = res.scalar()
        print(f"knowledge_chunks.embedding typmod/dimension: {dim}")

if __name__ == "__main__":
    asyncio.run(inspect())
