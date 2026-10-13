"""Framework-independent business workflows."""

from app.workflows.general_email import (
    ApprovalOutcome,
    GeneralEmailRequest,
    GeneralEmailSession,
    GeneralEmailWorkflow,
    WorkflowStateError,
)

__all__ = [
    "ApprovalOutcome",
    "GeneralEmailRequest",
    "GeneralEmailSession",
    "GeneralEmailWorkflow",
    "WorkflowStateError",
]

