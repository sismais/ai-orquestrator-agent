from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


class MessageSchema(BaseModel):
    """Schema for a chat message"""
    id: str
    role: Literal['user', 'assistant']
    content: str
    timestamp: datetime
    model: Optional[str] = None


class SessionHistoryResponse(BaseModel):
    """Schema for a chat session history response"""
    sessionId: str
    messages: list[MessageSchema]
    projectId: Optional[str] = None
    projectName: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    model: Optional[str] = None


class CreateSessionRequest(BaseModel):
    """Request to create a new chat session, escopada a um projeto"""
    project_id: str = Field(alias="projectId")

    class Config:
        populate_by_name = True


class CreateSessionResponse(BaseModel):
    """Response when creating a chat session"""
    sessionId: str
    createdAt: datetime


class SendMessageRequest(BaseModel):
    """Request to send a message"""
    content: str
    model: Optional[str] = 'sonnet-5'


class StreamChunk(BaseModel):
    """A chunk of streamed response"""
    type: Literal['chunk', 'end', 'error']
    content: Optional[str] = None
    messageId: Optional[str] = None
    message: Optional[str] = None


class SessionHistoryResponse(BaseModel):
    """Response with session history"""
    sessionId: str
    messages: list[MessageSchema]
