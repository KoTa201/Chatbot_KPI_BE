from typing import TYPE_CHECKING
from uuid import uuid4
from sqlalchemy import UUID, String, Text, Enum, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from model.Base import Base
from model.Base import AuthorityEnum  # noqa: F401 — re-exported for backward compat

if TYPE_CHECKING:
    from model.ChatSession import ChatSession


class Chatbot(Base):
    __tablename__ = "chatbots"

    id: Mapped[UUID] = mapped_column(
        UUID, primary_key=True, index=True, default=uuid4)
    chatbot_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True)
    authority: Mapped[AuthorityEnum] = mapped_column(
        Enum(AuthorityEnum, values_callable=lambda e: [x.value for x in e]),
        nullable=False)
    addon_prompt: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="chatbot", lazy="noload"
    )

    def __repr__(self):
        return f"<Chatbot id={self.id} name='{self.chatbot_name}' authority='{self.authority}'>"
