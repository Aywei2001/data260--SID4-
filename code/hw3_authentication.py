from fastapi import APIRouter, Request, Form, FastAPI, Request, Response, HTTPException, status
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_302_FOUND
import time 
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from fastapi.middleware.cors import CORSMiddleware


#set up and get connection from MySQL

DATABASE_URL = "mysql+pymysql://your_user:your_password@localhost/myprefix_rel"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db_connection():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class User(Base):
    __tablename__ = "user_info"
    username_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    user_password = Column(String(255), nullable=False)

class SessionModel(Base):
    __tablename__ = "session_info"
    session_id = Column(String(255), primary_key=True) # Token
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

class Record(Base):
    __tablename__ = "record_info"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    primary_field = Column(String(255), nullable=False)
    secondary_field = Column(Text, nullable=False)

Base.metadata.create_all(bind=engine)

app = FastAPI()

#CORS for react
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter()

#timeout after 5 minutes/300 seconds of inactivity
idle_timeout_seconds = 300

def check_idle_timeout(request: Request) -> str:
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in SESSION_STORE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Login required"
        )

    session_data = SESSION_STORE[session_token]
    current_time = time.time()
    last_activity = session_data.get("last_activity")

    # Inactivity timeout check
    if last_activity and (current_time - last_activity > idle_timeout_seconds):
        del SESSION_STORE[session_token]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Your session has expired, please login again"
        )

    # Update activity timestamp
    session_data["last_activity"] = current_time
    return session_data["email"]

class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class RecordSchema(BaseModel):
    name: str
    description: str

def get_current_user(request: Request, db: Session = Depends(get_db)):
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Welcome! Please login"
        )
    
    # Query session from MySQL sessions table
    db_session = db.query(SessionModel).filter(SessionModel.id == session_token).first()
    
    if not db_session or db_session.expires_at < datetime.datetime.utcnow():
        if db_session:
            db.delete(db_session)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Your session has expired, please login again"
        )
    
    return db_session.user_id


#get the login page
@app.post("/login")
def login(credentials: LoginSchema, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()
    
    # Note: Replace user.password_hash check with passlib hash check in production
    if not user or user.password_hash != credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid email or password"
        )
    
    token = secrets.token_hex(32)
    expires = datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
    
    # Persist session in MySQL sessions table
    new_session = SessionModel(id=token, user_id=user.id, expires_at=expires)
    db.add(new_session)
    db.commit()
    
    # Set Opaque token in HTTP-only cookie
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False
    )
    return {"message": "Login successful"}


#logout out of users account
@app.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        db.query(SessionModel).filter(SessionModel.id == token).delete()
        db.commit()
    response.delete_cookie("session_token")
    return {"message": "Logout successful"}

#get records
@router.get("/records")
def get_records(user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    records = db.query(Record).all()
    formatted_records = [
        {"id": r.id, "name": r.primary_field, "description": r.secondary_field}
        for r in records
    ]
    return {"records": formatted_records}

#get user records by id
@router.get("/records/{record_id}")
def get_record_by_id(record_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Error: Cannot find user record")
    return {"id": record.id, "name": record.primary_field, "description": record.secondary_field}

#create a user record
@router.post("/records", status_code=status.HTTP_201_CREATED)
def create_record(item: RecordSchema, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    new_record = Record(primary_field=item.name, secondary_field=item.description)
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return {"id": new_record.id, "name": new_record.primary_field, "description": new_record.secondary_field}

#update a user record
@router.put("/records/{record_id}")
def update_record(record_id: int, item: RecordSchema, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Error: Cannot find user record")
    
    record.primary_field = item.name
    record.secondary_field = item.description
    db.commit()
    return {"message": "Successfully updated user record"}

#delete a user record
@router.delete("/records/{record_id}")
def delete_record(record_id: int, user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(Record).filter(Record.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Error: Cannot find user record")
    
    db.delete(record)
    db.commit()
    return {"message": "Successfully deleted user record"}