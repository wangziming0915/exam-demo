import json
from pathlib import Path
from typing import Dict, Any

# In-memory cache
_CACHE: Dict[str, Any] | None = None


def _questions_path() -> Path:
    # app/services/grading_service.py -> app/questions.json
    return Path(__file__).resolve().parent.parent / "questions.json"


def load_questions() -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    path = _questions_path()
    with path.open("r", encoding="utf-8") as f:
        _CACHE = json.load(f)

    return _CACHE


def clear_cache() -> None:
    global _CACHE
    _CACHE = None


def get_exam_public_view() -> Dict[str, Any]:
    """
    Return questions WITHOUT correct_option
    """
    data = load_questions()
    questions = []

    for q in data.get("questions", []):
        questions.append(
            {
                "id": str(q["id"]),
                "text": q["text"],
                "options": q["options"],
            }
        )

    return {
        "pass_threshold": int(data.get("pass_threshold", 0)),
        "questions": questions,
    }


def get_full_questions_map() -> Dict[str, Dict[str, Any]]:
    """
    Return full questions WITH correct_option, keyed by question id
    """
    data = load_questions()
    return {str(q["id"]): q for q in data.get("questions", [])}


def grade_submission(submitted: Dict[str, str]) -> Dict[str, Any]:
    data = load_questions()
    questions = data.get("questions", [])
    pass_threshold = int(data.get("pass_threshold", 0))

    score = 0
    total = len(questions)
    wrong_questions = []

    for q in questions:
        qid = str(q["id"])
        correct = str(q.get("correct_option", "")).strip().upper()
        selected = str(submitted.get(qid, "")).strip().upper()

        if selected == correct:
            score += 1
        else:
            wrong_questions.append(
                {
                    "question_id": qid,
                    "selected_option": selected,
                    "correct_option": correct,
                }
            )

    passed = score >= pass_threshold

    return {
        "score": score,
        "total": total,
        "passed": passed,
        "wrong_questions": wrong_questions,
    }
