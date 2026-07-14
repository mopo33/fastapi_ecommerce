from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.models.users import User as UserModel
from app.auth import get_current_seller
from app.models.reviews import Review as ReviewModel
from app.schemas import Review as ReviewSchema
from app.models.products import Product as ProductModel
from app.models.categories import Category as CategoryModel
from app.schemas import Product as ProductSchema, ProductCreate, ProductList
from sqlalchemy.ext.asyncio import AsyncSession
from app.db_depends import get_async_db
from sqlalchemy import select, func, desc, update, asc
from enum import Enum

# Создаём маршрутизатор для товаров
router = APIRouter(
    prefix="/products",
    tags=["products"],
)

class ProductSortField(str, Enum):
    id = "id"
    created_at = "created_at"
    price = "price"
    name = "name"
    rating = "rating"

class SortDir(str, Enum):
    asc = "asc"
    desc = "desc"

@router.get("/", response_model=ProductList)
async def get_all_products(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        category_id: int | None = Query(
            None, description="ID категории для фильтрации"),
        min_price: float | None = Query(
            None, ge=0, description="Минимальная цена товара"),
        max_price: float | None = Query(
            None, ge=0, description="Максимальная цена товара"),
        in_stock: bool | None = Query(
            None, description="true — только товары в наличии, false — только без остатка"),
        seller_id: int | None = Query(
            None, description="ID продавца для фильтрации"),
        sort_by: list[ProductSortField] = Query([ProductSortField.id], descrtiption='Список для сортировки'),
        sort_dir: list[SortDir] = Query([SortDir.desc], descrtiption='Выбор сортировки по убыванию или по возрастанию'),
        db: AsyncSession = Depends(get_async_db),
):
    """
    Возвращает список всех активных товаров с поддержкой фильтров.
    """

    if len(sort_by) != len(sort_dir):
        raise HTTPException(status_code=400, detail='Количество полей сортировки и направлений не совпадает')

    sort_mapping = {
        ProductSortField.id: ProductModel.id,
        ProductSortField.created_at: ProductModel.created_at,
        ProductSortField.price: ProductModel.price,
        ProductSortField.name: ProductModel.name,
        ProductSortField.rating: ProductModel.rating
    }

    sorted_list = []
    for field, direction in zip(sort_by, sort_dir):
        sort_col = sort_mapping[field]
        if direction == SortDir.desc:
            sorted_list.append(desc(sort_col))
        else:
            sorted_list.append(asc(sort_col))

    # Проверка логики min_price <= max_price
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_price не может быть больше max_price",
        )

    # Формируем список фильтров
    filters = [ProductModel.is_active == True]

    if category_id is not None:
        filters.append(ProductModel.category_id == category_id)
    if min_price is not None:
        filters.append(ProductModel.price >= min_price)
    if max_price is not None:
        filters.append(ProductModel.price <= max_price)
    if in_stock is not None:
        filters.append(ProductModel.stock > 0 if in_stock else ProductModel.stock == 0)
    if seller_id is not None:
        filters.append(ProductModel.seller_id == seller_id)

    # Подсчёт общего количества с учётом фильтров
    total_stmt = select(func.count()).select_from(ProductModel).where(*filters)
    total = await db.scalar(total_stmt) or 0

    # Выборка товаров с фильтрами и пагинацией
    products_stmt = (
        select(ProductModel)
        .where(*filters)
        .order_by(*sorted_list)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = (await db.scalars(products_stmt)).all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/category/{category_id}", response_model=list[ProductSchema])
async def get_products_by_category(category_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    Возвращает список товаров в указанной категории по её ID.
    """
    stmt = await db.scalars(select(ProductModel).where(category_id == ProductModel.category_id,
                                      ProductModel.is_active == True))
    products = stmt.all()
    if products is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return products


@router.get("/{product_id}", response_model=ProductSchema)
async def get_product(product_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    Возвращает детальную информацию о товаре по его ID.
    """
    stmt = await db.scalars(select(ProductModel).where(product_id == ProductModel.id,
                                      ProductModel.is_active == True))
    product = stmt.first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.get("/{product_id}/reviews/", response_model=list[ReviewSchema])
async def get_reviews_by_product(product_id: int, db: AsyncSession = Depends(get_async_db)):
    """
    Возвращает список отзывов на конкретный товар по его ID.
    """
    stmt = await db.scalars(select(ReviewModel).where(product_id == ReviewModel.product_id,
                                      ReviewModel.is_active == True))
    reviews = stmt.all()
    if reviews is None:
        raise HTTPException(status_code=404, detail="Product not found or inactive")
    return reviews

@router.post("/", response_model=ProductSchema, status_code=201)
async def create_product(
    product: ProductCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_seller)
):
    """
    Создаёт новый товар, привязанный к текущему продавцу (только для 'seller').
    """
    category_result = await db.scalars(
        select(CategoryModel).where(CategoryModel.id == product.category_id, CategoryModel.is_active == True)
    )
    if not category_result.first():
        raise HTTPException(status_code=400, detail="Category not found or inactive")
    db_product = ProductModel(**product.model_dump(), seller_id=current_user.id)
    db.add(db_product)
    await db.commit()
    await db.refresh(db_product)  # Для получения id и is_active из базы
    return db_product

@router.put("/{product_id}", response_model=ProductSchema)
async def update_product(
    product_id: int,
    product: ProductCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_seller)
):
    """
    Обновляет товар, если он принадлежит текущему продавцу (только для 'seller').
    """
    result = await db.scalars(select(ProductModel).where(ProductModel.id == product_id, ProductModel.is_active == True))
    db_product = result.first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    if db_product.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only update your own products")
    category_result = await db.scalars(
        select(CategoryModel).where(CategoryModel.id == product.category_id, CategoryModel.is_active == True)
    )
    if not category_result.first():
        raise HTTPException(status_code=400, detail="Category not found or inactive")
    await db.execute(
        update(ProductModel).where(ProductModel.id == product_id).values(**product.model_dump())
    )
    await db.commit()
    await db.refresh(db_product)  # Для консистентности данных
    return db_product

@router.delete("/{product_id}", response_model=ProductSchema)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_seller)
):
    """
    Выполняет мягкое удаление товара, если он принадлежит текущему продавцу (только для 'seller').
    """
    result = await db.scalars(
        select(ProductModel).where(ProductModel.id == product_id, ProductModel.is_active == True)
    )
    product = result.first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found or inactive")
    if product.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own products")
    await db.execute(
        update(ProductModel).where(ProductModel.id == product_id).values(is_active=False)
    )
    await db.commit()
    await db.refresh(product)  # Для возврата is_active = False
    return product