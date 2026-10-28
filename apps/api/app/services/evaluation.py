import hashlib
import logging
import time
import uuid
from statistics import mean

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import SAMPLE_DATASET_NAME
from app.core.time import utcnow
from app.db.session import SessionLocal
from app.models import (
    Document,
    DocumentChunk,
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    User,
)
from app.services.chat import answer_question
from app.services.documents import create_document
from app.services.embeddings import get_embeddings
from app.services.files import validate_upload
from app.services.jobs import enqueue_job
from app.services.policies import is_abstention
from app.services.processing import process_document
from app.services.retrieval import retrieve_chunks
from app.services.tools import ToolContext, execute_tool

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "These figures describe this labelled dataset and configuration. "
    "They are not a real-world guarantee."
)

SAMPLE_CASES = [
    {
        "case_type": "retrieval",
        "question": "What is the specification code?",
        "expected_substrings": ["SPEC-CTX-1842"],
        "expect_abstention": False,
        "sort_order": 1,
    },
    {
        "case_type": "retrieval",
        "question": "What is the technical architecture?",
        "expected_substrings": ["FastAPI", "pgvector"],
        "expect_abstention": False,
        "sort_order": 2,
    },
    {
        "case_type": "answer",
        "question": "What outstanding task mentions API authentication?",
        "expected_substrings": ["Complete API authentication"],
        "expect_abstention": False,
        "sort_order": 3,
    },
    {
        "case_type": "answer",
        "question": "Does the brief define a project budget?",
        "expected_substrings": ["does not define a project budget"],
        "expect_abstention": False,
        "sort_order": 4,
    },
    {
        "case_type": "answer",
        "question": "Who operates the lunar pager relay?",
        "expected_substrings": [],
        "expect_abstention": True,
        "sort_order": 5,
    },
    {
        "case_type": "answer",
        "question": "How wide are the embedding vectors?",
        "expected_substrings": ["384-dimensional"],
        "expect_abstention": False,
        "sort_order": 6,
    },
    {
        "case_type": "workflow",
        "question": "Create a proposed evaluation task",
        "tool_name": "create_task",
        "tool_arguments": {"title": "Write the evaluation summary", "status": "proposed"},
        "expected": {"status": "proposed", "idempotent": True},
        "sort_order": 7,
    },
    {
        "case_type": "workflow",
        "question": "Summarize a document the user does not own",
        "tool_name": "summarize_document",
        "tool_arguments": {"document_id": "00000000-0000-0000-0000-000000000099"},
        "expected": {"error_category": "not_found"},
        "sort_order": 8,
    },
]


def recall_at_k(retrieved_texts: list[str], expected: list[str], k: int) -> float:
    if not expected:
        return 1.0
    window = "\n".join(retrieved_texts[:k]).lower()
    found = sum(1 for item in expected if item.lower() in window)
    return found / len(expected)


def precision_at_k(retrieved_texts: list[str], expected: list[str], k: int) -> float:
    window = retrieved_texts[:k]
    if not window or not expected:
        return 1.0 if not expected else 0.0
    hits = sum(1 for text in window if any(item.lower() in text.lower() for item in expected))
    return hits / len(window)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


async def ensure_sample_dataset(session: AsyncSession) -> EvaluationDataset:
    dataset = await session.scalar(select(EvaluationDataset).where(EvaluationDataset.name == SAMPLE_DATASET_NAME))
    if dataset is None:
        dataset = EvaluationDataset(
            name=SAMPLE_DATASET_NAME,
            description=(
                "Small labelled set based on samples/project-brief.md. "
                "Use it to catch regressions. Do not treat the score as a production quality guarantee."
            ),
        )
        session.add(dataset)
        await session.flush()
    existing = await session.scalar(select(EvaluationCase.id).where(EvaluationCase.dataset_id == dataset.id))
    if existing is not None:
        return dataset
    for item in SAMPLE_CASES:
        session.add(
            EvaluationCase(
                dataset_id=dataset.id,
                case_type=item["case_type"],
                question=item.get("question"),
                expected_substrings=item.get("expected_substrings", []),
                expect_abstention=item.get("expect_abstention", False),
                tool_name=item.get("tool_name"),
                tool_arguments=item.get("tool_arguments", {}),
                expected=item.get("expected", {}),
                sort_order=item["sort_order"],
            )
        )
    await session.flush()
    return dataset


