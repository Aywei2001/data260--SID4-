import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, HTTPException, status
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "s1339")

mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
mongo_db = mongo_client[MONGO_DB_NAME]
records_collection = mongo_db["records"]

router = APIRouter(prefix="/documents", tags=["HW6 documents"])

class RecordStatus(str, Enum):
    planned = "planned"
    active = "active"
    complete = "complete"

class RecordCategory(str, Enum):
    #records based on domain "Grocery Supply and Recall Notices"
    contamination = "Contamination"
    undeclared_allergen = "Undeclared allergen"
    mislabling = "Mislabing"

class DocumentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    status: RecordStatus = RecordStatus.planned
    category: RecordCategory
    due_at: datetime

class DocumentResponse(DocumentCreate):
    id: str
    created_at: datetime
    updated_at: datetime

def to_document_response(document: dict) -> dict:
    """Convert MongoDB's _id field into the API's string id field."""
    document["id"] = str(document.pop("_id"))
    return document


def parse_object_id(document_id: str) -> ObjectId:
    if not ObjectId.is_valid(document_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid document ID format",
        )
    return ObjectId(document_id)

@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED,
)
def create_document(item: DocumentCreate):
    now = datetime.now(timezone.utc)
    document = item.dict()
    document["created_at"] = now
    document["updated_at"] = now

    try:
        result = records_collection.insert_one(document)
        document["_id"] = result.inserted_id
        return to_document_response(document)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A document with this name already exists",
        )
    except PyMongoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not save the document to MongoDB",
        )

@router.get("", response_model=list[DocumentResponse])
def get_documents():
    try:
        return [
            to_document_response(document)
            for document in records_collection.find().sort("created_at", -1)
        ]
    except PyMongoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not retrieve documents from MongoDB",
        )

@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str):
    object_id = parse_object_id(document_id)

    try:
        document = records_collection.find_one({"_id": object_id})
    except PyMongoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not retrieve the document from MongoDB",
        )

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return to_document_response(document)

@router.put("/{document_id}", response_model=DocumentResponse)
def update_document(document_id: str, item: DocumentCreate):
    object_id = parse_object_id(document_id)
    updated_fields = item.dict()
    updated_fields["updated_at"] = datetime.now(timezone.utc)

    try:
        result = records_collection.update_one(
            {"_id": object_id},
            {"$set": updated_fields},
        )
        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        document = records_collection.find_one({"_id": object_id})
        return to_document_response(document)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A document with this name already exists",
        )
    except PyMongoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not update the document in MongoDB",
        )

@router.delete("/{document_id}")
def delete_document(document_id: str):
    object_id = parse_object_id(document_id)

    try:
        result = records_collection.delete_one({"_id": object_id})
    except PyMongoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not delete the document from MongoDB",
        )

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return {"message": "Document deleted successfully"}