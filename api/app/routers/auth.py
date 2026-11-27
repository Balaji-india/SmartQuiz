import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from eth_utils import is_checksum_address, to_checksum_address
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import create_token, get_current_user, hash_password, verify_password
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupIn(BaseModel):
    email: EmailStr
    # The upper limit stops very long passwords from tying up argon2.
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: str
    wallet_address: str | None


_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


class WalletIn(BaseModel):
    wallet_address: str | None

    @field_validator("wallet_address")
    @classmethod
    def _checksummed(cls, v: str | None) -> str | None:
        """null clears the wallet (badges then go to the custodial address). A mixed-case address must carry a valid
        EIP-55 checksum, so a mistyped address is refused instead of minting a badge to it."""
        if v is None:
            return None
        v = v.strip()
        if not _ADDRESS.match(v):
            raise ValueError("wallet_address must be 0x followed by 40 hex characters")
        body = v[2:]
        if body != body.lower() and body != body.upper() and not is_checksum_address(v):
            raise ValueError("wallet_address has an invalid EIP-55 checksum")
        if int(body, 16) == 0:
            raise ValueError("wallet_address cannot be the zero address")
        return to_checksum_address(v)


class AuthOut(BaseModel):
    token: str
    user: UserOut


def _auth_response(user: User) -> AuthOut:
    return AuthOut(token=create_token(user.id), user=UserOut.model_validate(user))


@router.post("/signup", response_model=AuthOut)
def signup(body: SignupIn, db: Session = Depends(get_db)) -> AuthOut:
    user = User(email=body.email.lower(), password_hash=hash_password(body.password), name=body.name)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from None
    return _auth_response(user)


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> AuthOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not verify_password(user.password_hash if user else None, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return _auth_response(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.put("/me/wallet", response_model=UserOut)
def set_wallet(body: WalletIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> User:
    """Future badges go to this address; badges already minted stay where they are (they are soulbound)."""
    user.wallet_address = body.wallet_address
    db.commit()
    return user
