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

    async def get_by_id(self, chatbot_id: UUID) -> Optional[Chatbot]:
        result = await self.db.execute(
            select(Chatbot).where(Chatbot.id == chatbot_id)
        )
        return result.scalars().first()

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
        offset = (page - 1) * limit

        # Build base filter conditions
        conditions = []
        if authority:
            conditions.append(Chatbot.authority == authority)
        if search:
            conditions.append(
                or_(
                    Chatbot.chatbot_name.ilike(f"%{search}%"),
                    Chatbot.addon_prompt.ilike(f"%{search}%"),
                )
            )

        # Single query using window function — one DB round-trip instead of two
        total_col = func.count().over().label("total")
        query = (
            select(Chatbot, total_col)
            .where(*conditions)
            .order_by(Chatbot.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self.db.execute(query)
        rows = result.all()

        if not rows:
            return [], 0

        chatbots = [row[0] for row in rows]
        total = rows[0][1]

        return chatbots, total

    async def create(self, payload: ChatbotCreate) -> Chatbot:
        chatbot = Chatbot(**payload.model_dump())
        self.db.add(chatbot)
        await self.db.commit()
        await self.db.refresh(chatbot)
        return chatbot

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

    async def update(self, chatbot: Chatbot, payload: ChatbotUpdate) -> Chatbot:
        # Only set attributes that are explicitly provided and not None.
        # This prevents accidental NULL assignment to non-nullable columns
        # like `authority` when callers pass { authority: null }.
        for field, value in payload.model_dump(exclude_unset=True).items():
            if value is None and field != "addon_prompt":
                # Skip explicit nulls to preserve existing DB values for
                # non-nullable fields unless caller truly intends to clear them.
                continue
            setattr(chatbot, field, value)
        self.db.add(chatbot)
        await self.db.commit()
        await self.db.refresh(chatbot)
        return chatbot

    async def soft_delete(self, chatbot: Chatbot) -> Chatbot:
        chatbot.is_active = False
        await self.db.commit()
        await self.db.refresh(chatbot)
        return chatbot

    async def hard_delete(self, chatbot: Chatbot) -> None:
        await self.db.delete(chatbot)
        await self.db.commit()
