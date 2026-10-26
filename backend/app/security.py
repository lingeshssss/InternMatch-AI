import hashlib, json, secrets
from datetime import timedelta
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import Session, AuthSession, User, RateLimit, now, aware

hasher = PasswordHasher()
# __Host- cookies must be Secure, host-only and Path=/; browsers reject them over plain HTTP.
COOKIE = '__Host-internmatch_session' if settings.production else 'internmatch_session'

def cipher():
    if not settings.data_encryption_key: raise HTTPException(503,'DATA_ENCRYPTION_KEY is required for encrypted storage')
    return Fernet(settings.data_encryption_key.encode())
def encrypt(data): return cipher().encrypt(json.dumps(data).encode()).decode()
def decrypt(data): return json.loads(cipher().decrypt(data.encode()))
def digest(v): return hashlib.sha256(v.encode()).hexdigest()
def get_db():
    with Session() as db:
        yield db

def current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get(COOKIE)
    if not token: raise HTTPException(401,'Sign in required')
    session = db.get(AuthSession,digest(token))
    if not session or aware(session.expires_at) <= now(): raise HTTPException(401,'Session expired')
    user = db.get(User,session.user_id)
    if not user: raise HTTPException(401,'Account not found')
    return user

def set_session_cookie(response,token):
    response.set_cookie(COOKIE,token,httponly=True,secure=settings.production,samesite='lax',max_age=604800,path='/')

def clear_session_cookie(response):
    response.delete_cookie(COOKIE,path='/',secure=settings.production,httponly=True,samesite='lax')

def new_session(db,user,response):
    token=secrets.token_urlsafe(48)
    db.add(AuthSession(token_hash=digest(token),user_id=user.id,expires_at=now()+timedelta(days=7)))
    set_session_cookie(response,token)

def rate_limit(key,limit=60,seconds=60):
    """Fixed-window counter in PostgreSQL. Row locking keeps concurrent API processes consistent."""
    count=None
    for _ in range(2):
        try:
            with Session() as db:
                row=db.scalar(select(RateLimit).where(RateLimit.key==key).with_for_update())
                current=now()
                if row is None:
                    row=RateLimit(key=key,window_start=current,count=0); db.add(row)
                elif aware(row.window_start)<=current-timedelta(seconds=seconds):
                    row.window_start=current; row.count=0
                row.count+=1; count=row.count
                db.commit()
            break
        except IntegrityError:
            continue  # Concurrent first insert for this key; retry against the existing row.
        except Exception:
            break
    if count is None: raise HTTPException(503,'Rate limiter unavailable')
    if count>limit: raise HTTPException(429,'Rate limit exceeded')
