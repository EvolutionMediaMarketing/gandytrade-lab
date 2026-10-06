import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { COURSE, PASS_MARK, type Week } from "./course";
import type { CourseProgress, CourseWeek } from "./types";

type Go = "charts" | "backtest" | "paper" | "journal" | "review" | "tools";

/** The 12-week course: pick a week, read its lessons, take the quiz, do the task. Weeks unlock in order. */
export default function CourseView({ onGo, onAuthError }: { onGo: (page: Go) => void; onAuthError: (err: unknown) => void }) {
  const [progress, setProgress] = useState<CourseProgress | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.course().then((p) => {
      setProgress(p);
      setSelected((s) => s ?? p.current ?? 12);
    }).catch(onAuthError);
  }, [onAuthError]);
  useEffect(load, [load]);

  const save = useCallback((p: Promise<CourseProgress>) => {
    setError(null);
    p.then(setProgress).catch((err) => { onAuthError(err); setError(err instanceof Error ? err.message : "That didn't save."); });
  }, [onAuthError]);

  if (!progress) return <p className="muted">Loading the course…</p>;
  const week = COURSE.find((w) => w.week === selected) ?? COURSE[0];
  const state = progress.weeks[week.week - 1];

  return (
    <div className="course">
      <div className="course-progress">
        <p className="muted small-text">
          {progress.completed === 12 ? "Course complete. Well done: now the plan meets the market."
            : `${progress.completed} of 12 weeks complete. Each week unlocks when the one before is done: pass the quiz (${PASS_MARK} of 4) and do the task.`}
          {" "}A week's work takes about an hour; there's no rush to finish one a week.
        </p>
        <ol className="week-strip" aria-label="Weeks">
          {progress.weeks.map((w) => (
            <li key={w.week}>
              <button type="button" disabled={!w.unlocked}
                className={`week-chip ${w.complete ? "done" : ""} ${w.week === week.week ? "on" : ""} ${!w.unlocked ? "locked" : ""}`}
                title={`${COURSE[w.week - 1].title}${!w.unlocked ? " (locked)" : w.complete ? " (complete)" : ""}`}
                aria-current={w.week === week.week ? "step" : undefined}
                onClick={() => setSelected(w.week)}>
                <span className="week-num">{w.complete ? "✓" : w.unlocked ? w.week : "🔒"}</span>
                <span className="week-name">{COURSE[w.week - 1].title}</span>
              </button>
            </li>
          ))}
        </ol>
      </div>

      {error && <p className="warn stop">{error}</p>}
      <WeekView key={week.week} week={week} state={state} onGo={onGo}
        onStart={() => { if (!state.startedAt) save(api.courseStart(week.week)); }}
        onQuiz={(score) => save(api.courseQuiz(week.week, score))}
        onTask={(done, note) => save(api.courseTask(week.week, done, note))}
        onNext={progress.weeks[week.week]?.unlocked ? () => setSelected(week.week + 1) : undefined} />
    </div>
  );
}

function WeekView({ week, state, onGo, onStart, onQuiz, onTask, onNext }: {
  week: Week; state: CourseWeek; onGo: (page: Go) => void; onStart: () => void;
  onQuiz: (score: number) => void; onTask: (done: boolean, note?: string) => void; onNext?: () => void;
}) {
  useEffect(onStart, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <article className="card week">
      <header>
        <span className="muted small-text">Week {week.week} of 12{state.complete ? " · complete" : ""}</span>
        <h2>{week.title}</h2>
        <p className="week-goal">{week.goal}</p>
      </header>

      {week.lessons.map((l, i) => (
        <section key={i} className="lesson">
          <h3><span className="lesson-num">{i + 1}</span>{l.title}</h3>
          {l.body.map((p, j) => <p key={j}>{p}</p>)}
        </section>
      ))}

      <Quiz week={week} best={state.quizScore} passed={state.quizPassed} onSubmit={onQuiz} />
      <TaskBox week={week} state={state} onGo={onGo} onTask={onTask} />

      {state.complete && (
        <div className="week-done">
          <b>Week {week.week} complete.</b>{" "}
          {onNext ? <button type="button" className="primary small" onClick={onNext}>On to week {week.week + 1}</button>
            : week.week === 12 ? "That's the course. Re-read your plan before every trading session." : null}
        </div>
      )}
    </article>
  );
}

