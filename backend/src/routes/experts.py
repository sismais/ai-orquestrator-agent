"""Expert routes for triage, sync, and configuration endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
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

router = APIRouter(prefix="/api", tags=["experts"])


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
