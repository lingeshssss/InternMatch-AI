import base64, hashlib, json, secrets
from datetime import timedelta, timezone
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, Depends
from redis import Redis
from sqlalchemy import select
from .config import settings
from .db import Session, AuthSession, User, now

hasher = PasswordHasher()
redis = Redis.from_url(settings.redis_url, decode_responses=True)

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
    token = request.cookies.get('internmatch_session')
    if not token: raise HTTPException(401,'Sign in required')
    session = db.get(AuthSession,digest(token))
    if not session or session.expires_at.replace(tzinfo=timezone.utc) <= now(): raise HTTPException(401,'Session expired')
    user = db.get(User,session.user_id)
    if not user: raise HTTPException(401,'Account not found')
    return user

def new_session(db,user,response):
    token=secrets.token_urlsafe(48)
    db.add(AuthSession(token_hash=digest(token),user_id=user.id,expires_at=now()+timedelta(days=7)))
    response.set_cookie('internmatch_session',token,httponly=True,secure=settings.app_env=='production',samesite='lax',max_age=604800,path='/')

def rate_limit(key,limit=60,seconds=60):
    try:
        n=redis.incr('rate:'+key)
        if n==1: redis.expire('rate:'+key,seconds)
        if n>limit: raise HTTPException(429,'Rate limit exceeded')
    except HTTPException: raise
    except Exception: raise HTTPException(503,'Rate limiter unavailable')