async def ensure_sample_corpus(user_id: uuid.UUID) -> None:
    path = settings.sample_document_path
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    document_id: uuid.UUID | None = None
    async with SessionLocal() as session:
        existing = await session.scalar(
            select(Document).where(Document.user_id == user_id, Document.content_sha256 == digest)
        )
        if existing is not None and existing.status == "completed":
            return
        if existing is None:
            upload = validate_upload(path.name, data, max_bytes=settings.max_upload_bytes)
            document = await create_document(session, user_id=user_id, upload=upload, enqueue=False)
            document_id = document.id
        else:
            document_id = existing.id
        await session.commit()
    if document_id is not None:
        await process_document(document_id)


async def run_evaluation(run_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            run = await session.get(EvaluationRun, run_id)
            if run is None or run.status == "completed":
                return
            run.status = "running"
            run.started_at = utcnow()
            user_id = run.user_id
            dataset_id = run.dataset_id
            use_sample = bool((run.config or {}).get("use_sample_corpus", True))
    try:
        if use_sample:
            await ensure_sample_corpus(user_id)
        async with SessionLocal() as session:
            cases = list(
                await session.scalars(
                    select(EvaluationCase).where(EvaluationCase.dataset_id == dataset_id).order_by(EvaluationCase.sort_order)
                )
            )
            case_ids = [case.id for case in cases]
            snapshots = [
                {
                    "id": case.id,
                    "case_type": case.case_type,
                    "question": case.question,
                    "expected_substrings": list(case.expected_substrings or []),
                    "expect_abstention": case.expect_abstention,
                    "tool_name": case.tool_name,
                    "tool_arguments": dict(case.tool_arguments or {}),
                    "expected": dict(case.expected or {}),
                }
                for case in cases
            ]
        async with SessionLocal() as session:
            async with session.begin():
                await session.execute(delete(EvaluationResult).where(EvaluationResult.run_id == run_id))
        results = []
        for snapshot in snapshots:
            try:
                results.append(await _evaluate_case(user_id, snapshot))
            except Exception as exc:
                logger.warning(
                    "evaluation case failed",
                    extra={"component": "evaluation", "error_category": type(exc).__name__},
                )
                results.append(
                    {
                        "case_id": snapshot["id"],
                        "passed": False,
                        "failure_reason": type(exc).__name__,
                        "metrics": {},
                        "details": {},
                        "case_type": snapshot["case_type"],
                        "recall": None,
                        "precision": None,
                    }
                )
        metrics = _aggregate(results)
        async with SessionLocal() as session:
            async with session.begin():
                for item in results:
                    session.add(
                        EvaluationResult(
                            run_id=run_id,
                            case_id=item["case_id"],
                            passed=item["passed"],
                            failure_reason=item.get("failure_reason"),
                            metrics=item.get("metrics") or {},
                            details=item.get("details") or {},
                        )
                    )
                run = await session.get(EvaluationRun, run_id)
                if run is not None:
                    run.status = "completed"
                    run.metrics = metrics
                    run.finished_at = utcnow()
                    run.error_code = None
        del case_ids
    except Exception:
        logger.exception("evaluation run failed", extra={"component": "evaluation", "error_category": "evaluation_failed"})
        async with SessionLocal() as session:
            async with session.begin():
                run = await session.get(EvaluationRun, run_id)
                if run is not None and run.status != "completed":
                    run.status = "failed"
                    run.error_code = "evaluation_failed"
                    run.finished_at = utcnow()


async def _evaluate_case(user_id: uuid.UUID, case: dict) -> dict:
    if case["case_type"] == "workflow":
        return await _evaluate_workflow(user_id, case)
    started = time.perf_counter()
    async with SessionLocal() as session:
        outcome = await retrieve_chunks(session, user_id=user_id, query=case["question"] or "", limit=5)
        texts = [chunk.content for chunk in outcome.chunks]
    retrieval_ms = (time.perf_counter() - started) * 1000
    expected = case["expected_substrings"]
    recall = None if case["expect_abstention"] else recall_at_k(texts, expected, 5)
    precision = None if case["expect_abstention"] else precision_at_k(texts, expected, 5)
    if case["case_type"] == "retrieval":
        passed = recall == 1
        return {
            "case_id": case["id"],
            "case_type": "retrieval",
            "passed": passed,
            "failure_reason": None if passed else "Expected evidence was not in the top 5 chunks.",
            "recall": recall,
            "precision": precision,
            "metrics": {"recall_at_5": recall, "precision_at_5": precision, "retrieval_ms": round(retrieval_ms, 2)},
            "details": {"retrieved": len(texts)},
        }
    answer = await answer_question(user_id=user_id, question=case["question"] or "", history=[])
    citations = answer["citations"]
    if case["expect_abstention"]:
        passed = is_abstention(answer["content"]) and not citations
        reason = None if passed else "The answer did not abstain, or it cited evidence anyway."
        support = None
    else:
        support = await _citation_support(expected, citations)
        passed = support == 1
        reason = None if passed else "A cited source did not contain the expected evidence."
    return {
        "case_id": case["id"],
        "case_type": "answer",
        "passed": passed,
        "failure_reason": reason,
        "recall": recall,
        "precision": precision,
        "support": support,
        "abstention": case["expect_abstention"],
        "abstention_correct": passed if case["expect_abstention"] else None,
        "metrics": {
            "recall_at_5": recall,
            "precision_at_5": precision,
            "citation_support": support,
            "retrieval_ms": round(retrieval_ms, 2),
            "generation_ms": answer["diagnostics"].get("generation_ms"),
        },
        "details": {
            "insufficient_support": answer["diagnostics"].get("insufficient_support"),
            "citation_count": len(citations),
        },
    }


async def _citation_support(expected: list[str], citations: list[dict]) -> float:
    if not expected:
        return 1.0
    chunk_ids = [uuid.UUID(item["chunk_id"]) for item in citations if item.get("chunk_id")]
    if not chunk_ids:
        return 0.0
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))))
    blob = "\n".join(row.content for row in rows).lower()
    found = sum(1 for item in expected if item.lower() in blob)
    return found / len(expected)


