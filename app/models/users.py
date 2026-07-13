from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from .reviews import Review
from .categories import Category
from .products import Product


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String, default="buyer")  # "buyer" or "seller"

    products: Mapped[list["Product"]] = relationship("Product", back_populates="seller")
    categories: Mapped[list["Category"]] = relationship("Category", back_populates="admin")
    reviews: Mapped[list["Review"]] = relationship("Review", back_populates="buyer")