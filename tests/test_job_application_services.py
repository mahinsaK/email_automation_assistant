"""Unit tests for Phase 4 profile, CV, matching, and grounded generation."""

import asyncio
import json
from pathlib import Path

import pytest

from app.models.email import EmailTone
from app.models.job_application import (
    CandidateProfile,
    JobApplicationRequest,
    Project,
)
from app.services.attachment import AttachmentValidationError, CVAttachmentService
from app.services.candidate_profile import CandidateProfileError, CandidateProfileService
from app.services.job_application_generator import (
    AIJobApplicationGenerator,
    DeterministicJobApplicationGenerator,
)
from app.services.job_requirements import (
    CandidateRequirementMatcher,
    DeterministicJobRequirementExtractor,
)


class UnsupportedSkillProvider:
    async def generate(self, **kwargs: object) -> str:
        return json.dumps(
            {
                "subject": "AWS engineering application",
                "body": "I have extensive AWS and Docker expertise.",
            }
        )


def write_profile(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "name": "Alex Candidate",
                "email": "alex@example.com",
                "education": [
                    {"degree": "BSc Computing", "institution": "Example University"}
                ],
                "skills": ["Python", "SQL", "React"],
                "projects": [
                    {
                        "name": "Reporting Portal",
                        "description": "A reporting application.",
                        "technologies": ["Python", "SQL"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_profile_service_loads_valid_profile_and_rejects_missing_file(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "candidate.json"
    write_profile(profile_path)

    profile = asyncio.run(CandidateProfileService(profile_path).get_profile())

    assert profile.name == "Alex Candidate"
    assert profile.skills == ("Python", "SQL", "React")
    with pytest.raises(CandidateProfileError):
        asyncio.run(CandidateProfileService(tmp_path / "missing.json").get_profile())


def test_profile_service_rejects_invalid_json(tmp_path: Path) -> None:
    profile_path = tmp_path / "candidate.json"
    profile_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(CandidateProfileError):
        asyncio.run(CandidateProfileService(profile_path).get_profile())


def test_cv_attachment_service_validates_file_and_metadata(tmp_path: Path) -> None:
    cv_path = tmp_path / "Candidate CV.pdf"
    cv_path.write_bytes(b"%PDF-1.4 test")

    attachment = asyncio.run(CVAttachmentService(cv_path).prepare())

    assert attachment.file_name == "Candidate CV.pdf"
    assert attachment.mime_type == "application/pdf"
    assert attachment.size_bytes > 0
    assert Path(attachment.file_path).is_absolute()


@pytest.mark.parametrize(
    "name,content",
    [("missing.pdf", None), ("empty.pdf", b""), ("cv.txt", b"cv")],
)
def test_cv_attachment_service_rejects_unsafe_inputs(
    tmp_path: Path,
    name: str,
    content: bytes | None,
) -> None:
    cv_path = tmp_path / name
    if content is not None:
        cv_path.write_bytes(content)

    with pytest.raises(AttachmentValidationError):
        asyncio.run(CVAttachmentService(cv_path).prepare())


def test_requirement_matching_uses_only_explicit_candidate_facts() -> None:
    profile = CandidateProfile(
        name="Alex Candidate",
        skills=("SQL", "React"),
        projects=(Project(name="Portal", technologies=("React",)),),
    )
    requirements = DeterministicJobRequirementExtractor().extract(
        "Required: PyTorch, AWS, Docker, and SQL. React is preferred."
    )

    result = CandidateRequirementMatcher().match(profile, requirements)

    assert result.matched_skills == ("SQL", "React")
    assert result.unmatched_skills == ("AWS", "Docker", "PyTorch")
    assert tuple(project.name for project in result.relevant_projects) == ("Portal",)


def test_ai_output_claiming_unmatched_skill_uses_truthful_fallback() -> None:
    profile = CandidateProfile(name="Alex Candidate", skills=("SQL",))
    request = JobApplicationRequest(
        company_email="jobs@example.com",
        company_name="Example Co",
        role="Software Engineer",
        job_description="SQL required. AWS and Docker required.",
    )
    extractor = DeterministicJobRequirementExtractor()
    requirements = extractor.extract(request.job_description)
    match = CandidateRequirementMatcher().match(profile, requirements)
    generator = AIJobApplicationGenerator(
        provider=UnsupportedSkillProvider(),  # type: ignore[arg-type]
        fallback=DeterministicJobApplicationGenerator(),
    )

    draft = asyncio.run(
        generator.generate(
            request=request,
            profile=profile,
            requirements=requirements,
            match_result=match,
            tone=EmailTone.PROFESSIONAL,
        )
    )

    assert "SQL" in draft.body
    assert "AWS" not in draft.body
    assert "Docker" not in draft.body

