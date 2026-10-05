import datetime
import secrets
from typing import Optional, List
from fastapi import APIRouter, Request, Response, HTTPException, status, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker, relationship
from sqlalchemy.exc import IntegrityError
from passlib.context import CryptContext 


DATABASE_URL = "mysql+pymysql://username:password@localhost:8439/my_db_info"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "user_info"
    
    username_id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    user_password = Column(String(255), nullable=False)


class SessionModel(Base):
    __tablename__ = "session_info"
    
    session_id = Column(String(255), primary_key=True)
    user_id = Column(Integer, ForeignKey("user_info.username_id", ondelete="CASCADE"), nullable=False)
    time_created = Column(DateTime, default=datetime.datetime.utcnow)
    time_expiration = Column(DateTime, nullable=False)


class RelatedEntity(Base):
    __tablename__ = "related_entities"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)  
    primary_text = Column(String(255), nullable=False)                     
    secondary_text = Column(Text, nullable=False)                           
    code = Column(String(100), unique=True, nullable=False, index=True)    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)         
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow) 

    records = relationship("Record", back_populates="related_entity")


class Record(Base):
    __tablename__ = "record_info"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)  
    primary_field = Column(String(255), nullable=False)                     
    secondary_field = Column(Text, nullable=False)
    unique_code = Column(String(100), unique=True, nullable=False)         
    quantity = Column(Integer, default=10, nullable=False)                  
    
    related_entity_id = Column(Integer, ForeignKey("related_entities.id"), nullable=False) 
    created_at = Column(DateTime, default=datetime.datetime.utcnow)         
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow) 

    related_entity = relationship("RelatedEntity", back_populates="records")


Base.metadata.create_all(bind=engine)

router = APIRouter()


class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class RelatedEntityCreate(BaseModel):
    primary_text: str = Field(..., min_length=1)
    secondary_text: str = Field(..., min_length=1)
    code: str = Field(..., min_length=3, max_length=50, pattern=r"^[A-Z0-9_-]+$") 

class RelatedEntityResponse(RelatedEntityCreate):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        orm_mode = True

class RecordSchema(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    unique_code: str = Field(..., min_length=3, max_length=50, pattern=r"^[A-Z0-9_-]+$") 
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

    class Config:
        orm_mode = True


def get_current_user(request: Request, db: Session = Depends(get_db)):
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Welcome! Please login"
        )
    
    db_session = db.query(SessionModel).filter(SessionModel.session_id == session_token).first()
    
    if not db_session or db_session.time_expiration < datetime.datetime.utcnow():
        if db_session:
            db.delete(db_session)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Your session has expired, please login again"
        )
    
    return db_session.user_id


@router.post("/login")
def login(credentials: LoginSchema, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()
    
    if not user or not pwd_context.verify(credentials.password, user.user_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid email or password"
        )
    
    token = secrets.token_hex(32)
    expires = datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
    
    # Updated to match DB column names: time_expiration
    new_session = SessionModel(
        session_id=token, 
        user_id=user.username_id, 
        time_expiration=expires
    )
    db.add(new_session)
    db.commit()
    
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False
    )
    return {"message": "Login successful"}

@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        db.query(SessionModel).filter(SessionModel.session_id == token).delete()
        db.commit()
    response.delete_cookie("session_token")
    return {"message": "Logout successful"}


