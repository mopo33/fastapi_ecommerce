from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from app.models.reviews import Review as ReviewModel
from app.auth import get_current_buyer
from app.auth import get_current_user
from sqlalchemy.sql import func
from app.models.users import User as UserModel
from app.models.products import Product as ProductModel
from app.schemas import Review as ReviewSchema, ReviewCreate
from sqlalchemy.ext.asyncio import AsyncSession
from app.db_depends import get_async_db

# Создаём маршрутизатор для отзывов
router = APIRouter(
    prefix="/reviews",
    tags=["reviews"],
)

async def update_product_rating(db: AsyncSession, product_id: int):
    """
    Обновляет рейтинг продукта.
    """
    result = await db.execute(
        select(func.avg(ReviewModel.grade)).where(
            ReviewModel.product_id == product_id,
            ReviewModel.is_active == True
        )
    )
    avg_rating = result.scalar() or 0.0
    product = await db.get(ProductModel, product_id)
    product.rating = avg_rating
    await db.commit()

@router.get("/", response_model=list[ReviewSchema])
async def get_all_reviews(db: AsyncSession = Depends(get_async_db)):
    """
    Возвращает список всех отзывов.
    """
    stmt = await db.scalars(select(ReviewModel).where(ReviewModel.is_active == True))
    reviews = stmt.all()
    return reviews

@router.post("/", response_model=ReviewSchema, status_code=201)
async def create_review(
    review: ReviewCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_buyer)
):
    """
    Создаёт новый отзыв, привязанный к текущему продукту и пользователю (только для 'buyer').
    """
    product_result = await db.scalars(
        select(ProductModel).where(ProductModel.id == review.product_id, ProductModel.is_active == True)
    )
    if not product_result.first():
        raise HTTPException(status_code=404, detail="Product not found or inactive")

    db_review = ReviewModel(**review.model_dump(), user_id=current_user.id)
    db.add(db_review)
    await db.commit()
    await db.refresh(db_review)
    await update_product_rating(db, review.product_id)
    return db_review

@router.delete("/{review_id}", response_model=ReviewSchema)
async def delete_review(
    review_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Выполняет мягкое удаление отзыва, если он принадлежит текущему покупателю или пользователь админ(только для 'buyer' и 'admin').
    """
    result = await db.scalars(
        select(ReviewModel).where(ReviewModel.id == review_id, ReviewModel.is_active == True)
    )
    review = result.first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found or inactive")
    if review.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="You are not the author of the comment or the admin")
    await db.execute(
        update(ReviewModel).where(ReviewModel.id == review_id).values(is_active=False)
    )
    await db.commit()
    await db.refresh(review)
    await update_product_rating(db, review.product_id)
    return review