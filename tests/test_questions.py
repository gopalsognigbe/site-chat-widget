"""End-to-end questions against the running API (uvicorn on port 8000).

    uvicorn app.main:app --port 8000      # with the site indexed
    pytest -v tests/test_questions.py
"""

import time

import httpx
import pytest

from tests.questions import CASES, PAUSE_SECONDS, REQUEST_TIMEOUT_SECONDS, api_is_up, ask

pytestmark = pytest.mark.skipif(not api_is_up(), reason="API not running on http://localhost:8000")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as c:
        yield c


@pytest.fixture(autouse=True)
def pause_between_calls():
    yield
    time.sleep(PAUSE_SECONDS)


@pytest.mark.parametrize("case", CASES, ids=[c.question for c in CASES])
def test_question(case, client):
    result = ask(case, client)
    assert result.passed, f"{case.question!r}: {'; '.join(result.failures)}\nanswer: {result.answer}\nsources: {result.sources}"
