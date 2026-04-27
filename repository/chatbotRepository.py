from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from model.Chatbot import Chatbot, AuthorityEnum
from schema.chatbotSchema import ChatbotCreate, ChatbotUpdate


class ChatbotRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chatbot: Chatbot = None  # Akan di-set di service sebelum operasi update/delete

    async def get_by_id(self, chatbot_id: UUID) -> Optional[Chatbot]:
        result = await self.db.execute(
            select(Chatbot).where(Chatbot.id == chatbot_id)
        )
        self.chatbot = result.scalars().first()
        return self.chatbot

    async def get_by_nama(self, nama_chatbot: str) -> Optional[Chatbot]:
        result = await self.db.execute(
            select(Chatbot).where(
                (func.lower(Chatbot.nama_chatbot) == nama_chatbot.lower()) & (
                    Chatbot.is_active == True)
            )
        )
        self.chatbot = result.scalars().first()
        return self.chatbot

    async def get_all(self, skip, limit, otoritas=None, search=None):
        query = select(Chatbot)

        if otoritas:
            query = query.where(Chatbot.otoritas == otoritas)
        if search:
            query = query.where(
                or_(
                    Chatbot.nama_chatbot.ilike(f"%{search}%"),
                    Chatbot.addon_prompt.ilike(f"%{search}%"),
                )
            )

        count_result = await self.db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar()

        result = await self.db.execute(
            query.order_by(Chatbot.created_at.desc())
            .offset(skip)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return result.scalars().all(), total

    async def create(self, payload: ChatbotCreate) -> Chatbot:
        self.chatbot = Chatbot(**payload.model_dump())
        self.db.add(self.chatbot)
        await self.db.commit()
        await self.db.refresh(self.chatbot)
        return self.chatbot

    async def deactivate_active_by_otoritas(
        self,
        otoritas: AuthorityEnum,
        exclude_id: Optional[UUID] = None,
    ) -> None:
        stmt = (
            update(Chatbot)
            .where((Chatbot.otoritas == otoritas) & (Chatbot.is_active == True))
            .values(is_active=False)
        )
        if exclude_id is not None:
            stmt = stmt.where(Chatbot.id != exclude_id)

        await self.db.execute(stmt)
        self.db.expire_all()

    async def update(self, payload: ChatbotUpdate) -> Chatbot:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(self.chatbot, field, value)
        self.db.add(self.chatbot)
        await self.db.commit()
        await self.db.refresh(self.chatbot)
        return self.chatbot

    async def soft_delete(self) -> Chatbot:
        self.chatbot.is_active = False
        await self.db.commit()
        await self.db.refresh(self.chatbot)
        return self.chatbot

    async def hard_delete(self) -> None:
        await self.db.delete(self.chatbot)
        await self.db.commit()
        self.chatbot = None
