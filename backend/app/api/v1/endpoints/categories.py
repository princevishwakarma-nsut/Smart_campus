from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.permissions import require_roles, UserContext, Role
from app.database.dependencies import get_db
from app.schemas.category import CategoryCreate, CategoryUpdate, CategoryResponse

router = APIRouter()


@router.get("", response_model=List[CategoryResponse], summary="List all categories")
def list_categories(db=Depends(get_db)):
    db.execute("SELECT category_id, category_name, description, created_at FROM categories ORDER BY category_id ASC")
    rows = db.fetchall()
    return [
        CategoryResponse(
            category_id=r["category_id"],
            category_name=r["category_name"],
            description=r["description"],
            created_at=r["created_at"]
        )
        for r in rows
    ]


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED, summary="Create category (Admin)")
def create_category(req: CategoryCreate, current_user: UserContext = Depends(require_roles(Role.ADMIN)), db=Depends(get_db)):
    db.execute("SELECT category_id FROM categories WHERE category_name = %s", (req.category_name.strip(),))
    if db.fetchone():
        raise HTTPException(status_code=400, detail="Category with this name already exists.")

    db.execute(
        "INSERT INTO categories (category_name, description) VALUES (%s, %s)",
        (req.category_name.strip(), req.description)
    )
    cat_id = db.lastrowid
    db.execute("SELECT * FROM categories WHERE category_id = %s", (cat_id,))
    row = db.fetchone()

    return CategoryResponse(
        category_id=row["category_id"],
        category_name=row["category_name"],
        description=row["description"],
        created_at=row["created_at"]
    )


@router.put("/{category_id}", response_model=CategoryResponse, summary="Update category (Admin)")
def update_category(category_id: int, req: CategoryUpdate, current_user: UserContext = Depends(require_roles(Role.ADMIN)), db=Depends(get_db)):
    updates = []
    params = []
    if req.category_name is not None:
        updates.append("category_name = %s")
        params.append(req.category_name.strip())
    if req.description is not None:
        updates.append("description = %s")
        params.append(req.description)

    if updates:
        params.append(category_id)
        db.execute(f"UPDATE categories SET {', '.join(updates)} WHERE category_id = %s", tuple(params))

    db.execute("SELECT * FROM categories WHERE category_id = %s", (category_id,))
    row = db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")

    return CategoryResponse(
        category_id=row["category_id"],
        category_name=row["category_name"],
        description=row["description"],
        created_at=row["created_at"]
    )
