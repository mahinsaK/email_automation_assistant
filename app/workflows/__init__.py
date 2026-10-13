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

__all__ = [
    "ApprovalOutcome",
    "AIUnavailableError",
    "DraftMode",
    "GeneralEmailRequest",
    "GeneralEmailSession",
    "GeneralEmailWorkflow",
    "WorkflowStateError",
]

