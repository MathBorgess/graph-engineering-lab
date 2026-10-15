"""Contratos de estado e ciclo de vida do agente de voz."""

from typing import Annotated, Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


ProposalStatus = Literal["pending", "confirmed", "rejected", "executed", "failed"]
ToolExecutionStatus = Literal["success", "failure", "unknown"]


class ActionProposal(BaseModel):
    """Proposta de ação que requer confirmação humana explícita antes da execução."""
    proposal_id: str
    tool_name: str
    arguments: Dict[str, Any]
    summary_for_user: str
    status: ProposalStatus = "pending"
    version: int = 1


class ToolResult(BaseModel):
    """Evidência operacional retornada pela execução de uma tool."""
    proposal_id: Optional[str] = None
    tool_name: str
    status: ToolExecutionStatus
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retryable: bool = False


class VoiceTurn(BaseModel):
    """Metadados do turno conversacional de voz."""
    session_id: str
    turn_id: str
    user_id: str
    transcript: str
    status: Literal["active", "interrupted", "completed"] = "active"


class ConversationState(BaseModel):
    """Estado principal do LangGraph persistido a cada superstep."""
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)
    user_id: str = "default_user"
    thread_id: str = "default_thread"
    
    # Máquina de estados para Two-Phase Commit de ações mutantes
    pending_proposal: Optional[ActionProposal] = None
    last_tool_result: Optional[ToolResult] = None
    
    # Metadados de voz do turno atual
    active_turn: Optional[VoiceTurn] = None
