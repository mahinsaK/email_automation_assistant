"""Tests for Python-version-compatible application startup."""

import asyncio

from main import run_application


class FakeApplication:
    def __init__(self) -> None:
        self.current_loop_seen = False
        self.arguments: dict[str, object] = {}

    def run_polling(self, **kwargs: object) -> None:
        self.current_loop_seen = asyncio.get_event_loop() is not None
        self.arguments = kwargs


def test_run_application_provides_current_loop_for_polling() -> None:
    application = FakeApplication()

    run_application(application)  # type: ignore[arg-type]

    assert application.current_loop_seen is True
    assert application.arguments == {
        "allowed_updates": None,
        "close_loop": False,
    }
