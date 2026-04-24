from uuid import uuid4
from sqlalchemy import UUID, String, Text, Enum, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from model.Base import Base
from model.Base import AuthorityEnum  # noqa: F401 — re-exported for backward compat


class Chatbot(Base):
    __tablename__ = "chatbots"

    id: Mapped[UUID] = mapped_column(
        UUID, primary_key=True, index=True, default=uuid4)
    nama_chatbot: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True)
    otoritas: Mapped[AuthorityEnum] = mapped_column(
        Enum(AuthorityEnum), nullable=False)
    addon_prompt: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Chatbot id={self.id} nama='{self.nama_chatbot}' otoritas='{self.otoritas}'>"
