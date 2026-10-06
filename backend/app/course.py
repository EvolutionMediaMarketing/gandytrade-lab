"""The 12-week course: progress, unlocking and the tasks the app can check for itself.

The lessons and quizzes live in the frontend (`frontend/src/course.ts`); this keeps your progress. Week 1 is
open from the start, and each later week unlocks once the one before is complete: quiz passed (3 of 4) and
task done. Tasks are one of three kinds, matching the frontend:

  * auto: the app checks what you've done (first paper trade, three journal lessons, a backtest, an automatic
    run, a weekly review), and ticks it the first time it sees it;
  * self: you tick it yourself;
  * plan: you write it here (week 12, your trading plan), at least a few sentences.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AutoRun, BacktestRun, CourseProgress, PaperAccount, PaperTrade, User, WeeklyReview

WEEKS = 12
QUIZ_QUESTIONS = 4
PASS_MARK = 3
PLAN_MIN_CHARS = 200

# Each week's task: "auto:<check>", "self" or "plan". Must match the frontend's course.ts.
TASKS = {
    1: "auto:first_trade", 2: "self", 3: "self", 4: "auto:journal3", 5: "self", 6: "auto:backtest",
    7: "self", 8: "self", 9: "auto:auto_run", 10: "auto:weekly_review", 11: "self", 12: "plan",
}


class CourseError(ValueError):
    """A reason a course step can't be saved, in plain words."""


def _accounts(db: Session, user: User) -> list[int]:
    return list(db.scalars(select(PaperAccount.id).where(PaperAccount.user_id == user.id)))


def check(db: Session, user: User, name: str) -> tuple[bool, str]:
    """Whether an automatic task is done, and a short progress note."""
    accts = _accounts(db, user) or [-1]
    if name == "first_trade":
        n = db.scalar(select(func.count()).select_from(PaperTrade).where(
            PaperTrade.account_id.in_(accts), PaperTrade.source == "manual")) or 0
        return n >= 1, f"{n} paper trade{'s' if n != 1 else ''} of your own"
    if name == "journal3":
        n = db.scalar(select(func.count()).select_from(PaperTrade).where(
            PaperTrade.account_id.in_(accts), PaperTrade.source == "manual", PaperTrade.status == "closed",
            PaperTrade.lesson != "")) or 0
        return n >= 3, f"{min(n, 3)} of 3 closed trades with a lesson"
    if name == "backtest":
        n = db.scalar(select(func.count()).select_from(BacktestRun).where(BacktestRun.user_id == user.id)) or 0
        return n >= 1, f"{n} saved backtest{'s' if n != 1 else ''}"
    if name == "auto_run":
        n = db.scalar(select(func.count()).select_from(AutoRun).where(AutoRun.account_id.in_(accts))) or 0
        return n >= 1, f"{n} automatic run{'s' if n != 1 else ''}"
    if name == "weekly_review":
        n = db.scalar(select(func.count()).select_from(WeeklyReview).where(
            WeeklyReview.user_id == user.id, WeeklyReview.completed_at.is_not(None))) or 0
        return n >= 1, f"{n} completed review{'s' if n != 1 else ''}"
    raise CourseError(f"Unknown check: {name}")


def _row(db: Session, user: User, week: int, create: bool = False) -> CourseProgress | None:
    row = db.scalar(select(CourseProgress).where(CourseProgress.user_id == user.id, CourseProgress.week == week))
    if row is None and create:
        row = CourseProgress(user_id=user.id, week=week, started_at=datetime.now(timezone.utc), quiz_score=0, note="")
        db.add(row)
        db.flush()
    return row


def _iso(d: datetime | None) -> str | None:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def progress(db: Session, user: User) -> dict:
    """Every week's state. Auto tasks are checked here and ticked the first time they pass."""
    rows = {r.week: r for r in db.scalars(select(CourseProgress).where(CourseProgress.user_id == user.id))}
    weeks, open_until, changed = [], 1, False
    for w in range(1, WEEKS + 1):
        r = rows.get(w)
        task = TASKS[w]
        detail = ""
        if task.startswith("auto:") and w <= open_until:
            ok, detail = check(db, user, task[5:])
            if ok and (r is None or r.task_done_at is None):
                r = r or _row(db, user, w, create=True)
                r.task_done_at = datetime.now(timezone.utc)
                rows[w], changed = r, True
        quiz_passed = r is not None and r.quiz_passed_at is not None
        task_done = r is not None and r.task_done_at is not None
        complete = quiz_passed and task_done
        unlocked = w <= open_until
        weeks.append({
            "week": w, "unlocked": unlocked, "complete": complete,
            "startedAt": _iso(r.started_at) if r else None,
            "quizScore": r.quiz_score if r else 0, "quizPassed": quiz_passed, "quizPassedAt": _iso(r.quiz_passed_at) if r else None,
            "task": task.split(":")[0], "taskDone": task_done, "taskDoneAt": _iso(r.task_done_at) if r else None,
            "taskDetail": detail, "note": r.note if r else "",
        })
        if complete and w == open_until:
            open_until = w + 1
    if changed:
        db.commit()
    done = sum(1 for w in weeks if w["complete"])
    current = next((w["week"] for w in weeks if w["unlocked"] and not w["complete"]), None)
    return {"weeks": weeks, "completed": done, "current": current, "passMark": PASS_MARK, "questions": QUIZ_QUESTIONS}


def _unlocked(db: Session, user: User, week: int) -> None:
    if not 1 <= week <= WEEKS:
        raise CourseError("There's no such week.")
    state = progress(db, user)["weeks"][week - 1]
    if not state["unlocked"]:
        raise CourseError(f"Week {week} unlocks once week {week - 1} is complete.")


def start(db: Session, user: User, week: int) -> dict:
    _unlocked(db, user, week)
    _row(db, user, week, create=True)
    db.commit()
    return progress(db, user)


def record_quiz(db: Session, user: User, week: int, score: int) -> dict:
    _unlocked(db, user, week)
    if not 0 <= score <= QUIZ_QUESTIONS:
        raise CourseError("That's not a possible score.")
    row = _row(db, user, week, create=True)
    row.quiz_score = max(row.quiz_score, score)
    if score >= PASS_MARK and row.quiz_passed_at is None:
        row.quiz_passed_at = datetime.now(timezone.utc)
    db.commit()
    return progress(db, user)


def record_task(db: Session, user: User, week: int, done: bool, note: str = "") -> dict:
    _unlocked(db, user, week)
    kind = TASKS[week].split(":")[0]
    if kind == "auto":
        raise CourseError("This task is ticked automatically once you've done it in the app.")
    row = _row(db, user, week, create=True)
    if kind == "plan":
        note = note.strip()
        row.note = note[:4000]
        if done and len(note) < PLAN_MIN_CHARS:
            raise CourseError(f"Write a bit more: a plan needs at least {PLAN_MIN_CHARS} characters to cover the basics.")
    row.task_done_at = datetime.now(timezone.utc) if done else None
    db.commit()
    return progress(db, user)
