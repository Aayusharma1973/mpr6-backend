"""
Authentication routes — register & login.
"""
from fastapi import APIRouter
from app.schemas.user_schemas import UserRegister, UserLogin, TokenOut
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=TokenOut,
    status_code=201,
    summary="Register a new user",
)
async def register(body: UserRegister):
    """
    Create a new account.  Returns a JWT + user info.
    """
    return await user_service.register_user(body)


@router.post(
    "/login",
    response_model=TokenOut,
    summary="Login with email & password",
)
async def login(body: UserLogin):
    """
    Authenticate and receive a JWT token.
    """
    return await user_service.login_user(body)
