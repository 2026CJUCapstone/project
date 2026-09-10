import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import database as m, schemas
from app.api.routes import auth, admin


@pytest.fixture
def accounts(tmp_path):
    engine=create_engine(f"sqlite:///{(tmp_path/'profiles.db').as_posix()}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        manager=m.User(id='manager',username='manager',hashed_password='unused',role='admin')
        target=m.User(id='target',username='target',hashed_password='unused',role='user',
            email='old@example.test',nickname='Old nickname',avatar_url='https://fixture.invalid/old.svg')
        db.add_all([manager,target]);db.commit()
        yield db,manager,target
    engine.dispose()


def update(role,body,accounts):
    db,manager,target=accounts
    if role=='admin':admin.update_user(target.id,schemas.AdminUserUpdate.model_validate(body),db,manager)
    else:auth.update_profile(schemas.UserProfileUpdate.model_validate(body),db,target)
    db.expire_all()
    return db.get(m.User,target.id)


@pytest.mark.parametrize('role',['self','admin'])
def test_explicit_null_clears_optional_profile_fields_but_not_role(role,accounts):
    target=update(role,{'email':None,'nickname':None,'avatarUrl':None},accounts)
    assert (target.email,target.nickname,target.avatar_url)==(None,None,None)
    assert target.role=='user'


@pytest.mark.parametrize('role',['self','admin'])
def test_partial_update_does_not_clear_omitted_fields(role,accounts):
    target=update(role,{'avatarUrl':None},accounts)
    assert target.avatar_url is None
    assert target.email=='old@example.test' and target.nickname=='Old nickname'


@pytest.mark.parametrize('role',['self','admin'])
def test_empty_patch_preserves_all_profile_fields(role,accounts):
    target=update(role,{},accounts)
    assert (target.email,target.nickname,target.avatar_url)==(
        'old@example.test','Old nickname','https://fixture.invalid/old.svg')


def test_admin_concurrent_uniqueness_conflict_rolls_back_and_returns_409(accounts,monkeypatch):
    db,manager,target=accounts
    rollback=db.rollback
    events=[]
    def raced_commit():
        # Another transaction can take the email after the route precheck.
        raise IntegrityError('UPDATE users',{},Exception('unique constraint'))
    def recorded_rollback():
        events.append('rollback')
        rollback()
    monkeypatch.setattr(db,'commit',raced_commit)
    monkeypatch.setattr(db,'rollback',recorded_rollback)
    with pytest.raises(HTTPException) as error:
        admin.update_user(target.id,schemas.AdminUserUpdate(email='racing@example.test'),db,manager)
    assert error.value.status_code==409
    assert events==['rollback']
    assert db.get(m.User,'target').email=='old@example.test'
