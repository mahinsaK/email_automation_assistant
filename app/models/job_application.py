"""Provider- and Telegram-independent job application domain values."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.email import EmailDraft


@dataclass(frozen=True, slots=True)
class JobApplicationRequest:
    """Validated company and role information supplied by the user."""

    company_email: str
    company_name: str
    role: str
    job_description: str


@dataclass(frozen=True, slots=True)
class Education:
    degree: str
    institution: str
    graduation_year: int | None = None


@dataclass(frozen=True, slots=True)
class Project:
    name: str
    description: str | None = None
    technologies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Experience:
    title: str
    organization: str
    description: str | None = None
    skills: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Certification:
    name: str
    issuer: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateProfile:
    """The sole source of candidate facts available to application generation."""

    name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None
    education: tuple[Education, ...] = ()
    skills: tuple[str, ...] = ()
    projects: tuple[Project, ...] = ()
    experience: tuple[Experience, ...] = ()
    certifications: tuple[Certification, ...] = ()
    achievements: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JobRequirements:
    required_skills: tuple[str, ...] = ()
    preferred_skills: tuple[str, ...] = ()
    responsibilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RequirementMatchResult:
    matched_skills: tuple[str, ...] = ()
    unmatched_skills: tuple[str, ...] = ()
    relevant_projects: tuple[Project, ...] = ()


@dataclass(frozen=True, slots=True)
class EmailAttachment:
    """Validated attachment metadata; file content is not loaded in Phase 4."""

    file_path: str
    file_name: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PreparedEmail:
    """A draft bundled with typed attachment metadata for future delivery."""

    draft: EmailDraft
    attachments: tuple[EmailAttachment, ...] = ()
