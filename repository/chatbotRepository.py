from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from model.Chatbot import Chatbot, AuthorityEnum
from schema.chatbotSchema import ChatbotCreate, ChatbotUpdate


class ChatbotRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db
        self.chatbot: Chatbot | None = None  # Akan di-set di service sebelum operasi update/delete

    async def get_by_id(self, chatbot_id: UUID) -> Optional[Chatbot]:
        result = await self.db.execute(
            select(Chatbot).where(Chatbot.id == chatbot_id)
        )
        self.chatbot: Chatbot | None = result.scalars().first()
        return self.chatbot

    async def get_by_chatbot_name(self, chatbot_name: str) -> Optional[Chatbot]:
        result = await self.db.execute(
            select(Chatbot).where(
                (func.lower(Chatbot.chatbot_name) == chatbot_name.lower()) &
                (Chatbot.is_active == True)
            )
        )
        return result.scalars().first()

    async def get_active_by_authority(self, authority: AuthorityEnum | str) -> Optional[Chatbot]:
        authority_value = authority.value if isinstance(authority, AuthorityEnum) else authority
        result = await self.db.execute(
            select(Chatbot).where(
                (Chatbot.authority == authority_value) &
                (Chatbot.is_active == True)
            )
        )
        return result.scalars().first()

    async def get_all(self, page, limit, authority=None, search=None):
        query = select(Chatbot).where(Chatbot.is_active == True)
        offset = (page - 1) * limit

        if authority:
            query = query.where(Chatbot.authority == authority)
        if search:
            query = query.where(
                or_(
                    Chatbot.chatbot_name.ilike(f"%{search}%"),
                    Chatbot.addon_prompt.ilike(f"%{search}%"),
                )
            )

        count_result = await self.db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar_one()

        result = await self.db.execute(
            query.order_by(Chatbot.created_at.desc())
            .offset(offset)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return result.scalars().all(), total

    async def create(self, payload: ChatbotCreate) -> Chatbot:
        self.chatbot: Chatbot = Chatbot(**payload.model_dump())
        self.db.add(self.chatbot)
        await self.db.commit()
        await self.db.refresh(self.chatbot)
        return self.chatbot

    async def deactivate_active_by_authority(
        self,
        authority: AuthorityEnum,
        exclude_id: Optional[UUID] = None,
    ) -> None:
        stmt = (
            update(Chatbot)
            .where((Chatbot.authority == authority) & (Chatbot.is_active == True))
            .values(is_active=False)
        )
        if exclude_id is not None:
            stmt = stmt.where(Chatbot.id != exclude_id)

        await self.db.execute(stmt)
        self.db.expire_all()

    async def update(self, payload: ChatbotUpdate) -> Chatbot:
        assert self.chatbot is not None
        # Only set attributes that are explicitly provided and not None.
        # This prevents accidental NULL assignment to non-nullable columns
        # like `authority` when callers pass { authority: null }.
        for field, value in payload.model_dump(exclude_unset=True).items():
            if value is None and field != "addon_prompt":
                # Skip explicit nulls to preserve existing DB values for
                # non-nullable fields unless caller truly intends to clear them.
                continue
            setattr(self.chatbot, field, value)
        self.db.add(self.chatbot)
        await self.db.commit()
        await self.db.refresh(self.chatbot)
        return self.chatbot

    async def soft_delete(self) -> Chatbot:
        assert self.chatbot is not None
        self.chatbot.is_active = False
        await self.db.commit()
        await self.db.refresh(self.chatbot)
        return self.chatbot

    async def hard_delete(self) -> None:
        assert self.chatbot is not None
        await self.db.delete(self.chatbot)
        await self.db.commit()
        self.chatbot: Chatbot | None = None
