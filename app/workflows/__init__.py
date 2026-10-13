"""Framework-independent business workflows."""

from app.workflows.general_email import (
    AIUnavailableError,
    ApprovalOutcome,
    DraftMode,
    GeneralEmailRequest,
    GeneralEmailSession,
    GeneralEmailWorkflow,
    WorkflowStateError,
)
from app.workflows.job_application import (
    JobApplicationApprovalOutcome,
    JobApplicationResources,
    JobApplicationSession,
    JobApplicationWorkflow,
)

__all__ = [
    "ApprovalOutcome",
    "AIUnavailableError",
    "DraftMode",
    "GeneralEmailRequest",
    "GeneralEmailSession",
    "GeneralEmailWorkflow",
    "JobApplicationApprovalOutcome",
    "JobApplicationResources",
    "JobApplicationSession",
    "JobApplicationWorkflow",
    "WorkflowStateError",
]

