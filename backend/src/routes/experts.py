"""Expert routes for triage, sync, and configuration endpoints."""

from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..repositories.card_repository import CardRepository
from ..schemas.expert import (
    ExpertTriageRequest,
    ExpertTriageResponse,
    ExpertSyncRequest,
    ExpertSyncResponse,
    ExpertsUpdateRequest,
    ExpertMatch,
)
from ..services.expert_triage_service import identify_experts
from ..services.expert_sync_service import sync_experts
from ..services.expert_init_service import expert_init_service
from ..config.experts import get_experts, clear_experts_cache
from .projects import get_project_manager

router = APIRouter(prefix="/api", tags=["experts"])


# =============================================================================
# Schemas para novos endpoints
# =============================================================================

class ExpertSuggestion(BaseModel):
    """Sugestão de expert baseada na análise da codebase."""
    id: str
    name: str
    keywords: List[str]
    file_patterns: List[str]
    detected: bool = True


class CreateExpertsRequest(BaseModel):
    """Request para criar experts."""
    experts: List[ExpertSuggestion]


class ExpertStatusResponse(BaseModel):
    """Response com status dos experts do projeto."""
    success: bool
    project_path: Optional[str] = None
    is_orchestrator: bool = False
    has_experts: bool = False
    experts: Dict[str, Any] = {}


# =============================================================================
# Novos endpoints para configuração de experts
# =============================================================================

@router.get("/experts/analyze")
async def analyze_codebase_for_experts():
    """
    Analisa a codebase do projeto atual e sugere experts.

    Só funciona quando há um projeto externo carregado.
    Se não há projeto carregado (orquestrador), retorna erro apropriado.
    """
    try:
        manager = get_project_manager()

        # Verificar se há projeto externo carregado
        if manager.current_project is None:
            return {
                "success": False,
                "is_orchestrator": True,
                "message": "Nenhum projeto externo carregado. Os experts do orquestrador são usados automaticamente.",
                "suggestions": []
            }

        project_path = str(manager.current_project)

        # Analisar codebase
        suggestions = await expert_init_service.analyze_codebase(project_path)

        return {
            "success": True,
            "is_orchestrator": False,
            "project_path": project_path,
            "project_name": manager.current_project.name,
            "suggestions": suggestions
        }

    except Exception as e:
        print(f"[ExpertsAnalyze] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/experts/create")
