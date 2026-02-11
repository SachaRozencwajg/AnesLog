"""
SQLAlchemy ORM models for AnesLog.

Domain entities:
- User (resident or senior)
- Category (procedure category, e.g. "Cathéters")
- Procedure (specific gesture, e.g. "KTC")
- ProcedureLog (a resident recording they performed a procedure)
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Enum as SAEnum, Boolean
)
from sqlalchemy.orm import relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    """Role of the user in the application."""
    resident = "resident"
    senior = "senior"


class AutonomyLevel(str, enum.Enum):
    """
    Level of autonomy the resident had during the procedure.
    Values are stored in French to match the UI display.
    """
    observed = "J'ai vu"
    assisted = "J'ai fait avec aide"
    capable = "Je sais faire"
    autonomous = "Je suis autonome"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.resident)
    
    # Profile fields (for residents)
    semester = Column(Integer, nullable=True)  # 1-10
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    institution = Column(String(255), nullable=True)
    
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    logs = relationship("ProcedureLog", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.email} ({self.role.value})>"


class Category(Base):
    """
    Procedure category (e.g. "Cathéters", "Voies aériennes").
    To add a new category, insert a row here or add it to seed.py.
    """
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)

    # Relationships
    procedures = relationship("Procedure", back_populates="category", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Category {self.name}>"


class Procedure(Base):
    """
    A specific medical procedure / gesture (e.g. "KTC", "Intubation double lumière").
    To add a new procedure, insert a row here or add it to seed.py.
    """
    __tablename__ = "procedures"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)

    # Relationships
    category = relationship("Category", back_populates="procedures")
    logs = relationship("ProcedureLog", back_populates="procedure", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Procedure {self.name}>"


class ProcedureLog(Base):
    """
    Core transaction: a resident logs that they performed (or observed) a procedure.
    """
    __tablename__ = "procedure_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    procedure_id = Column(Integer, ForeignKey("procedures.id"), nullable=False)
    date = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    autonomy_level = Column(SAEnum(AutonomyLevel), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="logs")
    procedure = relationship("Procedure", back_populates="logs")

    def __repr__(self):
        return f"<Log {self.user_id} – {self.procedure.name} ({self.autonomy_level.value})>"
