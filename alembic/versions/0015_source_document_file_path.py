"""source_document_file_path

전표 원본 PDF 미리보기(관리자 HITL 상세 패널) 기능 추가 — 지금까지
api/document_ingestion.py::ingest_uploaded_document()는 업로드된 file_bytes를
해시 계산·OCR 텍스트 추출에만 쓰고 디스크에 저장하지 않아서, source_documents에
file_hash·extracted_json만 남고 원본을 다시 볼 방법이 없었다. 업로드 파이프라인이
파일을 data/uploads/ 아래 저장하고 그 경로를 기록할 수 있도록 컬럼을 추가한다.

DB에 파일 바이너리(BYTEA)가 아니라 경로만 저장하는 이유는 기존 관례를 따르기
위함이다 — docker-compose.yml에 이미 ./data:/app/data 볼륨이 마운트돼 있고,
.gitignore가 data/ 하위 실데이터 폴더를 이미 제외하고 있으며,
scripts/generate_upload_docs.py가 같은 방식(파일시스템 저장)의 선례다. Supabase는
여러 명이 동시 접속하는 공유 개발 DB라(CLAUDE.md §3) 바이너리를 얹지 않는다.

nullable로 둔다 — 이 리비전 이전에 업로드된 source_documents 레코드는 file_path가
없다.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('source_documents', sa.Column('file_path', sa.String(500)))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('source_documents', 'file_path')
