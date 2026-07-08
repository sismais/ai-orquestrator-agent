"""
Chat API routes for WebSocket-based real-time chat.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import JSONResponse
import json
from ..database import async_session_maker
from ..repositories.project_repository import ProjectRepository
from ..services.chat_service import get_chat_service
from ..schemas.chat import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionHistoryResponse,
    MessageSchema,
)


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_chat_session(body: CreateSessionRequest):
    """
    Create a new chat session, escopada a um projeto.

    Returns:
        CreateSessionResponse: Session ID and creation timestamp
    """
    chat_service = get_chat_service()
    session_data = await chat_service.create_session(project_id=body.project_id)

    return CreateSessionResponse(
        sessionId=session_data["sessionId"],
        createdAt=session_data["createdAt"],
    )


@router.get("/sessions/{session_id}", response_model=SessionHistoryResponse)
async def get_chat_history(session_id: str):
    """
    Get the chat history for a session.

    Args:
        session_id: The session ID to retrieve

    Returns:
        SessionHistoryResponse: Session history with all messages

    Raises:
        HTTPException: 404 if session not found
    """
    chat_service = get_chat_service()
    session = await chat_service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Resolve nome do projeto dono da sessao para exibir na UI do chat.
    async with async_session_maker() as db:
        project = await ProjectRepository(db).get_by_id(session["project_id"])
    project_name = project.name if project else None

    # Convert messages to schema format
    messages = [
        MessageSchema(
            id=f"{session_id}-{idx}",
            role=msg["role"],
            content=msg["content"],
            timestamp=msg["timestamp"],
            model=msg.get("model"),
        )
        for idx, msg in enumerate(session["messages"])
    ]

    return SessionHistoryResponse(
        sessionId=session_id,
        messages=messages,
        projectId=session["project_id"],
        projectName=project_name,
    )


@router.delete("/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    """
    Delete a chat session.

    Args:
        session_id: The session ID to delete

    Returns:
        JSON: Success message

    Raises:
        HTTPException: 404 if session not found
    """
    chat_service = get_chat_service()
    success = await chat_service.delete_session(session_id)

    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return JSONResponse(
        content={"message": "Session deleted successfully"},
        status_code=200,
    )


@router.websocket("/ws/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time chat with streaming responses.

    The WebSocket expects JSON messages with format:
    {
        "type": "message",
        "content": "user message text",
        "model": "sonnet-5" (optional, defaults to sonnet-5)
    }

    And sends back JSON responses:
    {
        "type": "chunk" | "end" | "error",
        "content": "response chunk text" (for chunk type),
        "messageId": "unique-message-id",
        "message": "error message" (for error type)
    }

    Args:
        websocket: The WebSocket connection
        session_id: The chat session ID
    """
    chat_service = get_chat_service()
    await websocket.accept()

    print(f"[ChatWebSocket] Client connected to session: {session_id}")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            try:
                message_data = json.loads(data)
                message_type = message_data.get("type")
                message_content = message_data.get("content")
                message_model = message_data.get("model", "sonnet-5")

                # Heartbeat: responde pong ao ping do cliente (useWebSocketBase),
                # senao o cliente estoura o pongTimeout e reconecta em loop.
                if message_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue

                if message_type != "message" or not message_content:
                    await websocket.send_text(
                        json.dumps({
                            "type": "error",
                            "message": "Invalid message format",
                        })
                    )
                    continue

                # Stream response from chat service with selected model
                async for chunk in chat_service.send_message(
                    session_id=session_id,
                    message=message_content,
                    model=message_model,
                ):
                    await websocket.send_text(json.dumps(chunk))

            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "message": "Invalid JSON format",
                    })
                )
            except Exception as e:
                error_msg = f"Error processing message: {str(e)}"
                print(f"[ChatWebSocket] {error_msg}")
                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "message": error_msg,
                    })
                )

    except WebSocketDisconnect:
        print(f"[ChatWebSocket] Client disconnected from session: {session_id}")
    except Exception as e:
        print(f"[ChatWebSocket] Unexpected error: {str(e)}")
        try:
            await websocket.close()
        except:
            pass


@router.get("/sessions")
async def list_sessions(project_id: str = Query(..., alias="projectId")):
    """
    List chat sessions de um projeto.

    Args:
        project_id: The project to list sessions for

    Returns:
        JSON: List of sessions and count
    """
    chat_service = get_chat_service()
    sessions = await chat_service.list_sessions(project_id)

    # Resolve nomes dos projetos donos de cada sessao (para exibir na lista de
    # chats da UI). Como a lista ja e escopada por project_id, todas pertencem
    # ao mesmo projeto — mas trazemos o nome pra UI nao precisar de outra rota.
    async with async_session_maker() as db:
        project = await ProjectRepository(db).get_by_id(project_id)
    project_name = project.name if project else None

    return JSONResponse(
        content={
            "sessions": [
                {
                    "sessionId": s.id,
                    "title": s.title,
                    "projectId": s.project_id,
                    "projectName": project_name,
                    "createdAt": s.created_at.isoformat(),
                    "updatedAt": s.updated_at.isoformat(),
                }
                for s in sessions
            ],
            "count": len(sessions),
        },
        status_code=200,
    )
