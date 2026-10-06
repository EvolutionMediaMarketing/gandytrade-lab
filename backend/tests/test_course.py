"""12-week course: unlocking in order, quizzes, the three kinds of task, and the frontend's content matching."""

import re
from pathlib import Path

from app import course
from tests.test_paper import FakeMarket, accounts, order  # noqa: F401

import pytest

from app.paper import service as paper


@pytest.fixture()
def market(monkeypatch):
    m = FakeMarket()
    monkeypatch.setattr(paper, "latest_quote", m.quote)
    return m


def weeks(client):
    return client.get("/api/course").json()["weeks"]


def test_only_week_one_is_open_at_first(signed_in):
    w = weeks(signed_in)
    assert len(w) == 12 and w[0]["unlocked"] and not any(x["unlocked"] for x in w[1:])
    r = signed_in.post("/api/course/2/quiz", json={"score": 4})
    assert r.status_code == 400 and "unlocks once week 1" in r.json()["detail"]


def test_week_one_needs_the_quiz_and_a_real_trade(signed_in, market):
    r = signed_in.post("/api/course/1/quiz", json={"score": 2})
    assert r.json()["weeks"][0]["quizPassed"] is False
    r = signed_in.post("/api/course/1/quiz", json={"score": 3})
    w1 = r.json()["weeks"][0]
    assert w1["quizPassed"] and w1["quizScore"] == 3 and not w1["taskDone"] and not w1["complete"]
    # The trade task can't be ticked by hand: the app checks it.
    assert "ticked automatically" in signed_in.post("/api/course/1/task", json={"done": True}).json()["detail"]
    order(signed_in, accounts(signed_in)["cfd"]["id"])
    w = weeks(signed_in)
    assert w[0]["taskDone"] and w[0]["complete"] and w[1]["unlocked"] and not w[2]["unlocked"]
    # A worse later attempt never lowers the best score.
    assert signed_in.post("/api/course/1/quiz", json={"score": 1}).json()["weeks"][0]["quizScore"] == 3


def test_self_ticked_task_and_the_written_plan(signed_in, monkeypatch):
    from app.db import new_session
    from app.models import User

    monkeypatch.setattr(course, "TASKS", {w: "self" for w in range(1, 12)} | {12: "plan"})
    for w in range(1, 12):
        signed_in.post(f"/api/course/{w}/quiz", json={"score": 4})
        assert signed_in.post(f"/api/course/{w}/task", json={"done": True}).status_code == 200
    w = weeks(signed_in)
    assert w[11]["unlocked"] and sum(x["complete"] for x in w) == 11
    short = signed_in.post("/api/course/12/task", json={"done": True, "note": "Buy low, sell high."})
    assert short.status_code == 400 and "at least 200" in short.json()["detail"]
    plan = "Markets: gold, silver, Brent, corn, Nasdaq 100, Japan 225. Strategy: Breakout 55/20 on daily candles, buys only. " \
           "Risk 1% a trade, 10% at most at once. Pause at a 20% fall and review. Weekly review every Sunday evening; " \
           "no changes to settings except at the review."
    signed_in.post("/api/course/12/quiz", json={"score": 3})
    r = signed_in.post("/api/course/12/task", json={"done": True, "note": plan}).json()
    assert r["completed"] == 12 and r["current"] is None and r["weeks"][11]["note"] == plan
    # Unticking a self task re-locks nothing earlier but marks that week incomplete.
    r = signed_in.post("/api/course/12/task", json={"done": False, "note": plan}).json()
    assert r["completed"] == 11
    db = new_session()
    assert db.query(User).count() == 1
    db.close()


def test_frontend_course_matches_the_backend():
    src = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "course.ts").read_text()
    weeks_found = [int(n) for n in re.findall(r"^\s{4}week: (\d+),", src, re.M)]
    assert weeks_found == list(range(1, course.WEEKS + 1))
    kinds = re.findall(r'task: \{ kind: "(\w+)"', src)
    assert kinds == [course.TASKS[w].split(":")[0] for w in range(1, course.WEEKS + 1)]
    # Every quiz has exactly four questions, each with its answer among the options.
    blocks = re.findall(r"quiz: \[(.*?)\n    \],", src, re.S)
    assert len(blocks) == course.WEEKS
    for b in blocks:
        assert b.count("{ q:") == course.QUIZ_QUESTIONS
        for opts, ans in re.findall(r"options: \[(.*?)\], answer: (\d+)", b):
            assert int(ans) < len(re.findall(r'"(?:[^"\\]|\\.)*"', opts))
