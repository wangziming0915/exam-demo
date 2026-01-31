from datetime import datetime, timedelta
import json
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db import get_db, init_db
from app.models import ExamToken, ExamAttempt, ExamAnswer
from app.services.grading_service import get_exam_public_view, grade_submission

ADMIN_KEY = "demo-admin-key"

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")


@app.get("/")
def root_redirect():
    return RedirectResponse(url="/payment-success")


@app.on_event("startup")
def on_startup():
    # initialize database and preload questions into the grading service cache
    init_db()
    get_exam_public_view()


def _require_admin(request: Request) -> None:
    header_key = request.headers.get("X-Admin-Key")
    query_key = request.query_params.get("admin_key")
    if header_key == ADMIN_KEY or query_key == ADMIN_KEY:
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/payment-success")
def payment_success(request: Request):
    return templates.TemplateResponse("payment_success.html", {"request": request, "exam_link": None})


@app.post("/payment-success/generate")
def payment_generate(request: Request, db: Session = Depends(get_db)):
    # Simulate payment success, create one-time token
    token_val = uuid.uuid4().hex
    now = datetime.utcnow()
    expires_at = now + timedelta(hours=1)

    token_obj = ExamToken(
        token=token_val,
        created_at=now,
        expires_at=expires_at,
        is_submitted=False,
        attempt_id=None,
    )
    db.add(token_obj)
    db.commit()

    try:
        link = request.url_for("take_exam", token=token_val)
    except Exception:
        link = f"/take-exam/{token_val}"

    return templates.TemplateResponse("payment_success.html", {"request": request, "exam_link": link})


@app.get("/take-exam/{token}", name="take_exam")
def take_exam(token: str, request: Request, db: Session = Depends(get_db)):
    # Validate token
    token_obj = db.query(ExamToken).filter(ExamToken.token == token).first()
    now = datetime.utcnow()
    if not token_obj:
        return templates.TemplateResponse(
            "take_exam.html",
            {"request": request, "error": "Invalid token", "questions": [], "token": token},
        )
    if token_obj.is_submitted:
        return templates.TemplateResponse(
            "take_exam.html",
            {"request": request, "error": "This exam has already been submitted.", "questions": [], "token": token},
        )
    if token_obj.expires_at and token_obj.expires_at < now:
        return templates.TemplateResponse(
            "take_exam.html",
            {"request": request, "error": "This token has expired.", "questions": [], "token": token},
        )

    # Create attempt if not present
    attempt = None
    if token_obj.attempt_id:
        attempt = db.query(ExamAttempt).filter(ExamAttempt.id == token_obj.attempt_id).first()

    if not attempt:
        public = get_exam_public_view()
        total = len(public.get("questions", []))
        attempt = ExamAttempt(
            token=token_obj.token,
            started_at=now,
            submitted_at=None,
            score=0,
            total=total,
            passed=False,
        )
        db.add(attempt)
        db.flush()
        token_obj.attempt_id = attempt.id
        db.commit()

    public = get_exam_public_view()
    return templates.TemplateResponse(
        "take_exam.html", {"request": request, "questions": public.get("questions", []), "token": token}
    )


@app.post("/take-exam/{token}/submit")
async def submit_exam(token: str, request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    submitted: Dict[str, str] = {}
    for key, val in form.items():
        if key.startswith("answer_"):
            qid = key[len("answer_"):]
            submitted[str(qid)] = str(val).strip().upper()

    result = grade_submission(submitted)
    score = result["score"]
    total = result["total"]
    passed = result["passed"]
    wrong_questions = result["wrong_questions"]

    now = datetime.utcnow()

    try:
        with db.begin():
            token_obj = db.query(ExamToken).filter(ExamToken.token == token).first()

            if not token_obj:
                return templates.TemplateResponse(
                    "take_exam.html",
                    {"request": request, "error": "Invalid token", "questions": [], "token": token},
                )

            if token_obj.is_submitted:
                return templates.TemplateResponse(
                    "take_exam.html",
                    {"request": request, "error": "This exam has already been submitted.", "questions": [], "token": token},
                )

            if token_obj.expires_at and token_obj.expires_at < now:
                return templates.TemplateResponse(
                    "take_exam.html",
                    {"request": request, "error": "This token has expired.", "questions": [], "token": token},
                )

            attempt = None
            if token_obj.attempt_id:
                attempt = db.query(ExamAttempt).filter(ExamAttempt.id == token_obj.attempt_id).first()

            if not attempt:
                attempt = ExamAttempt(
                    token=token_obj.token,
                    started_at=now,
                    submitted_at=None,
                    score=0,
                    total=total,
                    passed=False,
                )
                db.add(attempt)
                db.flush()
                token_obj.attempt_id = attempt.id

            attempt.submitted_at = now
            attempt.score = score
            attempt.total = total
            attempt.passed = passed

            from app.services.grading_service import get_full_questions_map
            full_questions = get_full_questions_map()

            for qid, sel in submitted.items():
                q = full_questions.get(str(qid), {})
                correct = str(q.get("correct_option", "")).strip().upper()
                is_correct = (sel == correct)

                db.add(
                    ExamAnswer(
                        attempt_id=attempt.id,
                        question_id=str(qid),
                        selected_option=sel or "(blank)",
                        correct_option=correct,
                        is_correct=is_correct,
                    )
                )

            token_obj.is_submitted = True

        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "score": score,
                "total": total,
                "passed": passed,
                "wrong_questions": wrong_questions,
            },
        )

    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass

        return templates.TemplateResponse(
            "take_exam.html",
            {
                "request": request,
                "error": f"Failed to submit exam: {exc}",
                "questions": [],
                "token": token,
            },
        )


    except Exception as exc:
        # Ensure DB session is clean; rollback handled by context manager but be explicit
        try:
            db.rollback()
        except Exception:
            pass
        return templates.TemplateResponse(
            "take_exam.html", {"request": request, "error": f"Failed to submit exam: {exc}", "questions": [], "token": token}
        )


@app.get("/admin/attempts")
def admin_attempts(request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    attempts = db.query(ExamAttempt).order_by(ExamAttempt.id.desc()).all()
    return templates.TemplateResponse("admin_attempts.html", {"request": request, "attempts": attempts, "admin_key": ADMIN_KEY})


@app.get("/admin/attempts/{attempt_id}")
def admin_attempt_detail(attempt_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    attempt = db.query(ExamAttempt).filter(ExamAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    answers = db.query(ExamAnswer).filter(ExamAnswer.attempt_id == attempt.id).all()
    return templates.TemplateResponse(
        "admin_attempt_detail.html", {"request": request, "attempt": attempt, "answers": answers, "admin_key": ADMIN_KEY}
    )
