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


class InvitationStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    expired = "expired"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Team(Base):
    """
    Medical team (e.g. "Marie Lannelongue - Anesthésie").
    """
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    users = relationship("User", back_populates="team")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.resident)
    
    # Team Relationship
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    is_approved = Column(Boolean, default=False) # True if request accepted by senior
    team = relationship("Team", back_populates="users")

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
    name = Column(String(255), unique=False, nullable=False) # Unique constraint removed (handled by logic/composite)
    
    # Team specificity (Null = Global)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    team = relationship("Team")

    # Section grouping for UI (intervention, gesture, complication)
    # Default is "intervention" for backwards compatibility
    section = Column(String(50), default="intervention", nullable=False)

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

    # Team specificity (Null = Global, or inherits from Category)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    team = relationship("Team")

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
    autonomy_level = Column(SAEnum(AutonomyLevel), nullable=True)  # Nullable: not asked when mastered
    case_id = Column(String(36), nullable=True, index=True) # Grouping ID for multi-procedure cases
    notes = Column(Text, nullable=True)
    is_success = Column(Boolean, nullable=True)  # Senior-validated objective success
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="logs")
    procedure = relationship("Procedure", back_populates="logs")

    def __repr__(self):
        return f"<Log {self.user_id} – {self.procedure.name}>"


class Invitation(Base):
    """
    Tracks pending email invitations to join a team.
    """
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    status = Column(SAEnum(InvitationStatus), default=InvitationStatus.pending)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    team = relationship("Team")

    def __repr__(self):
        return f"<Invitation {self.email} -> {self.team_id} ({self.status.value})>"


class ProcedureCompetence(Base):
    """
    Tracks mastery status for a (user, procedure) pair.
    When a resident declares autonomy for a procedure, this record is created.
    """
    __tablename__ = "procedure_competences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    procedure_id = Column(Integer, ForeignKey("procedures.id"), nullable=False)
    is_mastered = Column(Boolean, default=False, nullable=False)
    mastered_at_log_count = Column(Integer, nullable=True)  # How many logs before mastery
    mastered_date = Column(DateTime, nullable=True)
    is_pre_acquired = Column(Boolean, default=False)  # Senior manually marked as pre-acquired
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User")
    procedure = relationship("Procedure")


class TeamProcedureThreshold(Base):
    """
    Configurable competence threshold per procedure per team.
    The senior defines the expected number of procedures before autonomy.
    """
    __tablename__ = "team_procedure_thresholds"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    procedure_id = Column(Integer, ForeignKey("procedures.id"), nullable=False)
    min_procedures = Column(Integer, nullable=False, default=5)
    max_procedures = Column(Integer, nullable=False, default=15)

    # Relationships
    team = relationship("Team")
    procedure = relationship("Procedure")