@router.post("/related-entities", response_model=RelatedEntityResponse, status_code=status.HTTP_201_CREATED)
def create_related_entity(item: RelatedEntityCreate, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.query(RelatedEntity).filter(RelatedEntity.code == item.code).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Related entity with this code already exists")
    
    new_entity = RelatedEntity(
        primary_text=item.primary_text,
        secondary_text=item.secondary_text,
        code=item.code
    )
    db.add(new_entity)
    db.commit()
    db.refresh(new_entity)
    return new_entity

@router.get("/related-entities", response_model=List[RelatedEntityResponse])
def get_related_entities(
    skip: int = Query(0, ge=0), 
    limit: int = Query(10, ge=1, le=100), 
    user_id: int = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    return db.query(RelatedEntity).offset(skip).limit(limit).all()

@router.get("/related-entities/{entity_id}", response_model=RelatedEntityResponse)
def get_related_entity(entity_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    entity = db.query(RelatedEntity).filter(RelatedEntity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Related entity not found")
    return entity

@router.put("/related-entities/{entity_id}", response_model=RelatedEntityResponse)
def update_related_entity(entity_id: int, item: RelatedEntityCreate, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    entity = db.query(RelatedEntity).filter(RelatedEntity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Related entity not found")
    
    existing_code = db.query(RelatedEntity).filter(RelatedEntity.code == item.code, RelatedEntity.id != entity_id).first()
    if existing_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code already in use by another entity")
        
    entity.primary_text = item.primary_text
    entity.secondary_text = item.secondary_text
    entity.code = item.code
    db.commit()
    db.refresh(entity)
    return entity

@router.delete("/related-entities/{entity_id}")
def delete_related_entity(entity_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    entity = db.query(RelatedEntity).filter(RelatedEntity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Related entity not found")
    
    associated_records = db.query(Record).filter(Record.related_entity_id == entity_id).first()
    if associated_records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Cannot delete related entity because associated primary record(s) still exist."
        )
    
    db.delete(entity)
    db.commit()
    return {"message": "Successfully deleted related entity"}


@router.post("/records", response_model=RecordResponse, status_code=status.HTTP_201_CREATED)
def create_record(item: RecordSchema, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.query(RelatedEntity).filter(RelatedEntity.id == item.related_entity_id).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Referenced related entity does not exist")
    
    if db.query(Record).filter(Record.unique_code == item.unique_code).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Record with this unique code already exists")

    new_record = Record(
        primary_field=item.name, 
        secondary_field=item.description,
        unique_code=item.unique_code,
        quantity=item.quantity,
        related_entity_id=item.related_entity_id
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
        updated_at=new_record.updated_at
    )

@router.get("/records", response_model=List[RecordResponse])
def get_records(
    skip: int = Query(0, ge=0), 
    limit: int = Query(10, ge=1, le=100), 
    user_id: int = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    records = db.query(Record).offset(skip).limit(limit).all()
    return [
        RecordResponse(
            id=r.id, 
            name=r.primary_field, 
            description=r.secondary_field,
            unique_code=r.unique_code,
            quantity=r.quantity,
            related_entity_id=r.related_entity_id,
            created_at=r.created_at,
            updated_at=r.updated_at
        )
        for r in records
    ]

@router.get("/records/{record_id}", response_model=RecordResponse)
def get_record_by_id(record_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Error: Cannot find record")
    return RecordResponse(
        id=record.id, 
        name=record.primary_field, 
        description=record.secondary_field,
        unique_code=record.unique_code,
        quantity=record.quantity,
        related_entity_id=record.related_entity_id,
        created_at=record.created_at,
        updated_at=record.updated_at
    )

@router.get("/related-entities/{entity_id}/records", response_model=List[RecordResponse])
def get_records_by_related_entity(entity_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.query(RelatedEntity).filter(RelatedEntity.id == entity_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Related entity not found")
    
    records = db.query(Record).filter(Record.related_entity_id == entity_id).all()
    return [
        RecordResponse(
            id=r.id, 
            name=r.primary_field, 
            description=r.secondary_field,
            unique_code=r.unique_code,
            quantity=r.quantity,
            related_entity_id=r.related_entity_id,
            created_at=r.created_at,
            updated_at=r.updated_at
        )
        for r in records
    ]

@router.put("/records/{record_id}", response_model=RecordResponse)
def update_record(record_id: int, item: RecordSchema, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Error: Cannot find record")
    
    if not db.query(RelatedEntity).filter(RelatedEntity.id == item.related_entity_id).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Referenced related entity does not exist")

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
        updated_at=record.updated_at
    )

@router.delete("/records/{record_id}")
def delete_record(record_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Error: Cannot find record")
    
    db.delete(record)
    db.commit()
    return {"message": "Successfully deleted user record"}