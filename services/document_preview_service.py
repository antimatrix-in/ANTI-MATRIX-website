import os
import re
import html
import base64
import logging
import shutil
import subprocess
import tempfile
import glob
from typing import Tuple, Optional, Dict, Any

from flask import current_app, url_for
from models import db, JobApplication, EmployeeDocument

logger = logging.getLogger('document_preview_service')

# In-memory LRU-like cache for converted document HTML (fallback): {file_path: (mtime, html_content)}
_DOCUMENT_PREVIEW_CACHE: Dict[str, Tuple[float, str]] = {}


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


def find_libreoffice_binary() -> Optional[str]:
    """
    Locates the LibreOffice executable across Windows and Linux environments.
    """
    # 1. Environment variable override
    env_path = os.environ.get('LIBREOFFICE_PATH')
    if env_path and os.path.isfile(env_path):
        return env_path

    # 2. System PATH lookup
    for cmd in ['soffice', 'libreoffice', 'soffice.exe', 'libreoffice.exe']:
        found = shutil.which(cmd)
        if found and os.path.isfile(found):
            return found

    # 3. Standard Windows locations
    windows_candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    # Check for versioned folders e.g. "C:\Program Files\LibreOffice 24\program\soffice.exe"
    windows_candidates.extend(glob.glob(r"C:\Program Files\LibreOffice*\program\soffice.exe"))
    windows_candidates.extend(glob.glob(r"C:\Program Files (x86)\LibreOffice*\program\soffice.exe"))
    local_app_data = os.environ.get('LOCALAPPDATA', '')
    if local_app_data:
        windows_candidates.append(os.path.join(local_app_data, 'Programs', 'LibreOffice', 'program', 'soffice.exe'))

    for cand in windows_candidates:
        if os.path.isfile(cand):
            return cand

    # 4. Standard Linux / Docker locations
    linux_candidates = [
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
        "/usr/local/bin/libreoffice",
        "/usr/local/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
    ]
    for cand in linux_candidates:
        if os.path.isfile(cand):
            return cand

    return None


