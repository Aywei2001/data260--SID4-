import datetime
import os
from enum import Enum
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]
SECRET_KEY = os.environ["JWT_SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 30

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class Role(str, Enum):
    reader = "reader"
    writer = "writer"
    moderator = "moderator"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(SqlEnum(Role), nullable=False, default=Role.reader)


class RelatedEntity(Base):
    __tablename__ = "related_entities"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    primary_text = Column(String(255), nullable=False)
    secondary_text = Column(Text, nullable=False)
    code = Column(String(100), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    records = relationship("Record", back_populates="related_entity")


class Record(Base):
    __tablename__ = "record_info"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    primary_field = Column(String(255), nullable=False)
    secondary_field = Column(Text, nullable=False)
    unique_code = Column(String(100), unique=True, nullable=False)
    quantity = Column(Integer, default=10, nullable=False)
    related_entity_id = Column(
        Integer,
        ForeignKey("related_entities.id"),
        nullable=False,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    related_entity = relationship("RelatedEntity", back_populates="records")


# use to create or migrate any missing tables
Base.metadata.create_all(bind=engine)

router = APIRouter()


# uses for authentication
class LoginSchema(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserIdentity(BaseModel):
    id: int
    username: str
    role: Role


# use for existing schemas
class RelatedEntityCreate(BaseModel):
    primary_text: str = Field(..., min_length=1)
    secondary_text: str = Field(..., min_length=1)
    code: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[A-Z0-9_-]+$",
    )


class RelatedEntityResponse(RelatedEntityCreate):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class RecordSchema(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    unique_code: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[A-Z0-9_-]+$",
    )
    quantity: int = Field(default=10, ge=0)
    related_entity_id: int


class RecordResponse(BaseModel):
    id: int
    name: str
    description: str
    unique_code: str
    quantity: int
    related_entity_id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


def create_access_token(user: User) -> str:
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=ACCESS_TOKEN_MINUTES
    )
    claims = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "exp": expires_at,
    }
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(claims["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        raise unauthorized

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise unauthorized

    return user


def require_roles(*allowed_roles: Role):
    def role_check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return user

    return role_check


@router.post("/auth/login", response_model=TokenResponse)
def login(credentials: LoginSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == credentials.username).first()

    if not user or not pwd_context.verify(
        credentials.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    return TokenResponse(access_token=create_access_token(user))


@router.get("/auth/me", response_model=UserIdentity)
def get_me(user: User = Depends(get_current_user)):
    return UserIdentity(id=user.id, username=user.username, role=user.role)


@router.post(
    "/related-entities",
    response_model=RelatedEntityResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_related_entity(
    item: RelatedEntityCreate,
    user: User = Depends(require_roles(Role.writer, Role.moderator)),
    db: Session = Depends(get_db),
):
    existing = db.query(RelatedEntity).filter(RelatedEntity.code == item.code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Related entity with this code already exists",
        )

    new_entity = RelatedEntity(
        primary_text=item.primary_text,
        secondary_text=item.secondary_text,
        code=item.code,
    )
    db.add(new_entity)
    db.commit()
    db.refresh(new_entity)
    return new_entity


@router.get(
    "/related-entities",
    response_model=List[RelatedEntityResponse],
)
def get_related_entities(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(RelatedEntity).offset(skip).limit(limit).all()


@router.get(
    "/related-entities/{entity_id}",
    response_model=RelatedEntityResponse,
)
def get_related_entity(
    entity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entity = db.query(RelatedEntity).filter(RelatedEntity.id == entity_id).first()
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Related entity not found",
        )
    return entity


@router.put(
    "/related-entities/{entity_id}",
    response_model=RelatedEntityResponse,
)
def update_related_entity(
    entity_id: int,
    item: RelatedEntityCreate,
    user: User = Depends(require_roles(Role.writer, Role.moderator)),
    db: Session = Depends(get_db),
):
    entity = db.query(RelatedEntity).filter(RelatedEntity.id == entity_id).first()
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Related entity not found",
        )

    existing_code = (
        db.query(RelatedEntity)
        .filter(
            RelatedEntity.code == item.code,
            RelatedEntity.id != entity_id,
        )
        .first()
    )
    if existing_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Code already in use by another entity",
        )

    entity.primary_text = item.primary_text
    entity.secondary_text = item.secondary_text
    entity.code = item.code
    db.commit()
    db.refresh(entity)
    return entity


@router.delete("/related-entities/{entity_id}")
def delete_related_entity(
    entity_id: int,
    user: User = Depends(require_roles(Role.moderator)),
    db: Session = Depends(get_db),
):
    entity = db.query(RelatedEntity).filter(RelatedEntity.id == entity_id).first()
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Related entity not found",
        )

    associated_record = (
        db.query(Record).filter(Record.related_entity_id == entity_id).first()
    )
    if associated_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot delete related entity because associated "
                "primary record(s) still exist."
            ),
        )

    db.delete(entity)
    db.commit()
    return {"message": "Successfully deleted related entity"}


# Records: authenticated reads, writer/moderator creates,
# moderator-only deletes.
@router.post(
    "/records",
    response_model=RecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_record(
    item: RecordSchema,
    user: User = Depends(require_roles(Role.writer, Role.moderator)),
    db: Session = Depends(get_db),
):
    related_entity = (
        db.query(RelatedEntity)
        .filter(RelatedEntity.id == item.related_entity_id)
        .first()
    )
    if not related_entity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Referenced related entity does not exist",
        )

    duplicate = db.query(Record).filter(Record.unique_code == item.unique_code).first()
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Record with this unique code already exists",
        )

    new_record = Record(
        primary_field=item.name,
        secondary_field=item.description,
        unique_code=item.unique_code,
        quantity=item.quantity,
        related_entity_id=item.related_entity_id,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return RecordResponse(
        id=new_record.id,
        name=new_record.primary_field,
        description=new_record.secondary_field,
        unique_code=new_record.unique_code,
        quantity=new_record.quantity,
        related_entity_id=new_record.related_entity_id,
        created_at=new_record.created_at,
        updated_at=new_record.updated_at,
    )


@router.get("/records", response_model=List[RecordResponse])
def get_records(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = db.query(Record).offset(skip).limit(limit).all()
    return [
        RecordResponse(
            id=record.id,
            name=record.primary_field,
            description=record.secondary_field,
            unique_code=record.unique_code,
            quantity=record.quantity,
            related_entity_id=record.related_entity_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record in records
    ]


@router.get("/records/{record_id}", response_model=RecordResponse)
def get_record_by_id(
    record_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Error: Cannot find record",
        )

    return RecordResponse(
        id=record.id,
        name=record.primary_field,
        description=record.secondary_field,
        unique_code=record.unique_code,
        quantity=record.quantity,
        related_entity_id=record.related_entity_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get(
    "/related-entities/{entity_id}/records",
    response_model=List[RecordResponse],
)
def get_records_by_related_entity(
    entity_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entity = db.query(RelatedEntity).filter(RelatedEntity.id == entity_id).first()
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Related entity not found",
        )

    records = db.query(Record).filter(Record.related_entity_id == entity_id).all()
    return [
        RecordResponse(
            id=record.id,
            name=record.primary_field,
            description=record.secondary_field,
            unique_code=record.unique_code,
            quantity=record.quantity,
            related_entity_id=record.related_entity_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record in records
    ]


@router.put("/records/{record_id}", response_model=RecordResponse)
def update_record(
    record_id: int,
    item: RecordSchema,
    user: User = Depends(require_roles(Role.writer, Role.moderator)),
    db: Session = Depends(get_db),
):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Error: Cannot find record",
        )

    related_entity = (
        db.query(RelatedEntity)
        .filter(RelatedEntity.id == item.related_entity_id)
        .first()
    )
    if not related_entity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Referenced related entity does not exist",
        )

    duplicate = (
        db.query(Record)
        .filter(
            Record.unique_code == item.unique_code,
            Record.id != record_id,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Record with this unique code already exists",
        )

    record.primary_field = item.name
    record.secondary_field = item.description
    record.unique_code = item.unique_code
    record.quantity = item.quantity
    record.related_entity_id = item.related_entity_id

    db.commit()
    db.refresh(record)
    return RecordResponse(
        id=record.id,
        name=record.primary_field,
        description=record.secondary_field,
        unique_code=record.unique_code,
        quantity=record.quantity,
        related_entity_id=record.related_entity_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.delete("/records/{record_id}")
def delete_record(
    record_id: int,
    user: User = Depends(require_roles(Role.moderator)),
    db: Session = Depends(get_db),
):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Error: Cannot find record",
        )

    db.delete(record)
    db.commit()
    return {"message": "Successfully deleted user record"}
