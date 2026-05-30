import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base

if TYPE_CHECKING:
    from model.ChatMessage import ChatMessage


class ChatMessageGraphic(Base):
    __tablename__ = "chat_message_graphics"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("chat_messages.message_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kpi_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chart_type: Mapped[str] = mapped_column(String(50), nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    message: Mapped["ChatMessage"] = relationship(
        "ChatMessage", back_populates="graphics", lazy="noload"
    )