async def _evaluate_workflow(user_id: uuid.UUID, case: dict) -> dict:
    expected = case["expected"]
    key = f"eval:{case['id']}"
    async with SessionLocal() as session:
        async with session.begin():
            first = await execute_tool(
                case["tool_name"],
                case["tool_arguments"],
                ToolContext(session=session, user_id=user_id, invoked_by="user", approved=True, idempotency_key=key),
            )
            second = await execute_tool(
                case["tool_name"],
                case["tool_arguments"],
                ToolContext(session=session, user_id=user_id, invoked_by="user", approved=True, idempotency_key=key),
            )
    if expected.get("error_category"):
        passed = first.error_category == expected["error_category"]
        reason = None if passed else f"Expected {expected['error_category']}."
    else:
        same = first.resource_id == second.resource_id
        status_ok = first.data.get("status") == expected.get("status")
        passed = same and status_ok
        reason = None if passed else "The workflow result did not match the expected status or was not idempotent."
    return {
        "case_id": case["id"],
        "case_type": "workflow",
        "passed": passed,
        "failure_reason": reason,
        "recall": None,
        "precision": None,
        "metrics": {"idempotent": first.resource_id == second.resource_id},
        "details": {"status": first.status, "error_category": first.error_category},
    }


def _aggregate(results: list[dict]) -> dict:
    recalls = [item["recall"] for item in results if item.get("recall") is not None]
    precisions = [item["precision"] for item in results if item.get("precision") is not None]
    supports = [item["support"] for item in results if item.get("support") is not None]
    abstentions = [item["abstention_correct"] for item in results if item.get("abstention_correct") is not None]
    workflows = [item for item in results if item.get("case_type") == "workflow"]
    retrieval_ms = [
        item["metrics"]["retrieval_ms"] for item in results if item.get("metrics", {}).get("retrieval_ms") is not None
    ]
    return {
        "retrieval_recall_at_5": _average(recalls),
        "retrieval_precision_at_5": _average(precisions),
        "citation_support_rate": _average(supports),
        "abstention_accuracy": _average([1.0 if value else 0.0 for value in abstentions]),
        "workflow_pass_rate": _average([1.0 if item["passed"] else 0.0 for item in workflows]),
        "mean_retrieval_ms": _average(retrieval_ms),
        "case_count": len(results),
        "failed_cases": sum(1 for item in results if not item["passed"]),
        "embedding_provider": get_embeddings().provider,
        "llm_provider": "gemini" if settings.llm_configured else "none",
        "disclaimer": DISCLAIMER,
    }


async def enqueue_evaluation(session: AsyncSession, *, user_id: uuid.UUID, use_sample_corpus: bool) -> EvaluationRun:
    dataset = await ensure_sample_dataset(session)
    run = EvaluationRun(
        dataset_id=dataset.id,
        user_id=user_id,
        status="queued",
        config={
            "use_sample_corpus": use_sample_corpus,
            "embedding_provider": settings.embedding_provider,
            "llm_configured": settings.llm_configured,
            "gemini_model": settings.gemini_model if settings.llm_configured else None,
        },
    )
    session.add(run)
    await session.flush()
    await enqueue_job(session, job_type="evaluation_run", payload={"run_id": str(run.id)}, max_attempts=1)
    return run
