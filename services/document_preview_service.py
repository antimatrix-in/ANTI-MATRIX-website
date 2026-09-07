import os
import re
import html
import base64
import logging
from typing import Tuple, Optional, Dict, Any

from flask import current_app
from models import db, JobApplication, EmployeeDocument

logger = logging.getLogger('document_preview_service')

# In-memory LRU-like cache for converted document HTML: {file_path: (mtime, html_content)}
_DOCUMENT_PREVIEW_CACHE: Dict[str, Tuple[float, str]] = {}

# Custom style map for mammoth to generate clean, semantic HTML classes
MAMMOTH_STYLE_MAP = """
p[style-name='Title'] => h1.doc-title:fresh
p[style-name='Subtitle'] => p.doc-subtitle:fresh
p[style-name='Heading 1'] => h1.doc-heading:fresh
p[style-name='Heading 2'] => h2.doc-heading:fresh
p[style-name='Heading 3'] => h3.doc-heading:fresh
p[style-name='Heading 4'] => h4.doc-heading:fresh
table => table.doc-table:fresh
r[style-name='Strong'] => strong
r[style-name='Emphasis'] => em
"""


def convert_docx_to_html(file_path: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Safely converts a DOCX file on disk into HTML with embedded base64 images and styles.
    Purely Python-based; requires zero external binaries (no MS Word or LibreOffice).
    Returns (success, html_output, error_message).
    """
    if not file_path or not os.path.exists(file_path):
        return False, None, "Document file not found on server storage."

    try:
        current_mtime = os.path.getmtime(file_path)
    except Exception as e:
        logger.error(f"Error checking file mtime for {file_path}: {e}")
        return False, None, "Unable to access document file."

    # Check in-memory cache
    cached = _DOCUMENT_PREVIEW_CACHE.get(file_path)
    if cached and cached[0] == current_mtime:
        return True, cached[1], None

    try:
        import mammoth

        with open(file_path, 'rb') as docx_file:
            result = mammoth.convert_to_html(
                docx_file,
                style_map=MAMMOTH_STYLE_MAP
            )
            raw_html = result.value or ''

        # Basic post-processing / cleanup
        # Wrap tables in responsive wrapper if needed
        processed_html = raw_html.strip()
        if not processed_html:
            processed_html = "<p style='color: #64748b; font-style: italic;'>Document content is empty.</p>"

        # Cache the result
        _DOCUMENT_PREVIEW_CACHE[file_path] = (current_mtime, processed_html)
        return True, processed_html, None

    except Exception as exc:
        # Safe logging on server side without leaking details to response
        logger.error(f"Failed to convert DOCX file '{file_path}' to HTML: {exc}", exc_info=True)
        return False, None, "Preview is currently unavailable. Please download the document to view it."


def _resolve_document_file_path(doc) -> Optional[str]:
    """Resolves document file path with fallback to local generated_documents folder for cross-platform portability."""
    if not doc:
        return None
    fpath = doc.file_path
    if fpath and os.path.exists(fpath):
        return fpath
    basename = os.path.basename(fpath or doc.file_name or '')
    if basename:
        local_path = os.path.join(current_app.root_path, 'uploads', 'generated_documents', basename)
        if os.path.exists(local_path):
            return local_path
    return None


def get_application_offer_letter_preview(app_id: int) -> Dict[str, Any]:
    """
    Retrieves the generated Offer Letter document for the given JobApplication
    and converts it to an in-browser HTML preview payload.
    """
    application = db.session.get(JobApplication, app_id)
    if not application:
        return {
            'status': 'error',
            'error_code': 'NOT_FOUND',
            'message': 'Application record not found.'
        }

    offer_doc = application.offer_letter_doc
    fpath = _resolve_document_file_path(offer_doc)
    if not offer_doc or not fpath:
        return {
            'status': 'error',
            'error_code': 'DOC_NOT_GENERATED',
            'message': 'Offer Letter has not been generated for this application yet.'
        }

    success, html_content, err_msg = convert_docx_to_html(fpath)
    if not success or not html_content:
        return {
            'status': 'error',
            'error_code': 'CONVERSION_FAILED',
            'message': err_msg or "Preview is currently unavailable. Please download the document to view it.",
            'file_name': offer_doc.file_name,
            'download_url': f"/admin/applications/{app_id}/offer-letter/download"
        }

    return {
        'status': 'success',
        'document_type': 'offer_letter',
        'file_name': offer_doc.file_name,
        'candidate_name': application.full_name,
        'application_code': application.application_code or application.formatted_code,
        'html': html_content,
        'download_url': f"/admin/applications/{app_id}/offer-letter/download"
    }


def get_document_preview_by_id(doc_id: int) -> Dict[str, Any]:
    """
    Retrieves any EmployeeDocument by primary key ID and returns its HTML preview payload.
    Provides future support for Experience Letters, Completion Certificates, etc.
    """
    document = db.session.get(EmployeeDocument, doc_id)
    if not document or not document.file_path or not os.path.exists(document.file_path):
        return {
            'status': 'error',
            'error_code': 'NOT_FOUND',
            'message': 'Document file not found.'
        }

    success, html_content, err_msg = convert_docx_to_html(document.file_path)
    if not success or not html_content:
        return {
            'status': 'error',
            'error_code': 'CONVERSION_FAILED',
            'message': err_msg or "Preview is currently unavailable. Please download the document to view it.",
            'file_name': document.file_name
        }

    app_code = ''
    cand_name = ''
    if document.application:
        app_code = document.application.application_code or document.application.formatted_code
        cand_name = document.application.full_name
    elif document.employee and document.employee.application:
        app_code = document.employee.application.application_code or document.employee.application.formatted_code
        cand_name = document.employee.application.full_name

    return {
        'status': 'success',
        'document_type': document.document_type,
        'file_name': document.file_name,
        'candidate_name': cand_name,
        'application_code': app_code,
        'html': html_content
    }