async def create_experts(request: CreateExpertsRequest):
    """
    Cria experts selecionados no projeto atual.

    Só funciona quando há um projeto externo carregado.
    """
    try:
        manager = get_project_manager()

        # Verificar se há projeto externo carregado
        if manager.current_project is None:
            raise HTTPException(
                status_code=400,
                detail="Nenhum projeto externo carregado. Não é possível criar experts no orquestrador por esta rota."
            )

        project_path = str(manager.current_project)

        results = []
        for expert in request.experts:
            result = await expert_init_service.create_expert(
                project_path,
                expert.id,
                {
                    "name": expert.name,
                    "keywords": expert.keywords,
                    "file_patterns": expert.file_patterns
                }
            )
            results.append({
                "id": expert.id,
                "name": expert.name,
                **result
            })

        # Limpar cache para recarregar experts
        clear_experts_cache(project_path)

        return {
            "success": True,
            "project_path": project_path,
            "created": results
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ExpertsCreate] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/experts/{expert_id}")
async def delete_expert(expert_id: str):
    """
    Remove um expert do projeto atual.

    Só funciona quando há um projeto externo carregado.
    """
    try:
        manager = get_project_manager()

        # Verificar se há projeto externo carregado
        if manager.current_project is None:
            raise HTTPException(
                status_code=400,
                detail="Nenhum projeto externo carregado. Não é possível remover experts do orquestrador."
            )

        project_path = str(manager.current_project)

        success = await expert_init_service.delete_expert(project_path, expert_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Expert '{expert_id}' não encontrado no projeto"
            )

        # Limpar cache para recarregar experts
        clear_experts_cache(project_path)

        return {
            "success": True,
            "deleted": expert_id
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ExpertsDelete] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/experts/status", response_model=ExpertStatusResponse)
async def get_experts_status():
    """
    Retorna status dos experts do projeto atual.

    - Se não há projeto carregado: retorna experts do orquestrador
    - Se há projeto carregado: retorna experts do projeto (pode ser vazio)
    """
    try:
        manager = get_project_manager()

        # Verificar contexto
        if manager.current_project is None:
            # Sem projeto = orquestrador
            experts = get_experts(None)
            return ExpertStatusResponse(
                success=True,
                project_path=None,
                is_orchestrator=True,
                has_experts=len(experts) > 0,
                experts=experts
            )

        # Com projeto = carregar do projeto
        project_path = str(manager.current_project)
        experts = get_experts(project_path)

        return ExpertStatusResponse(
            success=True,
            project_path=project_path,
            is_orchestrator=False,
            has_experts=len(experts) > 0,
            experts=experts
        )

    except Exception as e:
        print(f"[ExpertsStatus] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Endpoints existentes (triage, sync, update)
# =============================================================================


@router.post("/expert-triage", response_model=ExpertTriageResponse)
async def expert_triage_endpoint(
    request: ExpertTriageRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Identify relevant experts for a card based on its title and description.

    This endpoint analyzes the card content and returns a list of expert agents
    that should be consulted during planning.

    Comportamento:
    - Sem projeto carregado: usa experts do orquestrador
    - Com projeto carregado: usa experts do projeto (pode ser vazio)
    """
    try:
        # Resolve o projeto pelo card (registry), nao mais pelo ProjectManager.
        card_repo = CardRepository(db)
        card = await card_repo.get_by_id(request.card_id)
        project_path = None
        if card and card.project_id:
            from ..repositories.project_repository import ProjectRepository
            project = await ProjectRepository(db).get_by_id(card.project_id)
            if project:
                project_path = project.path

        # cwd é onde os knowledge files estão
        cwd = project_path if project_path else str(Path.cwd().parent)

        # Identify experts based on card content and project context
        experts = identify_experts(
            title=request.title,
            description=request.description,
            cwd=cwd,
            project_path=project_path
        )

        # Save experts to the card in database
        if experts:
            # Convert ExpertMatch objects to dict for JSON storage
            experts_dict = {
                expert_id: match.model_dump()
                for expert_id, match in experts.items()
            }
            await card_repo.update_experts(request.card_id, experts_dict)
            await db.commit()

        return ExpertTriageResponse(
            success=True,
            card_id=request.card_id,
            experts=experts
        )

    except Exception as e:
        print(f"[ExpertTriage] Error: {e}")
        return ExpertTriageResponse(
            success=False,
            card_id=request.card_id,
            experts={},
            error=str(e)
        )


@router.post("/expert-sync", response_model=ExpertSyncResponse)
async def expert_sync_endpoint(
    request: ExpertSyncRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Synchronize expert knowledge bases after a card is completed.

    This endpoint checks which files were modified and triggers sync
    for relevant experts to update their KNOWLEDGE.md files.
    """
    try:
        # Use parent directory as working directory
        cwd = str(Path.cwd().parent)

        # Get card to check for branch name
        repo = CardRepository(db)
        card = await repo.get_by_id(request.card_id)
        branch_name = card.branch_name if card else None

        # Run sync for all identified experts
        synced_results = await sync_experts(
            card_id=request.card_id,
            experts=request.experts,
            branch_name=branch_name,
            cwd=cwd
        )

        return ExpertSyncResponse(
            success=True,
            card_id=request.card_id,
            synced_experts=synced_results
        )

    except Exception as e:
        print(f"[ExpertSync] Error: {e}")
        return ExpertSyncResponse(
            success=False,
            card_id=request.card_id,
            synced_experts=[],
            error=str(e)
        )


@router.patch("/cards/{card_id}/experts")
async def update_card_experts(
    card_id: str,
    request: ExpertsUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Update the experts field of a card.

    Used to persist expert identification results to the card.
    """
    try:
        repo = CardRepository(db)

        # Convert ExpertMatch objects to dict for JSON storage
        experts_dict = {
            expert_id: match.model_dump() if hasattr(match, 'model_dump') else match
            for expert_id, match in request.experts.items()
        }

        card = await repo.update_experts(card_id, experts_dict)
        await db.commit()

        return {
            "success": True,
            "cardId": card_id,
            "experts": experts_dict
        }

    except Exception as e:
        print(f"[UpdateExperts] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
