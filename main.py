import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from bson import ObjectId

# Database
from database import db

app = FastAPI(title="Shop API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helpers
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        try:
            return ObjectId(str(v))
        except Exception:
            raise ValueError("Invalid ObjectId")

def serialize_doc(doc: dict):
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id")) if doc.get("_id") else None
    # Convert nested object ids in cart items if present
    for k, v in list(doc.items()):
        if isinstance(v, ObjectId):
            doc[k] = str(v)
    return doc


# Schemas
class ProductCreate(BaseModel):
    title: str
    description: Optional[str] = None
    price: float = Field(ge=0)
    category: str
    image: Optional[str] = None
    rating: Optional[float] = Field(default=4.5, ge=0, le=5)
    reviews: Optional[int] = Field(default=0, ge=0)
    in_stock: bool = True

class Product(ProductCreate):
    id: str

class CartAddRequest(BaseModel):
    session_id: str
    product_id: str
    quantity: int = Field(ge=1, default=1)

class CartItem(BaseModel):
    product: Product
    quantity: int
    line_total: float

class CartResponse(BaseModel):
    session_id: str
    items: List[CartItem]
    subtotal: float
    total_items: int


@app.get("/")
def read_root():
    return {"message": "Shop backend running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set" if not os.getenv("DATABASE_URL") else "✅ Set",
        "database_name": "❌ Not Set" if not os.getenv("DATABASE_NAME") else "✅ Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()
    except Exception as e:
        response["database"] = f"⚠️ Error: {str(e)[:80]}"
    return response


# Products endpoints
@app.get("/api/products", response_model=List[Product])
def list_products(q: Optional[str] = Query(default=None, description="Search query"), category: Optional[str] = None):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    query = {}
    if q:
        query["title"] = {"$regex": q, "$options": "i"}
    if category:
        query["category"] = category
    products = list(db["product"].find(query).limit(100))
    return [Product(**serialize_doc(p)) for p in products]


@app.get("/api/products/{product_id}", response_model=Product)
def get_product(product_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        oid = ObjectId(product_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product id")
    doc = db["product"].find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return Product(**serialize_doc(doc))


@app.post("/api/products/seed")
def seed_products():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    if db["product"].count_documents({}) > 0:
        return {"message": "Products already seeded"}
    sample = [
        {
            "title": "Wireless Headphones",
            "description": "Noise-cancelling over-ear headphones with 30h battery",
            "price": 129.99,
            "category": "Electronics",
            "image": "https://images.unsplash.com/photo-1518449007433-67807eebedc2?w=800",
            "rating": 4.6,
            "reviews": 1243,
            "in_stock": True,
        },
        {
            "title": "Smartwatch Series X",
            "description": "Fitness tracking, GPS, and notifications",
            "price": 199.0,
            "category": "Wearables",
            "image": "https://images.unsplash.com/photo-1511739001486-6bfe10ce785f?w=800",
            "rating": 4.4,
            "reviews": 876,
            "in_stock": True,
        },
        {
            "title": "4K Monitor 27''",
            "description": "Ultra HD IPS display with vivid colors",
            "price": 329.0,
            "category": "Computers",
            "image": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=800",
            "rating": 4.7,
            "reviews": 532,
            "in_stock": True,
        },
        {
            "title": "Mechanical Keyboard",
            "description": "RGB backlit, hot-swappable switches",
            "price": 89.99,
            "category": "Computers",
            "image": "https://images.unsplash.com/photo-1516574187841-cb9cc2ca948b?w=800",
            "rating": 4.5,
            "reviews": 1450,
            "in_stock": True,
        },
        {
            "title": "Espresso Machine",
            "description": "Barista-grade coffee at home",
            "price": 249.99,
            "category": "Home",
            "image": "https://images.unsplash.com/photo-1504754524776-8f4f37790ca0?w=800",
            "rating": 4.3,
            "reviews": 412,
            "in_stock": True,
        },
    ]
    db["product"].insert_many(sample)
    return {"message": "Seeded", "count": len(sample)}


# Cart endpoints
@app.post("/api/cart/add", response_model=CartResponse)
def add_to_cart(payload: CartAddRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Validate product
    try:
        prod_oid = ObjectId(payload.product_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product id")
    product = db["product"].find_one({"_id": prod_oid})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Upsert cart item
    db["cart"].update_one(
        {"session_id": payload.session_id, "product_id": prod_oid},
        {"$inc": {"quantity": payload.quantity}, "$setOnInsert": {"session_id": payload.session_id, "product_id": prod_oid}},
        upsert=True,
    )
    return build_cart_response(payload.session_id)


@app.get("/api/cart", response_model=CartResponse)
def get_cart(session_id: str = Query(...)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    return build_cart_response(session_id)


@app.post("/api/cart/clear", response_model=CartResponse)
def clear_cart(session_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    db["cart"].delete_many({"session_id": session_id})
    return build_cart_response(session_id)


def build_cart_response(session_id: str) -> CartResponse:
    cart_items = list(db["cart"].find({"session_id": session_id}))
    items: List[CartItem] = []
    subtotal = 0.0
    total_items = 0
    for ci in cart_items:
        prod = db["product"].find_one({"_id": ci.get("product_id")})
        if not prod:
            continue
        prod_s = serialize_doc(prod)
        line_total = float(prod_s.get("price", 0)) * int(ci.get("quantity", 1))
        subtotal += line_total
        total_items += int(ci.get("quantity", 1))
        items.append(
            CartItem(
                product=Product(**prod_s),
                quantity=int(ci.get("quantity", 1)),
                line_total=round(line_total, 2),
            )
        )
    return CartResponse(
        session_id=session_id,
        items=items,
        subtotal=round(subtotal, 2),
        total_items=total_items,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
