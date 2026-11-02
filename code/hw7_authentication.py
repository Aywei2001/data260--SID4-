
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

import argparse
import json
import logging
import time
from uuid import UUID, uuid4

from fastapi import FastAPI
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
from kafka.errors import KafkaError
from pydantic import ValidationError

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("recall_service")


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

class GroceryRecallNoticeCreate(RecordSchema):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", strict=True)
    related_entity_id: int = Field(..., gt=0)


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


def kafka_settings():
    prefix = os.environ.get("KAFKA_PREFIX", "s1339").strip()
    if not prefix:
        raise RuntimeError("Set KAFKA_PREFIX to the prefix from Section 0")
    return (
        os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        f"{prefix}_entity_requests",
        f"{prefix}_entity_responses",
    )


def make_producer(servers):
    return KafkaProducer(
        bootstrap_servers=servers,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        acks="all",
    )


def process_request(request, notices):
    correlation_id = request.get("correlation_id")

    def failure(message):
        return {"correlation_id": correlation_id, "success": False, "error": message}

    if not isinstance(correlation_id, str) or not correlation_id.strip():
        return failure("Missing or invalid correlation_id")
    if not isinstance(request.get("reply_to"), str) or not request["reply_to"].strip():
        return failure("Missing or invalid reply_to")
    operation = request.get("operation")
    if operation not in ("CREATE_GROCERY_RECALL_NOTICE", "GET_GROCERY_RECALL_NOTICE"):
        return failure("Unknown operation")
    data = request.get("data")
    if not isinstance(data, dict):
        return failure("data must be an object")

    if operation == "CREATE_GROCERY_RECALL_NOTICE":
        try:
            item = GroceryRecallNoticeCreate.model_validate(data)
        except ValidationError as exc:
            return failure(str(exc))
        if any(n["unique_code"] == item.unique_code for n in notices.values()):
            return failure("Grocery recall notice with this unique_code already exists")
        notice_id = str(uuid4())
        notices[notice_id] = {"grocery_recall_notice_id": notice_id, **item.model_dump()}
        return {
            "correlation_id": correlation_id,
            "success": True,
            "grocery_recall_notice_id": notice_id,
            "message": "Grocery recall notice created",
        }

    notice_id = data.get("grocery_recall_notice_id")
    if not isinstance(notice_id, str):
        return failure("Missing or invalid grocery_recall_notice_id")
    try:
        UUID(notice_id)
    except ValueError:
        return failure("grocery_recall_notice_id must be a UUID")
    if notice_id not in notices:
        return failure("Grocery recall notice not found")
    return {"correlation_id": correlation_id, 
            "success": True,
            "grocery_recall_notice": notices[notice_id]}


def run_worker():
    servers, requests_topic, responses_topic = kafka_settings()
    consumer = KafkaConsumer(
        requests_topic, bootstrap_servers=servers,
        group_id=f"{requests_topic}_worker", auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    producer = make_producer(servers)
    notices = {}
    completed = {}
    try:
        ready = False
        while True:
            batches = consumer.poll(timeout_ms=1000, max_records=1)
            if consumer.assignment() and not ready:
                log.info("Consumer is ready and listening...")
                ready = True
            for message in (m for batch in batches.values() for m in batch):
                try:
                    request = json.loads(message.value)
                except (ValueError, UnicodeDecodeError):
                    log.error("WORKER invalid JSON; no usable reply envelope")
                    consumer.commit()
                    continue
                if not isinstance(request, dict):
                    log.error("WORKER request must be an object")
                    consumer.commit()
                    continue
                log.info("WORKER RECEIVE %s", request)
                cid = request.get("correlation_id")
                if request.get("reply_to") != responses_topic:
                    response = {"correlation_id": cid, "success": False,
                                "error": "reply_to must be the configured response topic"}
                elif isinstance(cid, str) and cid in completed:
                    old_request, old_response = completed[cid]
                    response = old_response if old_request == request else {
                        "correlation_id": cid, "success": False,
                        "error": "correlation_id reused for a different request"}
                else:
                    log.info("WORKER PROCESS operation=%s correlation_id=%s",
                             request.get("operation"), cid)
                    response = process_request(request, notices)
                    if isinstance(cid, str) and cid.strip():
                        completed[cid] = (request, response)
                producer.send(responses_topic, response).get(timeout=15)
                log.info("WORKER REPLY topic=%s %s", responses_topic, response)
                consumer.commit()
    finally:
        consumer.close()
        producer.close()


def send_request(operation, data, timeout=30):
    servers, requests_topic, responses_topic = kafka_settings()
    consumer = KafkaConsumer(bootstrap_servers=servers, group_id=None,
                            enable_auto_commit=False)
    producer = make_producer(servers)
    try:
        partitions = consumer.partitions_for_topic(responses_topic)
        if not partitions:
            raise RuntimeError("Response topic is unavailable; create both topics first")
        assigned = [TopicPartition(responses_topic, p) for p in sorted(partitions)]
        consumer.assign(assigned)
        consumer.seek_to_end(*assigned)
        for partition in assigned:
            consumer.position(partition)
        correlation_id = str(uuid4())
        request = {"correlation_id": correlation_id, "reply_to": responses_topic,
                   "operation": operation, "data": data}
        log.info("CLIENT SEND topic=%s %s", requests_topic, request)
        producer.send(requests_topic, request).get(timeout=15)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for batch in consumer.poll(timeout_ms=500).values():
                for message in batch:
                    try:
                        response = json.loads(message.value)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(response, dict) and response.get("correlation_id") == correlation_id:
                        log.info("CLIENT RECEIVE correlation preserved=True %s", response)
                        return response
        raise TimeoutError(f"No response for correlation_id={correlation_id}")
    finally:
        consumer.close()
        producer.close()


@router.post("/recall-notices", status_code=status.HTTP_201_CREATED)
def create_grocery_recall_notice(
    item: GroceryRecallNoticeCreate,
    user: User = Depends(require_roles(Role.writer, Role.moderator)),
):
    return api_request("CREATE_GROCERY_RECALL_NOTICE", item.model_dump())


@router.get("/recall-notices/{grocery_recall_notice_id}")
def get_grocery_recall_notice(
    grocery_recall_notice_id: str,
    user: User = Depends(get_current_user),
):
    return api_request("GET_GROCERY_RECALL_NOTICE", {"grocery_recall_notice_id": grocery_recall_notice_id})


def api_request(operation, data):
    try:
        response = send_request(operation, data)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except (KafkaError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # Preserve the worker's success flag and correlation ID on errors too.
    if not response["success"]:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content=response)
    return response


# NEW: Standalone application; original file only exported a router.
# If integrating with an existing app, include this router there instead.
app = FastAPI(title="Grocery Supply and Recall Notices")
app.include_router(router)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["worker", "demo"])
    args = parser.parse_args()
    if args.mode == "worker":
        run_worker()
    else:
        from homework_demo import run_demo

        run_demo()
