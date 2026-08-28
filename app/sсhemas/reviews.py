from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime


class ReviewCreate(BaseModel):
    """
    Модель для создания отзыва.
    Используется в POST.
    """
    product_id: int = Field(..., description="ID продукта")
    comment: str | None = Field(None, description="Отзыв на продукт")
    grade: int = Field(..., ge=1, le=5, description="Оценка продукта")

class Review(BaseModel):
    """
    Модель для ответа с данными отзыва.
    Используется в GET-запросах.
    """
    id: int = Field(..., description="Уникальный идентификатор отзыва")
    user_id: int = Field(..., description="ID пользователя")
    product_id: int = Field(..., description="ID продукта")
    comment: str | None = Field(None, description="Отзыв на продукт")
    comment_date: datetime = Field(..., escription="Дата отзыва")
    grade: int = Field(..., ge=1, le=5, description="Оценка продукта")
    is_active: bool = Field(..., description="Активность отзыва")

    model_config = ConfigDict(from_attributes=True)