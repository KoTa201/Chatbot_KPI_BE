from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from model.Chatbot import Chatbot, AuthorityEnum
from schema.chatbotSchema import ChatbotCreate, ChatbotUpdate


from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_


class ChatbotRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, chatbot_id: int) -> Optional[Chatbot]:
        result = await self.db.execute(
            select(Chatbot).where(Chatbot.id ==
                                  chatbot_id, Chatbot.is_active == True)
        )
        return result.scalars().first()

    async def get_by_nama(self, nama_chatbot: str) -> Optional[Chatbot]:
        result = await self.db.execute(
            select(Chatbot).where(
                func.lower(Chatbot.nama_chatbot) == nama_chatbot.lower(),
                Chatbot.is_active == True,
            )
        )
        return result.scalars().first()

    async def get_all(self, skip, limit, otoritas=None, search=None):
        query = select(Chatbot).where(Chatbot.is_active == True)

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
            query.order_by(Chatbot.created_at.desc()).offset(skip).limit(limit)
        )
        return result.scalars().all(), total

    async def create(self, payload: ChatbotCreate) -> Chatbot:
        chatbot = Chatbot(**payload.model_dump())
        self.db.add(chatbot)
        await self.db.commit()
        await self.db.refresh(chatbot)
        return chatbot

    async def update(self, chatbot: Chatbot, payload: ChatbotUpdate) -> Chatbot:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(chatbot, field, value)
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
