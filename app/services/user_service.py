"""
Business logic for User operations.
"""
from datetime import datetime, timezone
from fastapi import HTTPException, status
from app.database.mongo import users_col
from app.schemas.user_schemas import UserRegister, UserLogin, UserOut, TokenOut
from app.utils.password import hash_password, verify_password
from app.auth.jwt_handler import create_access_token
from app.utils.mongo_helpers import doc_to_dict


async def register_user(data: UserRegister) -> TokenOut:
    col = users_col()

    # Unique email check
    existing = await col.find_one({"email": data.email})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    user_doc = {
        "name": data.name,
        "email": data.email,
        "password": hash_password(data.password),
        "created_at": datetime.now(timezone.utc),
    }
    result = await col.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id

    user_dict = doc_to_dict(user_doc)
    user_out = UserOut(**user_dict)
    token = create_access_token({"sub": user_out.id})

    return TokenOut(access_token=token, user=user_out)


async def login_user(data: UserLogin) -> TokenOut:
    col = users_col()
    user = await col.find_one({"email": data.email})

    if not user or not verify_password(data.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    user_dict = doc_to_dict(user)
    user_out = UserOut(**user_dict)
    token = create_access_token({"sub": user_out.id})

    return TokenOut(access_token=token, user=user_out)
