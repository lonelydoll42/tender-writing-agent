"""Project file registration and parse-artifact facade.

The public registry API stays stable while its state is delegated to a
pluggable Store.  This keeps local tests lightweight and allows the service to
use SQLite without changing tender Skills.
"""

from __future__ import annotations

import hashlib
import html
import inspect
import json
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import uuid4

from qiaowenshu_agent.core.store import (
    Artifact,
    HumanReviewTask,
    InMemoryStore,
    Store,
)
from qiaowenshu_agent.domain.document_structure import build_document_structure
from qiaowenshu_agent.domain.models import SourceReference


_FILE_ROLES = {
    "tender",
    "clarification",
    "bidder_material",
    "bid_draft",
    "other",
}
_PARSE_STATUSES = {"pending", "success", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _unique_strings(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class ProjectFile:
    file_id: str
    project_id: str
    file_name: str
    file_role: str = "other"
    material_type: str | None = None
    version: int = 1
    checksum: str = ""
    uploaded_at: str = ""
    parse_status: str = "pending"
    page_count: int | None = None
    parse_artifact_id: str | None = None
    supersedes: str | None = None
    parse_error: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FileRegistration:
    file: ProjectFile
    deduplicated: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = self.file.to_dict()
        result["deduplicated"] = self.deduplicated
        return result


class FileRegistryError(ValueError):
    """Base error raised for invalid or unavailable project files."""


class OCRBackend(Protocol):
    """Synchronous page OCR port used by the local parser."""

    def run(self, payload: Mapping[str, Any]) -> Mapping[str, Any] | str: ...


class ProjectFileRegistry:
    """Thread-safe project file registry backed by a pluggable Store.

    File bytes are kept separately from the public metadata, so API responses
    never accidentally serialize uploaded documents.
    """

    def __init__(
        self,
        store: Store | None = None,
        *,
        ocr_backend: OCRBackend | Any | None = None,
    ) -> None:
        self.store: Store = store or InMemoryStore()
        self.ocr_backend = ocr_backend
        self._lock = threading.RLock()

    def register(
        self,
        *,
        project_id: str,
        file_name: str,
        content: bytes,
        file_role: str = "other",
        material_type: str | None = None,
        file_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> FileRegistration:
        project_id = _clean(project_id)
        file_name = Path(_clean(file_name)).name
        if not project_id:
            raise FileRegistryError("project_id is required")
        if not file_name:
            raise FileRegistryError("file_name is required")
        if not isinstance(content, bytes) or not content:
            raise FileRegistryError("file content must be non-empty bytes")
        file_role = _clean(file_role).lower() or "other"
        if file_role not in _FILE_ROLES:
            file_role = "other"
        checksum = hashlib.sha256(content).hexdigest()

        with self._lock:
            self.store.ensure_project(project_id)
            for existing in self.store.list_files(project_id):
                if existing.project_id == project_id and existing.checksum == checksum:
                    return FileRegistration(existing, deduplicated=True)

            previous = self._latest_same_file(
                project_id,
                file_name=file_name,
                file_role=file_role,
            )
            resolved_id = _clean(file_id) or f"file_{uuid4().hex[:16]}"
            if self.store.get_file(resolved_id) is not None:
                raise FileRegistryError(f"file_id already exists: {resolved_id}")
            record = ProjectFile(
                file_id=resolved_id,
                project_id=project_id,
                file_name=file_name,
                file_role=file_role,
                material_type=_clean(material_type) or None,
                version=(previous.version + 1 if previous else 1),
                checksum=checksum,
                uploaded_at=_now(),
                metadata=dict(metadata or {}),
                supersedes=previous.file_id if previous else None,
            )
            self.store.save_file(record, content)
            if previous is not None:
                self.store.invalidate_from_files([previous.file_id])
            return FileRegistration(record)

    def register_path(
        self,
        *,
        project_id: str,
        path: str | Path,
        file_role: str = "other",
        material_type: str | None = None,
        file_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> FileRegistration:
        source = Path(path)
        if not source.is_file():
            raise FileRegistryError(f"file does not exist: {source}")
        return self.register(
            project_id=project_id,
            file_name=source.name,
            content=source.read_bytes(),
            file_role=file_role,
            material_type=material_type,
            file_id=file_id,
            metadata=metadata,
        )

    def get(self, file_id: str) -> ProjectFile | None:
        with self._lock:
            return self.store.get_file(_clean(file_id))

    def require(self, file_id: str) -> ProjectFile:
        record = self.get(file_id)
        if record is None:
            raise FileRegistryError(f"file not found: {_clean(file_id)}")
        return record

    def content(self, file_id: str) -> bytes:
        with self._lock:
            self.require(file_id)
            try:
                return self.store.file_content(_clean(file_id))
            except KeyError as exc:
                raise FileRegistryError(f"file not found: {_clean(file_id)}") from exc

    def list(
        self, project_id: str, *, file_role: str | None = None
    ) -> list[ProjectFile]:
        role = _clean(file_role).lower()
        with self._lock:
            return list(
                self.store.list_files(_clean(project_id), file_role=role or None)
            )

    def parse(self, file_id: str, *, force: bool = False) -> dict[str, Any]:
        record = self.require(file_id)
        source_version = f"{record.file_id}:v{record.version}"
        stale_cached_artifact: Artifact | None = None
        with self._lock:
            if (
                record.parse_status == "success"
                and record.parse_artifact_id
                and not force
            ):
                artifact = self.store.get_artifact(record.parse_artifact_id)
                if artifact is not None and artifact.status == "stale":
                    stale_cached_artifact = artifact
                if artifact is not None and _parse_artifact_matches(
                    artifact,
                    record,
                    source_version=source_version,
                ):
                    if _document_structure_matches(
                        artifact.content.get("document_structure"),
                        record,
                        source_version=source_version,
                    ) and _page_references_match(
                        artifact.content.get("pages"),
                        document_id=record.file_id,
                        source_version=source_version,
                    ):
                        return artifact.to_dict()
                    artifact = _upgrade_parse_artifact_structure(
                        artifact,
                        record,
                        source_version=source_version,
                    )
                    self.store.save_artifact(artifact)
                    return artifact.to_dict()

        try:
            artifact_id = f"artifact_{record.file_id}_{record.version}"
            pages, warnings = extract_document_pages(
                self.content(record.file_id),
                record.file_name,
                ocr_backend=self.ocr_backend,
            )
            source_version = self.file_version_token(record.file_id)
            for page in pages:
                page["source_references"] = _page_source_references(
                    document_id=record.file_id,
                    artifact_id=artifact_id,
                    page=page,
                    source_version=source_version,
                )
            warnings = _document_structure_warnings(record.file_name, warnings)
            document_structure = build_document_structure(
                pages,
                document_id=record.file_id,
                source_version=source_version,
                source_checksum=record.checksum,
            )
            text = "\f".join(str(page.get("text") or "") for page in pages)
            page_count = len(pages)
            content = {
                "file_id": record.file_id,
                "file_name": record.file_name,
                "version": record.version,
                "checksum": record.checksum,
                "text": text,
                "page_count": page_count,
                "warnings": warnings,
                "pages": pages,
                "document_structure": document_structure,
            }
            artifact = Artifact(
                artifact_id=artifact_id,
                artifact_type="parsed_document",
                project_id=record.project_id,
                schema_version="1.2",
                source_file_versions=[source_version],
                created_at=_now(),
                content_hash=_content_hash(content),
                status=(
                    stale_cached_artifact.status
                    if stale_cached_artifact is not None
                    else "valid"
                ),
                stale_reason=(
                    stale_cached_artifact.stale_reason
                    if stale_cached_artifact is not None
                    else None
                ),
                content=content,
            )
            updated = replace(
                record,
                parse_status="success",
                page_count=page_count,
                parse_artifact_id=artifact_id,
                parse_error=None,
            )
        except Exception as exc:
            updated = replace(
                record,
                parse_status="failed",
                parse_error=str(exc),
            )
            with self._lock:
                self.store.save_file(updated, self.content(record.file_id))
            raise

        with self._lock:
            self.store.save_file(updated, self.content(record.file_id))
            self.store.save_artifact(artifact)
        return artifact.to_dict()

    def artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._lock:
            artifact = self.store.get_artifact(_clean(artifact_id))
            return artifact.to_dict() if artifact else None

    def artifacts(
        self, project_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            return [
                artifact.to_dict()
                for artifact in self.store.list_artifacts(
                    _clean(project_id), status=status
                )
            ]

    def project(self, project_id: str) -> dict[str, Any] | None:
        project = self.store.get_project(_clean(project_id))
        return project.to_dict() if project else None

    def file_version_token(self, file_id: str) -> str:
        record = self.require(file_id)
        return f"{record.file_id}:v{record.version}"

    def save_artifact(
        self,
        content: Mapping[str, Any],
        *,
        project_id: str,
        artifact_type: str,
        artifact_id: str | None = None,
        schema_version: str = "1.0",
        source_file_versions: list[str] | None = None,
        dependencies: list[str] | None = None,
        created_by_run: str | None = None,
        status: str = "valid",
    ) -> dict[str, Any]:
        safe_content = json_safe_artifact(content)
        resolved_id = _clean(artifact_id) or f"artifact_{uuid4().hex[:16]}"
        record = Artifact(
            artifact_id=resolved_id,
            artifact_type=_clean(artifact_type) or "runtime_output",
            project_id=_clean(project_id),
            schema_version=_clean(schema_version) or "1.0",
            source_file_versions=list(source_file_versions or []),
            dependencies=list(dependencies or []),
            created_by_run=created_by_run,
            created_at=_now(),
            content_hash=_content_hash(safe_content),
            status=status,
            content=safe_content,
        )
        self.store.ensure_project(record.project_id)
        self.store.save_artifact(record)
        return record.to_dict()

    def create_review_task(
        self,
        *,
        project_id: str,
        question: str,
        review_id: str | None = None,
        severity: str = "warning",
        review_type: str = "manual_check",
        requirement_id: str | None = None,
        source_run_id: str | None = None,
        affected_artifact_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        timestamp = _now()
        task = HumanReviewTask(
            review_id=_clean(review_id) or f"review_{uuid4().hex[:16]}",
            project_id=_clean(project_id),
            severity=_clean(severity) or "warning",
            review_type=_clean(review_type) or "manual_check",
            requirement_id=_clean(requirement_id) or None,
            question=_clean(question),
            source_run_id=_clean(source_run_id) or None,
            affected_artifact_ids=list(affected_artifact_ids or []),
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.store.ensure_project(task.project_id)
        self.store.save_review(task)
        return task.to_dict()

    def review(self, review_id: str) -> dict[str, Any] | None:
        task = self.store.get_review(_clean(review_id))
        return task.to_dict() if task else None

    def reviews(
        self, project_id: str, *, status: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            task.to_dict()
            for task in self.store.list_reviews(_clean(project_id), status=status)
        ]

    def resolve_review(
        self, review_id: str, resolution: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        task = self.store.get_review(_clean(review_id))
        if task is None:
            return None
        resolved = replace(
            task,
            status="resolved",
            resolution=dict(resolution),
            updated_at=_now(),
        )
        self.store.save_review(resolved)
        return resolved.to_dict()

    def _latest_same_file(
        self,
        project_id: str,
        *,
        file_name: str,
        file_role: str,
    ) -> ProjectFile | None:
        candidates = [
            item
            for item in self.store.list_files(project_id, file_role=file_role)
            if item.file_name == file_name
        ]
        return max(candidates, key=lambda item: item.version) if candidates else None


def _parse_artifact_matches(
    artifact: Artifact,
    record: ProjectFile,
    *,
    source_version: str,
) -> bool:
    content = artifact.content
    return (
        artifact.artifact_type == "parsed_document"
        and artifact.artifact_id == f"artifact_{record.file_id}_{record.version}"
        and artifact.project_id == record.project_id
        and artifact.source_file_versions == [source_version]
        and content.get("file_id") == record.file_id
        and content.get("version") == record.version
        and content.get("checksum") == record.checksum
        and _content_hash(content) == artifact.content_hash
    )


def _document_structure_matches(
    value: Any,
    record: ProjectFile,
    *,
    source_version: str,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    checksum = value.get("checksum", value.get("source_checksum"))
    return (
        value.get("schema_version") == "document-structure-v1"
        and value.get("document_id") == record.file_id
        and value.get("source_version") == source_version
        and checksum == record.checksum
    )


def _page_references_match(
    value: Any,
    *,
    document_id: str,
    source_version: str,
) -> bool:
    if not isinstance(value, (list, tuple)) or not value:
        return False
    for page in value:
        if not isinstance(page, Mapping):
            return False
        references = page.get("source_references")
        if not isinstance(references, (list, tuple)) or not references:
            return False
        if any(
            not isinstance(reference, Mapping)
            or reference.get("document_id") != document_id
            or reference.get("source_version") != source_version
            for reference in references
        ):
            return False
    return True


def _upgrade_parse_artifact_structure(
    artifact: Artifact,
    record: ProjectFile,
    *,
    source_version: str,
) -> Artifact:
    content = dict(artifact.content)
    raw_pages = content.get("pages")
    pages = (
        [dict(page) for page in raw_pages if isinstance(page, Mapping)]
        if isinstance(raw_pages, (list, tuple))
        else []
    )
    if not pages:
        pages = _text_pages(str(content.get("text") or ""))
    for page_number, page in enumerate(pages, start=1):
        page.setdefault("page_number", page_number)
        if not _page_references_match(
            [page],
            document_id=record.file_id,
            source_version=source_version,
        ):
            page["source_references"] = _page_source_references(
                document_id=record.file_id,
                artifact_id=artifact.artifact_id,
                page=page,
                source_version=source_version,
            )

    warnings = content.get("warnings")
    warnings = list(warnings) if isinstance(warnings, (list, tuple)) else []
    warnings = _document_structure_warnings(record.file_name, warnings)
    content.update(
        {
            "file_id": record.file_id,
            "file_name": record.file_name,
            "version": record.version,
            "checksum": record.checksum,
            "text": str(
                content.get("text")
                if content.get("text") is not None
                else "\f".join(str(page.get("text") or "") for page in pages)
            ),
            "page_count": len(pages),
            "warnings": warnings,
            "pages": pages,
            "document_structure": build_document_structure(
                pages,
                document_id=record.file_id,
                source_version=source_version,
                source_checksum=record.checksum,
            ),
        }
    )
    return replace(
        artifact,
        schema_version="1.2",
        content_hash=_content_hash(content),
        content=content,
    )


def _document_structure_warnings(
    file_name: str,
    warnings: list[str],
) -> list[str]:
    suffix = Path(file_name).suffix.lower()
    notes: list[str] = []
    if suffix == ".pdf":
        notes.append(
            "document_structure.raw_text is extracted page text, not original "
            "PDF layout; OCR accuracy is not independently verified."
        )
    elif suffix in {".docx", ".xlsx", ".xlsm"}:
        notes.append(
            "The existing Office extractor flattens document XML, tables, or "
            "sheet data into page text; native Office hierarchy and layout are "
            "not represented."
        )
    elif suffix == ".xml":
        notes.append(
            "XML is retained as extracted text; document_structure does not "
            "model the native XML element hierarchy."
        )
    return _unique_strings([*warnings, *notes])


def _content_hash(content: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(content),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def extract_document_pages(
    content: bytes,
    file_name: str,
    *,
    ocr_backend: OCRBackend | Any | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract page text and preserve available extraction provenance.

    Native PDF text is extracted page by page.  If an OCR backend is supplied,
    image pages are rendered with ``pdftoppm`` and sent to that backend.  A
    missing OCR backend never turns an empty page into a passing fact.

    Downstream document-structure ``raw_text`` is this extracted page text, not
    source binary data or a guarantee of original PDF layout or OCR accuracy.
    The existing DOCX/XLSX readers flatten selected XML/table/sheet content;
    XML input is treated as text rather than a parsed element hierarchy.
    """

    suffix = Path(file_name).suffix.lower()
    warnings: list[str] = []
    if suffix == ".pdf" or content.startswith(b"%PDF"):
        page_count = _pdf_page_count(content)
        image_pages = _pdf_pages_with_images(content)
        pages: list[dict[str, Any]] = []
        for page_number in range(1, page_count + 1):
            native_text = _extract_pdf_page_text(content, page_number)
            page_warnings: list[str] = []
            page_type = "native_text" if native_text.strip() else "scanned"
            extraction_method = "native_text" if native_text.strip() else "ocr_required"
            page_text = native_text
            confidence = 1.0 if native_text.strip() else 0.0
            regions: list[dict[str, Any]] = []
            should_ocr = ocr_backend is not None and (
                not native_text.strip() or page_number in image_pages
            )
            if should_ocr:
                image = _render_pdf_page(content, page_number)
                if image is None:
                    page_warnings.append(
                        "page image rendering unavailable; OCR was not run"
                    )
                else:
                    try:
                        ocr_text, ocr_confidence, ocr_regions, ocr_warnings = (
                            _run_ocr_backend(
                                ocr_backend,
                                image=image,
                                page_number=page_number,
                                file_name=file_name,
                            )
                        )
                        page_warnings.extend(ocr_warnings)
                        regions = ocr_regions
                        if ocr_text.strip():
                            if native_text.strip():
                                if ocr_text.strip() not in native_text:
                                    page_text = (
                                        native_text.rstrip()
                                        + "\n"
                                        + ocr_text.strip()
                                    )
                                extraction_method = "mixed"
                                page_type = "mixed"
                                confidence = min(1.0, ocr_confidence)
                            else:
                                page_text = ocr_text
                                extraction_method = "ocr"
                                confidence = ocr_confidence
                                page_type = (
                                    "table_heavy"
                                    if _looks_table_heavy(page_text)
                                    else "scanned"
                                )
                    except (TypeError, ValueError, RuntimeError) as exc:
                        page_warnings.append(f"OCR failed: {exc}")
            if not page_text.strip():
                page_warnings.append(
                    "no text extracted; OCR or manual review is required"
                )
                extraction_method = "ocr_required"
                confidence = 0.0
            elif _looks_table_heavy(page_text) and page_type == "native_text":
                page_type = "table_heavy"
            page = {
                "page_number": page_number,
                "text": page_text,
                "page_type": page_type,
                "extraction_method": extraction_method,
                "confidence": round(max(0.0, min(confidence, 1.0)), 4),
                "regions": regions,
                "warnings": _unique_strings(page_warnings),
            }
            pages.append(page)
            warnings.extend(
                f"page {page_number}: {warning}" for warning in page["warnings"]
            )
        return pages, _unique_strings(warnings)
    if suffix == ".docx":
        return [_text_page(_extract_docx_text(content))], warnings
    if suffix in {".xlsx", ".xlsm"}:
        return [_text_page(_extract_xlsx_text(content))], warnings
    if suffix in {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".html"}:
        text = _decode_text(content)
        return _text_pages(text), warnings
    text = _decode_text(content)
    if not text.strip():
        warnings.append("unsupported binary format; OCR or external parser is required")
    return _text_pages(text), warnings


def extract_document_text(content: bytes, file_name: str) -> tuple[str, int, list[str]]:
    """Compatibility wrapper returning the legacy flattened text contract."""

    pages, warnings = extract_document_pages(content, file_name)
    text = "\f".join(str(page.get("text") or "") for page in pages)
    return text, len(pages), warnings


def _extract_pdf_page_text(content: bytes, page_number: int) -> str:
    executable = _find_executable("pdftotext")
    if executable is None:
        return ""
    with tempfile.TemporaryDirectory(prefix="qiaowenshu-pdf-") as directory:
        source = Path(directory) / "source.pdf"
        source.write_bytes(content)
        result = subprocess.run(
            [
                executable,
                "-layout",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                str(source),
                "-",
            ],
            capture_output=True,
            check=False,
            timeout=45,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.decode("utf-8", errors="replace").replace("\f", "")


def _pdf_page_count(content: bytes) -> int:
    executable = _find_executable("pdfinfo")
    if executable is not None:
        with tempfile.TemporaryDirectory(prefix="qiaowenshu-pdf-info-") as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(content)
            result = subprocess.run(
                [executable, str(source)],
                capture_output=True,
                check=False,
                timeout=30,
            )
            match = re.search(
                rb"^Pages:\s*(\d+)", result.stdout, flags=re.MULTILINE
            )
            if result.returncode == 0 and match:
                return max(1, int(match.group(1)))
    pages = re.findall(rb"/Type\s*/Page\b", content)
    return max(1, len(pages))


def _pdf_pages_with_images(content: bytes) -> set[int]:
    executable = _find_executable("pdfimages")
    if executable is None:
        return set()
    with tempfile.TemporaryDirectory(prefix="qiaowenshu-pdf-images-") as directory:
        source = Path(directory) / "source.pdf"
        source.write_bytes(content)
        result = subprocess.run(
            [executable, "-list", str(source)],
            capture_output=True,
            check=False,
            timeout=45,
        )
    if result.returncode != 0:
        return set()
    pages: set[int] = set()
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        match = re.match(r"\s*(\d+)\s+\d+\s+", line)
        if match:
            pages.add(int(match.group(1)))
    return pages


def _render_pdf_page(content: bytes, page_number: int) -> bytes | None:
    executable = _find_executable("pdftoppm")
    if executable is None:
        return None
    with tempfile.TemporaryDirectory(prefix="qiaowenshu-pdf-render-") as directory:
        source = Path(directory) / "source.pdf"
        prefix = Path(directory) / "page"
        source.write_bytes(content)
        result = subprocess.run(
            [
                executable,
                "-png",
                "-singlefile",
                "-r",
                "200",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                str(source),
                str(prefix),
            ],
            capture_output=True,
            check=False,
            timeout=60,
        )
        image_path = prefix.with_suffix(".png")
        if result.returncode != 0 or not image_path.is_file():
            return None
        return image_path.read_bytes()


def _find_executable(name: str) -> str | None:
    direct = shutil.which(name)
    native = shutil.which(f"{name}.exe")
    if native:
        return native
    return direct


def _run_ocr_backend(
    backend: Any,
    *,
    image: bytes,
    page_number: int,
    file_name: str,
) -> tuple[str, float, list[dict[str, Any]], list[str]]:
    runner = getattr(backend, "run", None) or getattr(backend, "recognize", None)
    if runner is None and callable(backend):
        runner = backend
    if not callable(runner):
        raise TypeError("OCR backend must expose run/recognize or be callable")
    raw = runner(
        {
            "file_name": file_name,
            "page_number": page_number,
            "image": image,
            "mime_type": "image/png",
        }
    )
    if inspect.isawaitable(raw):
        raise RuntimeError("OCR backend must be synchronous for file parsing")
    if isinstance(raw, str):
        return raw, 0.0, [], ["OCR backend returned no confidence"]
    if not isinstance(raw, Mapping):
        raise TypeError("OCR backend must return text or an object")
    text = str(raw.get("text") or raw.get("content") or "")
    confidence = _confidence_value(
        raw.get("confidence", raw.get("ocr_confidence"))
    )
    warnings = [str(item) for item in raw.get("warnings") or []]
    if raw.get("confidence", raw.get("ocr_confidence")) in (None, ""):
        warnings.append("OCR backend returned no confidence")
    regions = [
        dict(region)
        for region in (raw.get("regions") or raw.get("blocks") or [])
        if isinstance(region, Mapping)
    ]
    return text, confidence, regions, _unique_strings(warnings)


def _text_page(text: str) -> dict[str, Any]:
    return {
        "page_number": 1,
        "text": text,
        "page_type": "native_text" if text.strip() else "scanned",
        "extraction_method": "native_text" if text.strip() else "ocr_required",
        "confidence": 1.0 if text.strip() else 0.0,
        "regions": [],
        "warnings": [],
    }


def _text_pages(text: str) -> list[dict[str, Any]]:
    return [
        {
            **_text_page(page_text),
            "page_number": page_number,
        }
        for page_number, page_text in enumerate(text.split("\f"), start=1)
    ] or [_text_page("")]


def _confidence_value(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence > 1 and confidence <= 100:
        confidence /= 100
    return round(max(0.0, min(confidence, 1.0)), 4)


def _page_source_references(
    *,
    document_id: str,
    artifact_id: str,
    page: Mapping[str, Any],
    source_version: str,
) -> list[dict[str, Any]]:
    page_number = int(page.get("page_number") or 1)
    page_confidence = _confidence_value(page.get("confidence"))
    extraction_method = str(page.get("extraction_method") or "")
    regions = page.get("regions") or []
    references: list[dict[str, Any]] = []
    for index, region in enumerate(regions, start=1):
        if not isinstance(region, Mapping):
            continue
        raw_bbox = region.get("bbox", region.get("bounding_box"))
        if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
            continue
        try:
            bbox = [float(value) for value in raw_bbox]
        except (TypeError, ValueError):
            continue
        references.append(
            SourceReference(
                document_id=document_id,
                page=page_number,
                quote=str(
                    region.get("text")
                    or region.get("content")
                    or page.get("text")
                    or ""
                )[:240],
                locator=f"{artifact_id}:p{page_number}:r{index}",
                bbox=bbox,
                confidence=_confidence_value(
                    region.get("confidence", page_confidence)
                ),
                extraction_method=extraction_method,
                source_version=source_version,
            ).to_dict()
        )
    if references:
        return references
    return [
        SourceReference(
            document_id=document_id,
            page=page_number,
            quote=str(page.get("text") or "")[:240],
            locator=f"{artifact_id}:p{page_number}",
            confidence=page_confidence,
            extraction_method=extraction_method,
            source_version=source_version,
        ).to_dict()
    ]


def _looks_table_heavy(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    marked_rows = sum(
        1
        for line in lines
        if line.count("\t") >= 2 or line.count("|") >= 2
    )
    return marked_rows >= 2 or (
        len(lines) >= 3
        and sum(len(re.findall(r"\s{2,}", line)) for line in lines) >= 4
    )


def _xml_text(value: bytes) -> str:
    text = value.decode("utf-8", errors="ignore")
    text = re.sub(r"<w:tab\s*/>|<tab\s*/>", "\t", text)
    text = re.sub(r"</w:p\s*>|</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def _extract_docx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(content)) as archive:
            return _xml_text(archive.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile):
        return _decode_text(content)


def _extract_xlsx_text(content: bytes) -> str:
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(content)) as archive:
            names = set(archive.namelist())
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                raw = archive.read("xl/sharedStrings.xml")
                shared = [
                    re.sub(r"<[^>]+>", "", html.unescape(item)).strip()
                    for item in re.findall(rb"<si>(.*?)</si>", raw, flags=re.S)
                ]
            rows: list[str] = []
            for name in sorted(
                item for item in names if item.startswith("xl/worksheets/sheet")
            ):
                xml = archive.read(name).decode("utf-8", errors="ignore")
                for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, flags=re.S):
                    values: list[str] = []
                    for cell in re.findall(r"<c[^>]*>(.*?)</c>", row, flags=re.S):
                        cell_type = re.search(r"t=\"([^\"]+)\"", cell)
                        value = re.search(r"<v>(.*?)</v>", cell, flags=re.S)
                        if value is None:
                            values.append("")
                            continue
                        item = html.unescape(re.sub(r"<[^>]+>", "", value.group(1)))
                        if cell_type and cell_type.group(1) == "s" and item.isdigit():
                            item = (
                                shared[int(item)] if int(item) < len(shared) else item
                            )
                        values.append(item.strip())
                    if values:
                        rows.append("\t".join(values))
            return "\n".join(rows)
    except zipfile.BadZipFile:
        return _decode_text(content)


def json_safe_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy suitable for API payloads and debugging output."""

    result = json.loads(json.dumps(dict(artifact), ensure_ascii=False, default=str))
    return result
