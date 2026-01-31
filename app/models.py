from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ExamToken(Base):
    __tablename__ = "exam_tokens"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_submitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Nullable until first open; used to reuse the same attempt on refresh
    attempt_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Store token string for easy lookup / display (no ORM relationship needed)
    token: Mapped[str] = mapped_column(String, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    answers = relationship("ExamAnswer", back_populates="attempt", cascade="all, delete-orphan")


class ExamAnswer(Base):
    __tablename__ = "exam_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    attempt_id: Mapped[int] = mapped_column(Integer, ForeignKey("exam_attempts.id"), nullable=False)
    question_id: Mapped[str] = mapped_column(String, nullable=False)

    selected_option: Mapped[str] = mapped_column(String, nullable=False)
    correct_option: Mapped[str] = mapped_column(String, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)

    attempt = relationship("ExamAttempt", back_populates="answers")


Index("ix_exam_attempts_token", ExamAttempt.token)
Index("ix_exam_answers_attempt_id", ExamAnswer.attempt_id)
Index("ix_exam_tokens_is_submitted", ExamToken.is_submitted)
