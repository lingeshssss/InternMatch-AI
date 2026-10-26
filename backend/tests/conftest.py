import os
from cryptography.fernet import Fernet
os.environ['DATABASE_URL']='sqlite://'
os.environ['DATA_ENCRYPTION_KEY']=Fernet.generate_key().decode()
os.environ['APP_ORIGINS']='http://localhost:8080'
os.environ['AI_PROVIDER']='disabled'
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.db import Base
from app.main import app
from app.security import get_db
@pytest.fixture
def db():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    @event.listens_for(engine,'connect')
    def fk(conn,_):conn.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with sessionmaker(engine,expire_on_commit=False)() as session:yield session
    engine.dispose()
@pytest.fixture
def client(db,monkeypatch):
    monkeypatch.setattr('app.main.rate_limit',lambda *a,**k:None)
    def override():yield db
    app.dependency_overrides[get_db]=override
    with TestClient(app,headers={'Origin':'http://localhost:8080'}) as c:yield c
    app.dependency_overrides.clear()
