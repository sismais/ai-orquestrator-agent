"""Card repository for database operations."""

from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.card import Card
from ..models.activity_log import ActivityType
from ..schemas.card import CardCreate, CardUpdate, ColumnId
from ..services.workflow_rules import is_valid_transition


class CardRepository:
    """Repository for Card database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self, project_id: Optional[str] = None, include_archived: bool = True) -> list[Card]:
        """Get all cards ordered by creation date, optionally scoped by project."""
        query = select(Card)
        if project_id is not None:
            query = query.where(Card.project_id == project_id)
        query = query.order_by(Card.created_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, card_id: str) -> Optional[Card]:
        """Get a card by its ID."""
        result = await self.session.execute(
            select(Card).where(Card.id == card_id)
        )
        return result.scalar_one_or_none()

    async def create(self, card_data: CardCreate, project_id: Optional[str] = None) -> Card:
        """Create a new card in the backlog column."""
        card = Card(
            id=str(uuid4()),
            project_id=project_id if project_id is not None else getattr(card_data, "project_id", None),
            title=card_data.title,
            description=card_data.description,
            column_id="backlog",
            model_plan=card_data.model_plan,
            model_implement=card_data.model_implement,
            model_test=card_data.model_test,
            model_review=card_data.model_review,
            parent_card_id=getattr(card_data, 'parent_card_id', None),
            is_fix_card=getattr(card_data, 'is_fix_card', False),
            test_error_context=getattr(card_data, 'test_error_context', None),
            base_branch=getattr(card_data, 'base_branch', None),
            dependencies=getattr(card_data, 'dependencies', []) or [],
        )
        self.session.add(card)
        await self.session.flush()
        await self.session.refresh(card)

        # Log activity
        from .activity_repository import ActivityRepository
        activity_repo = ActivityRepository(self.session)
        await activity_repo.log_activity(
            card_id=card.id,
            activity_type=ActivityType.CREATED,
            to_column="backlog",
            description=f"Card '{card.title}' criado"
        )

        return card

    async def update(self, card_id: str, card_data: CardUpdate) -> Optional[Card]:
        """Update an existing card."""
        card = await self.get_by_id(card_id)
        if not card:
            return None

        update_data = card_data.model_dump(exclude_unset=True, by_alias=False)

        # Track if any important fields changed
        has_changes = False
        for field, value in update_data.items():
            if value is not None:
                old_value = getattr(card, field, None)
                if old_value != value:
                    has_changes = True
                setattr(card, field, value)

        await self.session.flush()
        await self.session.refresh(card)

        # Log activity if there were changes
        if has_changes:
            from .activity_repository import ActivityRepository
            activity_repo = ActivityRepository(self.session)
            await activity_repo.log_activity(
                card_id=card_id,
                activity_type=ActivityType.UPDATED,
                description=f"Card '{card.title}' atualizado"
            )

        return card

    async def delete(self, card_id: str) -> bool:
        """Delete a card by its ID."""
        card = await self.get_by_id(card_id)
        if not card:
            return False

        await self.session.delete(card)
        await self.session.flush()
        return True

    async def _get_transitions_for_card(self, card) -> dict[str, list[str]]:
        """Transições do workflow do projeto do card (fallback: workflow dev)."""
        from ..models.project_registry import Project
        from ..models.workflow import Workflow
        from ..services.workflow_seed import DEV_WORKFLOW_ID, DEV_TRANSITIONS
        workflow_id = DEV_WORKFLOW_ID
        if card.project_id:
            proj = (await self.session.execute(
                select(Project).where(Project.id == card.project_id)
            )).scalar_one_or_none()
            if proj and proj.workflow_id:
                workflow_id = proj.workflow_id
        wf = (await self.session.execute(
            select(Workflow).where(Workflow.id == workflow_id)
        )).scalar_one_or_none()
        return wf.transitions if wf else DEV_TRANSITIONS

    async def move(self, card_id: str, new_column_id: ColumnId) -> tuple[Optional[Card], Optional[str]]:
        """
        Move a card to a new column with SDLC and finalization validation.

        IMPORTANTE: Este método NÃO limpa o activeExecution do card, permitindo
        que o histórico de logs permaneça acessível mesmo após o card ser movido
        para a coluna "done".

        Returns:
            tuple: (card, error_message) - card if successful, error_message if failed
        """
        card = await self.get_by_id(card_id)
        if not card:
            return None, "Card not found"

        current_column = card.column_id

        # Validação via config do workflow
        if current_column != new_column_id:
            transitions = await self._get_transitions_for_card(card)
            if not is_valid_transition(transitions, current_column, new_column_id):
                allowed = transitions.get(current_column, [])
                return None, f"Invalid transition from '{current_column}' to '{new_column_id}'. Allowed: {allowed}"

        # Mover card para nova coluna
        # IMPORTANTE: NÃO limpar activeExecution aqui para preservar histórico de logs
        card.column_id = new_column_id

        # Marcar timestamp de conclusão quando movido para Done
        if new_column_id == "done" and current_column != "done":
            from datetime import datetime
            card.completed_at = datetime.utcnow()

        await self.session.flush()
        await self.session.refresh(card)

        # Log activity
        from .activity_repository import ActivityRepository
        activity_repo = ActivityRepository(self.session)

        # Determine activity type based on target column
        if new_column_id == "done":
            activity_type = ActivityType.COMPLETED
        elif new_column_id == "archived":
            activity_type = ActivityType.ARCHIVED
        else:
            activity_type = ActivityType.MOVED

        await activity_repo.log_activity(
            card_id=card_id,
            activity_type=activity_type,
            from_column=current_column,
            to_column=new_column_id,
            description=f"Card movido de '{current_column}' para '{new_column_id}'"
        )

        return card, None

    async def update_spec_path(self, card_id: str, spec_path: str) -> Optional[Card]:
        """Update the spec_path for a card."""
        card = await self.get_by_id(card_id)
        if not card:
            return None

        card.spec_path = spec_path
        await self.session.flush()
        await self.session.refresh(card)
        return card

    async def get_active_fix_card(self, parent_card_id: str) -> Optional[Card]:
        """Get an active (non-archived, non-cancelled) fix card for a parent card."""
        result = await self.session.execute(
            select(Card).where(
                Card.parent_card_id == parent_card_id,
                Card.is_fix_card == True,
                Card.column_id.notin_(["done", "archived", "cancelado"])
            )
        )
        return result.scalar_one_or_none()

    async def create_fix_card(self, parent_card_id: str, error_info: dict) -> Optional[Card]:
        """Create a fix card for a parent card with test failure."""
        # Check if there's already an active fix card
        existing_fix = await self.get_active_fix_card(parent_card_id)
        if existing_fix:
            return existing_fix

        # Get parent card to copy configuration
        parent_card = await self.get_by_id(parent_card_id)
        if not parent_card:
            return None

        # Create the fix card
        fix_card_data = CardCreate(
            title=f"[FIX] {parent_card.title[:50]}",
            description=error_info.get("description", ""),
            model_plan=parent_card.model_plan,
            model_implement=parent_card.model_implement,
            model_test=parent_card.model_test,
            model_review=parent_card.model_review,
            parent_card_id=parent_card_id,
            is_fix_card=True,
            test_error_context=error_info.get("context", "")
        )

        return await self.create(fix_card_data)

    async def update_experts(self, card_id: str, experts: dict) -> Optional[Card]:
        """Update the experts field for a card."""
        card = await self.get_by_id(card_id)
        if not card:
            return None

        card.experts = experts
        await self.session.flush()
        await self.session.refresh(card)
        return card

    async def update_dependencies(self, card_id: str, dependencies: list[str]) -> Optional[Card]:
        """Update the dependencies for a card (for parallel execution)."""
        card = await self.get_by_id(card_id)
        if not card:
            return None

        # Assign new list to trigger SQLAlchemy change detection
        card.dependencies = list(dependencies)
        await self.session.flush()
        await self.session.refresh(card)
        return card