def convert_docx_to_pdf(file_path: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Converts a candidate DOCX file to a PDF using LibreOffice headless.
    Maintains a cache of converted PDFs in uploads/preview_cache/ keyed by file modification time.
    Returns (success: bool, pdf_path: Optional[str], error_message: Optional[str]).
    """
    if not file_path or not os.path.exists(file_path):
        return False, None, "Document file not found on server storage."

    try:
        current_mtime = int(os.path.getmtime(file_path))
    except Exception as e:
        logger.error(f"Error checking file mtime for {file_path}: {e}")
        return False, None, "Unable to access document file."

    # Cache directory
    cache_dir = os.path.join(current_app.root_path, 'uploads', 'preview_cache')
    os.makedirs(cache_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(file_path))[0]
    cached_pdf_name = f"{base_name}_{current_mtime}.pdf"
    cached_pdf_path = os.path.join(cache_dir, cached_pdf_name)

    # Return cached PDF if present and valid
    if os.path.exists(cached_pdf_path) and os.path.getsize(cached_pdf_path) > 0:
        return True, cached_pdf_path, None

    # Locate LibreOffice
    soffice_bin = find_libreoffice_binary()
    if not soffice_bin:
        logger.error("LibreOffice binary not found. Headless PDF preview is unavailable.")
        return False, None, "Preview is temporarily unavailable. Please use Download DOCX."

    # Convert using LibreOffice headless in a temp outdir
    with tempfile.TemporaryDirectory() as temp_dir:
        cmd = [
            soffice_bin,
            '--headless',
            '--invisible',
            '--nodefault',
            '--nofirststartwizard',
            '--nolockcheck',
            '--nologo',
            '--convert-to',
            'pdf',
            '--outdir',
            temp_dir,
            file_path
        ]

        logger.info(f"Converting DOCX to PDF with LibreOffice: {cmd}")
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
            if res.returncode != 0:
                logger.error(f"LibreOffice conversion failed with code {res.returncode}: {res.stderr.decode('utf-8', errors='ignore')}")
                return False, None, "Preview is temporarily unavailable. Please use Download DOCX."

            # LibreOffice produces <base_name>.pdf in temp_dir
            generated_pdf = os.path.join(temp_dir, f"{base_name}.pdf")
            if not os.path.exists(generated_pdf) or os.path.getsize(generated_pdf) == 0:
                # Search for any PDF in temp_dir
                pdf_files = glob.glob(os.path.join(temp_dir, "*.pdf"))
                if pdf_files and os.path.getsize(pdf_files[0]) > 0:
                    generated_pdf = pdf_files[0]
                else:
                    logger.error(f"LibreOffice conversion did not produce a valid PDF file in {temp_dir}")
                    return False, None, "Preview is temporarily unavailable. Please use Download DOCX."

            # Move to cache destination
            shutil.copyfile(generated_pdf, cached_pdf_path)
            logger.info(f"Successfully generated and cached PDF preview: {cached_pdf_path}")
            return True, cached_pdf_path, None

        except subprocess.TimeoutExpired:
            logger.error("LibreOffice conversion timed out after 45 seconds.")
            return False, None, "Preview is temporarily unavailable. Please use Download DOCX."
        except Exception as exc:
            logger.error(f"Unexpected error during LibreOffice DOCX to PDF conversion: {exc}", exc_info=True)
            return False, None, "Preview is temporarily unavailable. Please use Download DOCX."


def get_application_offer_letter_preview(app_id: int) -> Dict[str, Any]:
    """
    Retrieves the generated Offer Letter document for the given JobApplication
    and prepares metadata for in-browser PDF preview.
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

    pdf_url = f"/admin/applications/{app_id}/offer-letter/preview/pdf"
    file_url = f"/admin/applications/{app_id}/offer-letter/preview/file"
    download_url = f"/admin/applications/{app_id}/offer-letter/download"

    return {
        'status': 'success',
        'document_type': 'offer_letter',
        'file_name': offer_doc.file_name,
        'candidate_name': application.full_name,
        'application_code': application.application_code or application.formatted_code,
        'pdf_url': pdf_url,
        'file_url': file_url,
        'download_url': download_url
    }


def get_document_preview_by_id(doc_id: int) -> Dict[str, Any]:
    """
    Retrieves any EmployeeDocument by primary key ID and returns its preview metadata.
    """
    document = db.session.get(EmployeeDocument, doc_id)
    if not document or not document.file_path or not os.path.exists(document.file_path):
        return {
            'status': 'error',
            'error_code': 'NOT_FOUND',
            'message': 'Document file not found.'
        }

    app_code = ''
    cand_name = ''
    if document.application:
        app_code = document.application.application_code or document.application.formatted_code
        cand_name = document.application.full_name
    elif document.employee and document.employee.application:
        app_code = document.employee.application.application_code or document.employee.application.formatted_code
        cand_name = document.employee.application.full_name

    pdf_url = f"/admin/documents/{doc_id}/preview/pdf"
    file_url = f"/admin/documents/{doc_id}/preview/file"

    return {
        'status': 'success',
        'document_type': document.document_type,
        'file_name': document.file_name,
        'candidate_name': cand_name,
        'application_code': app_code,
        'pdf_url': pdf_url,
        'file_url': file_url
    }


def convert_docx_to_html(file_path: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Fallback server-side converter using mammoth if HTML format is explicitly requested.
    """
    if not file_path or not os.path.exists(file_path):
        return False, None, "Document file not found on server storage."

    try:
        current_mtime = os.path.getmtime(file_path)
    except Exception as e:
        logger.error(f"Error checking file mtime for {file_path}: {e}")
        return False, None, "Unable to access document file."

    cached = _DOCUMENT_PREVIEW_CACHE.get(file_path)
    if cached and cached[0] == current_mtime:
        return True, cached[1], None

    try:
        import mammoth

        with open(file_path, 'rb') as docx_file:
            result = mammoth.convert_to_html(docx_file)
            raw_html = result.value or ''

        processed_html = raw_html.strip()
        if not processed_html:
            processed_html = "<p style='color: #64748b; font-style: italic;'>Document content is empty.</p>"

        _DOCUMENT_PREVIEW_CACHE[file_path] = (current_mtime, processed_html)
        return True, processed_html, None

    except Exception as exc:
        logger.error(f"Failed to convert DOCX file '{file_path}' to HTML: {exc}", exc_info=True)
        return False, None, "Preview is currently unavailable. Please download the document to view it."
