"""Local operator-authenticated chat and intake; no provider or action authority in request bodies."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from trading_core.api import ENGINE_DEPENDENCY, require_operator
from trading_core.conversation import ConversationBusy, Conversations, Provider
from trading_core.intake import Intake, Submission
from trading_core.intelligence.records import Records
from trading_core.work import Record

router = APIRouter()
AUTH = [Depends(require_operator)]


def records(engine=ENGINE_DEPENDENCY):
    return Records(engine.store)


DEP = Depends(records)


class NewConversation(Record):
    provider: Provider = "CODEX"


class Message(Record):
    content: str = Field(min_length=1, max_length=6000)


class Disposition(Record):
    status: Literal["CONSIDERING", "USED", "DEFERRED", "REJECTED"]
    rationale: str = Field(min_length=1, max_length=4000)


@router.get("/core/chat", include_in_schema=False)
def chat_shell():
    return FileResponse(Path(__file__).parent / "static/conversation.html")


@router.get("/assets/conversation.js", include_in_schema=False)
def chat_script():
    return FileResponse(
        Path(__file__).parent / "static/conversation.js", media_type="text/javascript"
    )


@router.get("/api/core/conversations", dependencies=AUTH)
def conversations(service=DEP):
    return Conversations(service).list()


@router.post("/api/core/conversations", dependencies=AUTH)
def create_conversation(value: NewConversation, service=DEP):
    return {"id": Conversations(service).create(value.provider)}


@router.get("/api/core/conversations/{identifier}", dependencies=AUTH)
def conversation(identifier: str, service=DEP):
    chat = Conversations(service)
    return {"conversation": chat.get(identifier), "messages": chat.messages(identifier)}


@router.post("/api/core/conversations/{identifier}/messages", dependencies=AUTH)
def reply(identifier: str, value: Message, service=DEP):
    try:
        return Conversations(service).reply(identifier, value.content)
    except ConversationBusy as exc:
        raise HTTPException(
            409,
            "Another reply is already in progress. This message was not saved; try again when it finishes.",
        ) from exc
    except (KeyError, ValueError, PermissionError):
        raise
    except Exception as exc:
        raise HTTPException(
            503,
            "The selected provider could not finish. Your saved conversation contains the failure status.",
        ) from exc


@router.get("/api/core/intake", dependencies=AUTH)
def intake(destination: Literal["core", "triad"] = "core", service=DEP):
    return Intake(service).list(destination)


@router.post("/api/core/intake", dependencies=AUTH)
def submit(value: Submission, service=DEP):
    identifier = Intake(service).submit(
        value, authenticated=True, channel="local_api", source="Core operator"
    )
    return {"id": identifier, "automatic_execution": False}


@router.post("/api/core/intake/{identifier}/disposition", dependencies=AUTH)
def disposition(identifier: str, value: Disposition, service=DEP):
    return {"id": Intake(service).disposition(identifier, value.status, value.rationale)}
