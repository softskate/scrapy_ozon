from pydantic import BaseModel, ConfigDict
from typing import Optional


class ProductSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    productId: str
    productUrl: str
    name: str
    price: int
    imageUrl: str


class ProductDetailSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    productId: str
    productUrl: str
    name: str
    description: str
    price: int
    imageUrls: list
    brandName: Optional[str] = None
    details: Optional[dict] = None
    
    
class ParsingItemCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    link: str
