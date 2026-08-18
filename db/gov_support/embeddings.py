"""임베딩 생성 — gemini-embedding-2, output_dimensionality=768.
docs/gov-support-matching-plan.md §6-1 정본.

비대칭 검색이라 task_type을 구분한다 — 배치가 raw_text(지원사업 원문)를
임베딩할 땐 embed_document()(RETRIEVAL_DOCUMENT), 매칭 시점에 기업 프로필
쿼리를 임베딩할 땐 embed_query()(RETRIEVAL_QUERY). 같은 텍스트라도
task_type이 다르면 임베딩 값이 달라지므로 두 함수를 절대 바꿔 쓰지 않는다.

실패 시 None을 반환한다(예외를 삼키고 조용히 대체값을 채우지 않음) — 호출부가
"임베딩 실패"로 처리해 후보를 억지로 채우지 않는다(CLAUDE.md §6 실패 가시성 원칙).
"""
import os

from google import genai
from google.genai import types

MODEL = "gemini-embedding-2"
OUTPUT_DIMENSIONALITY = 768


def _embed(text: str, task_type: str) -> list[float] | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not text:
        return None
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=10_000),  # ms — 행 걸림은 빠르게 실패로
        )
        resp = client.models.embed_content(
            model=MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=OUTPUT_DIMENSIONALITY,
            ),
        )
        return list(resp.embeddings[0].values)
    except Exception:
        return None


def embed_document(text: str) -> list[float] | None:
    """배치가 raw_text(지원사업 원문)를 임베딩할 때 쓴다."""
    return _embed(text, "RETRIEVAL_DOCUMENT")


def embed_query(text: str) -> list[float] | None:
    """매칭 시점에 기업 프로필 쿼리를 임베딩할 때 쓴다."""
    return _embed(text, "RETRIEVAL_QUERY")
