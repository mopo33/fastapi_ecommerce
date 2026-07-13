import asyncio
from sqlalchemy import text
from app.db_depends import get_async_db

async def clear_users():
    async for db in get_async_db():
        # Удаляем всех пользователей
        await db.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
        await db.commit()
        print("Все пользователи и связанные данные удалены!")
        break

if __name__ == "__main__":
    asyncio.run(clear_users())