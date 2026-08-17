from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from app.models.users import User as UserModel
from app.auth import get_current_seller
from app.models.reviews import Review as ReviewModel
from app.schemas import Review as ReviewSchema
from app.models.products import Product as ProductModel
from app.models.categories import Category as CategoryModel
from app.schemas import Product as ProductSchema, ProductCreate, ProductList
from sqlalchemy.ext.asyncio import AsyncSession
from app.db_depends import get_async_db
from sqlalchemy import select, func, desc, update, asc, or_
from enum import Enum
from pathlib import Path
import uuid

# Константы

BASE_DIR = Path(__file__).resolve().parent.parent.parent #  Абсолютный путь к корню проекта Path(__file__) это путь к текущему файлу (products.py),
                                                         # а .resolve() абсолютный путь (без .., без символических ссылок)
                                                         # и .parent.parent.parent  поднимаемся на три уровня вверх, то есть корень проекта
MEDIA_ROOT = BASE_DIR / "media" / "products" # Физическая папка на диске, куда сохраняются все изображения товаров. Создаётся автоматически при старте.
MEDIA_ROOT.mkdir(parents=True, exist_ok=True) # Cоздаёт папку, если её нет
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"} # Белый список MIME-типов. Защищает от загрузки файлов с ненужным расширением
MAX_IMAGE_SIZE = 2 * 1024 * 1024  # 2 097 152 байт Ограничение размера изображения

# Создаём маршрутизатор для товаров
router = APIRouter(
    prefix="/products",
    tags=["products"],
)

# Класс для выбора сортировки
class ProductSortField(str, Enum):
    id = "id"
    created_at = "created_at"
    price = "price"
    name = "name"
    rating = "rating"

# Класс для выбора направления (по убыванию/по возрастанию)
class SortDir(str, Enum):
    asc = "asc"
    desc = "desc"

# Вспомогательные функции для медиафайлов

async def save_product_image(file: UploadFile) -> str:
    """
    Сохраняет изображение товара и возвращает относительный URL.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only JPG, PNG or WebP images are allowed")
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Image is too large")
    extension = Path(file.filename or "").suffix.lower() or ".jpg"
    file_name = f'{uuid.uuid4()}{extension}'
    file_path = MEDIA_ROOT / file_name
    file_path.write_bytes(content)

    return f'/media/products/{file_name}'

async def remove_product_image(url: str | None) -> None:
    """
    Удаляет файл изображения, если он существует.
    """
    if not url:
        return
    relative_path = url.lstrip("/")
    file_path = BASE_DIR / relative_path
    if file_path.exists():
        file_path.unlink()

@router.get("/", response_model=ProductList)
async def get_all_products(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        category_id: int | None = Query(
            None, description="ID категории для фильтрации"),
        search: str | None = Query(None, min_length=1, description="Поиск по названию товара"),
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
    # Проверка, что количество полей сортировки совпадает с количеством направлений сортировки
    if len(sort_by) != len(sort_dir):
        raise HTTPException(status_code=400, detail='Количество полей сортировки и направлений не совпадает')

    # Создаём маппинг полей
    sort_mapping = {
        ProductSortField.id: ProductModel.id,
        ProductSortField.created_at: ProductModel.created_at,
        ProductSortField.price: ProductModel.price,
        ProductSortField.name: ProductModel.name,
        ProductSortField.rating: ProductModel.rating
    }

    # Проверка логики min_price <= max_price
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(
            status_code=400,
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

    rank_col = None
    if search:
        search_value = search.strip()
        if search_value:
            # Строим два tsquery для одной и той же фразы
            ts_query_en = func.websearch_to_tsquery('english', search_value)
            ts_query_ru = func.websearch_to_tsquery('russian', search_value)

            # Ищем совпадение в любой конфигурации и добавляем в общий фильтр
            ts_match_any = or_(
                ProductModel.tsv.op('@@')(ts_query_en),
                ProductModel.tsv.op('@@')(ts_query_ru),
            )
            # Пытаемся найти через полнотекстовый поиск
            temp_filters = filters + [ts_match_any]
            check_stmt = select(func.count()).select_from(ProductModel).where(*temp_filters)
            count = await db.scalar(check_stmt) or 0

            if count > 0:
                # Есть результаты — используем полнотекстовый поиск
                filters.append(ts_match_any)
                rank_col = func.greatest(
                    func.ts_rank_cd(ProductModel.tsv, ts_query_en),
                    func.ts_rank_cd(ProductModel.tsv, ts_query_ru),
                ).label("rank")
            else:
                # Нет результатов — переключаемся на LIKE
                like_pattern = f"%{search_value}%"
                like_filter = or_(
                    func.lower(ProductModel.name).like(like_pattern.lower()),
                    func.lower(ProductModel.description).like(like_pattern.lower()),
                )
                filters.append(like_filter)

    # Подсчёт общего количества
    total_stmt = select(func.count()).select_from(ProductModel).where(*filters)
    total = await db.scalar(total_stmt) or 0

    # Создаём список для сортировки
    sorted_list = []

    # Если есть поиск — сначала сортировка по рангу
    if rank_col is not None:
        sorted_list.append(rank_col.desc())

    # После "поиска" добавляем остальные сортировки
    for field, direction in zip(sort_by, sort_dir):
        sort_col = sort_mapping[field]
        if direction == SortDir.desc:
            sorted_list.append(desc(sort_col))
        else:
            sorted_list.append(asc(sort_col))

    # Основной запрос (если есть поиск — добавим ранг в выборку и сортировку)
    if rank_col is not None:
        products_stmt = (
            select(ProductModel, rank_col)
            .where(*filters)
            .order_by(*sorted_list)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(products_stmt)
        rows = result.all()
        items = [row[0] for row in rows]  # сами объекты
        # при желании можно вернуть ранг в ответе
        # ranks = [row.rank for row in rows]
    else:
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
    product: ProductCreate = Depends(ProductCreate.as_form),
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_seller),
    image: UploadFile | None = File(None)
):
    """
    Создаёт новый товар, привязанный к текущему продавцу (только для 'seller').
    """
    category_result = await db.scalars(
        select(CategoryModel).where(CategoryModel.id == product.category_id, CategoryModel.is_active == True)
    )
    if not category_result.first():
        raise HTTPException(status_code=400, detail="Category not found or inactive")
    image_url = await save_product_image(image) if image else None
    db_product = ProductModel(**product.model_dump(), seller_id=current_user.id, image_url=image_url)
    db.add(db_product)
    await db.commit()
    await db.refresh(db_product)  # Для получения id и is_active из базы
    return db_product

@router.put("/{product_id}", response_model=ProductSchema)
async def update_product(
    product_id: int,
    product: ProductCreate = Depends(ProductCreate.as_form),
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_seller),
    image: UploadFile | None = File(None)
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
    if image:
        remove_product_image(db_product.image_url)
        db_product.image_url = await save_product_image(image)
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

    remove_product_image(product.image_url)

    await db.execute(
        update(ProductModel).where(ProductModel.id == product_id).values(image_url=None, is_active=False)
    )

    await db.commit()
    await db.refresh(product)  # Для возврата is_active = False

    return product