from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.config import JWT_EXPIRE_MINUTES, JWT_SECRET
from app.database import get_db
from app.models import now, parse_id

ALGORITHM = "HS256"

# Argon2id with the library's recommended defaults. Each hash embeds its own random salt.
hasher = PasswordHasher()
# Verified against when the email is unknown, so "no such user" takes as long as "wrong password"
_DUMMY_HASH = hasher.hash("not-a-real-password")

# Also makes the Authorize button appear on /docs. tokenUrl is where it sends the login form.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None = None  # accounts made before names were asked for have none
    created_at: datetime | None = None


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def create_access_token(user_id: str) -> str:
    issued = datetime.now(timezone.utc)
    claims = {
        "sub": user_id,  # who the token is for
        "iat": issued,
        "exp": issued + timedelta(minutes=JWT_EXPIRE_MINUTES),  # checked automatically on decode
    }
    return jwt.encode(claims, JWT_SECRET, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Database = Depends(get_db)) -> dict:
    """Dependency for protected routes: verifies the token and loads its user document."""
    unauthorized = HTTPException(
        status_code=401, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        # Pinning algorithms=[...] stops attackers choosing a weaker one (e.g. "none")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id = parse_id(payload["sub"])
    except (jwt.PyJWTError, KeyError):
        raise unauthorized
    user = db.users.find_one({"_id": user_id}) if user_id else None
    if user is None:
        raise unauthorized
    return user


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, db: Database = Depends(get_db)):
    email = _normalize_email(body.email)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Please enter your name")
    taken = HTTPException(status_code=409, detail="An account with this email already exists")
    if db.users.find_one({"email": email}, {"_id": 1}):
        raise taken

    try:
        result = db.users.insert_one(
            {"name": name, "email": email, "password_hash": hasher.hash(body.password), "created_at": now()}
        )
    except DuplicateKeyError:  # two signups with the same email raced past the check above
        raise taken
    return TokenOut(access_token=create_access_token(str(result.inserted_id)))


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Database = Depends(get_db)):
    """Form fields: username (your email) and password. Form-encoded so /docs' Authorize button works."""
    user = db.users.find_one({"email": _normalize_email(form.username)})

    password_ok = False
    try:
        hasher.verify(user["password_hash"] if user else _DUMMY_HASH, form.password)
        password_ok = user is not None
    except (VerificationError, InvalidHashError):
        pass

    if not password_ok:
        # Same message whether the email or the password was wrong
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    # Upgrade the stored hash if the library's recommended settings have changed since it was made
    if hasher.check_needs_rehash(user["password_hash"]):
        db.users.update_one({"_id": user["_id"]}, {"$set": {"password_hash": hasher.hash(form.password)}})
    return TokenOut(access_token=create_access_token(str(user["_id"])))


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)):
    return UserOut(
        id=str(user["_id"]), email=user["email"], name=user.get("name"), created_at=user.get("created_at")
    )