function Quiz({ week, best, passed, onSubmit }: { week: Week; best: number; passed: boolean; onSubmit: (score: number) => void }) {
  const [answers, setAnswers] = useState<(number | null)[]>(() => week.quiz.map(() => null));
  const [marked, setMarked] = useState(false);
  // Shuffle each question's options once, so the right answer isn't always in the same place.
  const orders = useMemo(() => week.quiz.map((q) => shuffle(q.options.map((_, i) => i), week.week * 31 + q.q.length)), [week]);
  const score = answers.filter((a, i) => a === week.quiz[i].answer).length;
  const all = answers.every((a) => a !== null);

  return (
    <section className="quiz">
      <h3>Quiz <span className="muted small-text">— {PASS_MARK} of {week.quiz.length} to pass{best ? ` · best so far ${best}/${week.quiz.length}` : ""}{passed ? " ✓" : ""}</span></h3>
      <ol>
        {week.quiz.map((q, i) => (
          <li key={i} className="quiz-q">
            <p>{q.q}</p>
            <div className="quiz-options" role="radiogroup" aria-label={`Question ${i + 1}`}>
              {orders[i].map((oi) => {
                const chosen = answers[i] === oi;
                const state = marked ? (oi === q.answer ? "right" : chosen ? "wrong" : "") : chosen ? "chosen" : "";
                return (
                  <label key={oi} className={`quiz-option ${state}`}>
                    <input type="radio" name={`w${week.week}q${i}`} checked={chosen} disabled={marked}
                      onChange={() => setAnswers((a) => a.map((x, k) => (k === i ? oi : x)))} />
                    {q.options[oi]}
                  </label>
                );
              })}
            </div>
            {marked && <p className={`quiz-why ${answers[i] === q.answer ? "up" : "down"}`}>{answers[i] === q.answer ? "Right. " : "Not quite. "}<span>{q.why}</span></p>}
          </li>
        ))}
      </ol>
      {!marked ? (
        <button type="button" className="primary" disabled={!all} onClick={() => { setMarked(true); onSubmit(score); }}>
          {all ? "Check my answers" : "Answer every question"}
        </button>
      ) : (
        <div className="quiz-result">
          <b className={score >= PASS_MARK ? "up" : "down"}>{score} of {week.quiz.length}</b>
          {score >= PASS_MARK ? " — passed." : ` — ${PASS_MARK} needed. Re-read the lessons above and try again.`}
          {" "}<button type="button" className="ghost small" onClick={() => { setAnswers(week.quiz.map(() => null)); setMarked(false); }}>Try again</button>
        </div>
      )}
    </section>
  );
}

function TaskBox({ week, state, onGo, onTask }: { week: Week; state: CourseWeek; onGo: (page: Go) => void; onTask: (done: boolean, note?: string) => void }) {
  const t = week.task;
  const [note, setNote] = useState(state.note);
  const [saved, setSaved] = useState(false);
  return (
    <section className={`task ${state.taskDone ? "done" : ""}`}>
      <h3>This week's task {state.taskDone && <span className="up">✓ done</span>}</h3>
      <p>{t.text}</p>
      {t.kind === "auto" && (
        <p className="muted small-text">The app ticks this off when it sees you've done it{state.taskDetail ? ` (so far: ${state.taskDetail})` : ""}.</p>
      )}
      {t.kind === "plan" && (
        <>
          <textarea rows={9} maxLength={4000} value={note} onChange={(e) => { setNote(e.target.value); setSaved(false); }}
            placeholder={"Markets:\nStrategy and settings:\nTimeframe:\nRisk per trade:\nMost at risk at once:\nI pause when:\nMy review routine:"} />
          <p className="muted small-text">{note.trim().length} characters{note.trim().length < 200 ? " (at least 200 to complete the task)" : ""}. Saved with your progress; you can change it at any review.</p>
        </>
      )}
      <div className="planner-actions">
        {t.go && <button type="button" className="ghost small" onClick={() => onGo(t.go!.page)}>{t.go.label}</button>}
        {t.kind === "self" && (
          <label className="check-row">
            <input type="checkbox" checked={state.taskDone} onChange={(e) => onTask(e.target.checked)} /> I've done it
          </label>
        )}
        {t.kind === "plan" && (
          <>
            <button type="button" className="ghost small" onClick={() => { onTask(state.taskDone, note); setSaved(true); }}>Save draft</button>
            <button type="button" className="primary small" disabled={note.trim().length < 200}
              onClick={() => { onTask(true, note); setSaved(true); }}>{state.taskDone ? "Save plan" : "Save and mark done"}</button>
            {saved && <span className="muted small-text">Saved.</span>}
          </>
        )}
      </div>
    </section>
  );
}

/** A repeatable shuffle (same order every visit), so options don't jump around between attempts. */
function shuffle(xs: number[], seed: number): number[] {
  const out = [...xs];
  let s = seed || 1;
  for (let i = out.length - 1; i > 0; i--) {
    s = (s * 9301 + 49297) % 233280;
    const j = Math.floor((s / 233280) * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}
