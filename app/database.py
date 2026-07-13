from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# Строка подключения для SQLite
DATABASE_URL = "sqlite:///ecommerce.db"

# Создаём Engine
engine = create_engine(DATABASE_URL, echo=True)

# Настраиваем фабрику сеансов
SessionLocal = sessionmaker(bind=engine)


# --------------- Асинхронное подключение к PostgreSQL -------------------------

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

# Строка подключения для PostgreSQl
DATABASE_URL = "postgresql+asyncpg://ecommerce_user:Ab12341234@localhost:5432/ecommerce_db"

# Создаём Engine
async_engine = create_async_engine(DATABASE_URL, echo=True)

# Настраиваем фабрику сеансов
async_session_maker = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass

'''
Также SQLAlchemy поддерживает различные базы данных через единый формат URL:
dialect+driver://username:password@host:port/database
               
-dialect: Тип базы данных (например, sqlite, postgresql, mysql).
-driver: DBAPI-драйвер (для SQLite дополнительный драйвер не нужен, так как SQLAlchemy использует встроенный модуль sqlite3. 
Но для других баз данных, таких как PostgreSQL, потребуется установить драйвер, например, psycopg2)
-username:password@host:port/database: Параметры подключения (для SQLite не требуются).
'''


