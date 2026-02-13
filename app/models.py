"""
SQLAlchemy ORM models for AnesLog.

Domain entities:
- User (resident or senior)
- Category (procedure category, e.g. "Cathéters")
- Procedure (specific gesture, e.g. "KTC")
- ProcedureLog (a resident recording they performed a procedure)
- CompetencyDomain (DESAR national domains A-G + CoBaTrICE)
- Competency (loggable sub-competency within a domain)
- Semester (DESAR S1-S10 tracking per resident)
- GuardLog (guard shift tracking)
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Enum as SAEnum, Boolean, Date
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


class DesarPhase(str, enum.Enum):
    """The 3 phases of DESAR training (Journal Officiel, 28 avril 2017)."""
    socle = "socle"                            # S1-S2
    approfondissement = "approfondissement"      # S3-S8
    consolidation = "consolidation"              # S9-S10


class GuardType(str, enum.Enum):
    """Type of guard shift."""
    garde_24h = "Garde 24h"
    astreinte = "Astreinte"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# DESAR Competency Models
# ---------------------------------------------------------------------------

class CompetencyDomain(Base):
    """
    National DESAR competency domain (A-G for anesthesia, CoBaTrICE for ICU).
    Pre-seeded from the Journal Officiel.
    """
    __tablename__ = "competency_domains"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, nullable=False)        # "A", "B", ..., "G", "COBA"
    name = Column(String(255), nullable=False)                    # "Évaluation pré-opératoire"
    description = Column(Text, nullable=True)
    phase_required = Column(SAEnum(DesarPhase), nullable=True)    # When this domain starts being evaluated
    display_order = Column(Integer, default=0)

    # Relationships
    competencies = relationship("Competency", back_populates="domain", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<CompetencyDomain {self.code}: {self.name}>"


class Competency(Base):
    """
    A specific loggable competency within a domain (e.g. "Intubation" in domain B).
    ~30 competencies total, extracted from the Journal Officiel.
    """
    __tablename__ = "competencies"

    id = Column(Integer, primary_key=True, index=True)
    domain_id = Column(Integer, ForeignKey("competency_domains.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    phase_required = Column(SAEnum(DesarPhase), nullable=True)    # Override domain phase if needed
    display_order = Column(Integer, default=0)

    # Relationships
    domain = relationship("CompetencyDomain", back_populates="competencies")

    def __repr__(self):
        return f"<Competency {self.domain.code}.{self.name}>"


# ---------------------------------------------------------------------------
# Core Models
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
    semester = Column(Integer, nullable=True)  # 1-10 (current semester number)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    institution = Column(String(255), nullable=True)
    desar_start_date = Column(Date, nullable=True)  # When the resident started DESAR
    
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    logs = relationship("ProcedureLog", back_populates="user", cascade="all, delete-orphan")
    semesters = relationship("Semester", back_populates="user", cascade="all, delete-orphan")
    guard_logs = relationship("GuardLog", back_populates="user", cascade="all, delete-orphan")

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

    # DESAR competency domain tagging (optional — set by senior)
    competency_id = Column(Integer, ForeignKey("competencies.id"), nullable=True)
    competency = relationship("Competency")

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
    surgery_type = Column(String(100), nullable=True)  # Type of surgery (maps to F.a-F.j)
    semester_id = Column(Integer, ForeignKey("semesters.id"), nullable=True)  # Which semester this log belongs to
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="logs")
    procedure = relationship("Procedure", back_populates="logs")
    semester = relationship("Semester")

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

    Lifecycle:
      1. Resident logs "Je suis autonome" ≥ MASTERY_THRESHOLD times → is_mastered=True
      2. Senior validates → senior_validated=True (procedure is now "locked")
      3. Locked procedures auto-set autonomy in the logging form.
    """
    __tablename__ = "procedure_competences"

    MASTERY_THRESHOLD = 3  # Number of autonomous logs needed to declare mastery

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    procedure_id = Column(Integer, ForeignKey("procedures.id"), nullable=False)
    is_mastered = Column(Boolean, default=False, nullable=False)
    mastered_at_log_count = Column(Integer, nullable=True)  # How many logs before mastery
    mastered_date = Column(DateTime, nullable=True)
    is_pre_acquired = Column(Boolean, default=False)  # Senior manually marked as pre-acquired
    senior_validated = Column(Boolean, default=False, nullable=False)
    senior_validated_date = Column(DateTime, nullable=True)
    senior_validated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    procedure = relationship("Procedure")
    validator = relationship("User", foreign_keys=[senior_validated_by])


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


# ---------------------------------------------------------------------------
# DESAR Tracking Models
# ---------------------------------------------------------------------------

class Semester(Base):
    """
    Tracks a resident's semester (S1-S10) in the DESAR program.
    All 10 blocks are pre-created; the resident fills in dates and details.
    End date = start_date + 6 months (auto-calculated).
    """
    __tablename__ = "semesters"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    number = Column(Integer, nullable=False)  # 1-10
    phase = Column(SAEnum(DesarPhase), nullable=False)
    start_date = Column(Date, nullable=True)  # Null = not yet configured
    end_date = Column(Date, nullable=True)  # Auto = start_date + 6 months
    subdivision = Column(String(100), nullable=True)  # Région / subdivision (ex: Île-de-France)
    hospital = Column(String(255), nullable=True)  # Établissement
    service = Column(String(255), nullable=True)  # Service / département
    chef_de_service = Column(String(255), nullable=True)  # Chef(fe) de service
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)  # Team during this semester
    is_current = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="semesters")
    team = relationship("Team")

    @staticmethod
    def phase_for_semester(number: int) -> DesarPhase:
        """Return the DESAR phase for a given semester number."""
        if number <= 2:
            return DesarPhase.socle
        elif number <= 8:
            return DesarPhase.approfondissement
        else:
            return DesarPhase.consolidation

    def __repr__(self):
        return f"<Semester S{self.number} ({self.phase.value}) – User {self.user_id}>"


class GuardLog(Base):
    """
    Simple guard shift tracker. One row per guard.
    """
    __tablename__ = "guard_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    guard_type = Column(SAEnum(GuardType), nullable=False, default=GuardType.garde_24h)
    semester_id = Column(Integer, ForeignKey("semesters.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="guard_logs")
    semester = relationship("Semester")

    def __repr__(self):
        return f"<GuardLog {self.date} – User {self.user_id}>"
