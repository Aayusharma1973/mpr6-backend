"""
FastAPI dependency that extracts + validates the current user from the JWT.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.auth.jwt_handler import decode_token, CREDENTIALS_EXCEPTION
from app.database.mongo import users_col
from bson import ObjectId

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    Validates the Bearer token and returns the user document from MongoDB.
    Raises 401 if token is invalid or user not found.
    """
    token = credentials.credentials
    payload = decode_token(token)

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise CREDENTIALS_EXCEPTION

    try:
        user = await users_col().find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise CREDENTIALS_EXCEPTION

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Normalise _id → id
    user["id"] = str(user["_id"])
    return user
