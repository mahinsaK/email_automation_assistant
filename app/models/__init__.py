"""Domain models."""

from app.models.ai_configuration import (
    AIProviderType,
    ResolvedAIConfiguration,
    StoredAIConfiguration,
)
from app.models.email import EmailDraft, EmailStatus, EmailTone, SendResult
from app.models.job_application import (
    CandidateProfile,
    Certification,
    Education,
    EmailAttachment,
    Experience,
    JobApplicationRequest,
    JobRequirements,
    PreparedEmail,
    Project,
    RequirementMatchResult,
)
from app.models.gmail_connection import (
    GmailConnection,
    GmailConnectionInfo,
    GoogleOAuthGrant,
    ResolvedGmailCredential,
)

__all__ = [
    "AIProviderType",
    "CandidateProfile",
    "Certification",
    "Education",
    "EmailAttachment",
    "EmailDraft",
    "EmailStatus",
    "EmailTone",
    "Experience",
    "GmailConnection",
    "GmailConnectionInfo",
    "GoogleOAuthGrant",
    "JobApplicationRequest",
    "JobRequirements",
    "PreparedEmail",
    "Project",
    "RequirementMatchResult",
    "ResolvedAIConfiguration",
    "ResolvedGmailCredential",
    "SendResult",
    "StoredAIConfiguration",
]

