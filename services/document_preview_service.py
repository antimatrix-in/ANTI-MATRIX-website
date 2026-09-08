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

from models import db, JobApplication, EmployeeDocument

logger = logging.getLogger('document_preview_service')

# In-memory LRU-like cache for converted document HTML (fallback): {file_path: (mtime, html_content)}
_DOCUMENT_PREVIEW_CACHE: Dict[str, Tuple[float, str]] = {}


def _get_root_path() -> str:
    """Safely retrieves the application root path, even when outside Flask request/app context."""
    try:
        from flask import current_app
        if current_app:
            return current_app.root_path
    except Exception:
        pass
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _resolve_document_file_path(doc) -> Optional[str]:
    """Resolves document file path with fallback to local generated_documents folder for cross-platform portability."""
    if not doc:
        return None
    fpath = getattr(doc, 'file_path', None) or (str(doc) if isinstance(doc, str) else None)
    if fpath and os.path.exists(fpath):
        return os.path.abspath(fpath)
    basename = os.path.basename(fpath or getattr(doc, 'file_name', None) or '')
    if basename:
        root_path = _get_root_path()
        candidates = [
            os.path.join(root_path, 'uploads', 'generated_documents', basename),
            os.path.join(root_path, 'uploads', 'documents', basename),
            os.path.join(root_path, 'uploads', 'templates', basename),
            os.path.join(root_path, 'static', 'default_templates', basename),
        ]
        for cand in candidates:
            if os.path.exists(cand):
                return os.path.abspath(cand)
    return None


def find_libreoffice_binary() -> Optional[str]:
    """
    Locates the LibreOffice executable across Windows, Linux, and custom environments.
    """
    # 1. Environment variable override
    env_path = os.environ.get('LIBREOFFICE_PATH')
    if env_path and os.path.isfile(env_path):
        return os.path.abspath(env_path)

    # 2. System PATH lookup
    for cmd in ['soffice', 'libreoffice', 'soffice.exe', 'libreoffice.exe']:
        found = shutil.which(cmd)
        if found and os.path.isfile(found):
            return os.path.abspath(found)

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
            return os.path.abspath(cand)

    # 4. Standard Linux / Render / Docker locations
    linux_candidates = [
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
        "/usr/local/bin/libreoffice",
        "/usr/local/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
    ]
    linux_candidates.extend(glob.glob("/opt/libreoffice*/program/soffice"))
    linux_candidates.extend(glob.glob("/usr/lib/libreoffice*/program/soffice"))

    for cand in linux_candidates:
        if os.path.isfile(cand):
            return os.path.abspath(cand)

    return None


def convert_docx_to_pdf(file_path: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Converts a candidate DOCX file to a PDF using LibreOffice headless.
    Maintains a cache of converted PDFs in uploads/preview_cache/ keyed by file modification time.
    Returns (success: bool, pdf_path: Optional[str], error_message: Optional[str]).

    Diagnostic logging captures every failure point:
    - LibreOffice binary path (found or NOT FOUND)
    - DOCX file path and size
    - Subprocess returncode, stdout, stderr
    - Temp directory path and output PDF existence/size
    - Conversion wall-clock duration
    No credentials are ever logged.
    """
    import time as _time

    if not file_path:
        logger.error("PDF_CONVERSION_FAILED | Reason: convert_docx_to_pdf called with empty file_path.")
        return False, None, "Document file not found on server storage."

    # If direct path does not exist, resolve via _resolve_document_file_path
    if not os.path.exists(file_path):
        resolved = _resolve_document_file_path(file_path)
        if resolved and os.path.exists(resolved):
            file_path = resolved
        else:
            logger.error(
                f"PDF_CONVERSION_FAILED | Reason: DOCX not found | "
                f"Attempted path: '{file_path}'"
            )
            return False, None, "Document file not found on server storage."

    abs_file_path = os.path.abspath(file_path)

    try:
        file_size = os.path.getsize(abs_file_path)
        if file_size == 0:
            logger.error(
                f"PDF_CONVERSION_FAILED | Reason: DOCX is empty (0 bytes) | "
                f"Path: '{abs_file_path}'"
            )
            return False, None, "Document file is corrupted or empty."
        current_mtime = int(os.path.getmtime(abs_file_path))
    except Exception as e:
        logger.error(
            f"PDF_CONVERSION_FAILED | Reason: Cannot stat DOCX file | "
            f"Path: '{abs_file_path}' | Error: {e}"
        )
        return False, None, "Unable to access document file on server storage."

    # Cache directory
    root_path = _get_root_path()
    cache_dir = os.path.join(root_path, 'uploads', 'preview_cache')
    os.makedirs(cache_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(abs_file_path))[0]
    cached_pdf_name = f"{base_name}_{current_mtime}.pdf"
    cached_pdf_path = os.path.join(cache_dir, cached_pdf_name)

    # Return cached PDF if present, non-empty, and valid
    if os.path.exists(cached_pdf_path) and os.path.getsize(cached_pdf_path) > 1000:
        try:
            with open(cached_pdf_path, 'rb') as f:
                header = f.read(5)
            if header.startswith(b'%PDF-'):
                logger.info(
                    f"PDF_CONVERSION_CACHE_HIT | "
                    f"File: {os.path.basename(abs_file_path)} | "
                    f"Cached PDF: {cached_pdf_path} ({os.path.getsize(cached_pdf_path)} bytes)"
                )
                return True, cached_pdf_path, None
        except Exception as e:
            logger.warning(
                f"Cached PDF validation error for {cached_pdf_path}: {e}. Re-converting."
            )

    # Locate LibreOffice binary — log all searched paths on failure
    soffice_bin = find_libreoffice_binary()
    if not soffice_bin:
        # Log the full list of paths that were searched so the issue is diagnosable from logs
        searched = [
            os.environ.get('LIBREOFFICE_PATH', '(LIBREOFFICE_PATH not set)'),
            '/usr/bin/libreoffice', '/usr/bin/soffice',
            '/usr/local/bin/libreoffice', '/usr/local/bin/soffice',
            '/usr/lib/libreoffice/program/soffice',
            'C:\\Program Files\\LibreOffice\\program\\soffice.exe',
        ]
        logger.error(
            f"PDF_CONVERSION_FAILED | Reason: LibreOffice binary NOT FOUND | "
            f"Searched paths include: {searched} | "
            f"DOCX: '{abs_file_path}' ({file_size} bytes) | "
            f"Hint: Ensure LibreOffice headless is installed in the deployment environment "
            f"(Dockerfile: apt-get install libreoffice-writer-nogui)"
        )
        return False, None, "Offer Letter PDF could not be generated. LibreOffice is not available on the server."

    # Convert using LibreOffice headless in an isolated temporary environment
    temp_dir = tempfile.mkdtemp(prefix='antimatrix_lo_')
    conversion_start = _time.monotonic()

    try:
        temp_outdir = os.path.join(temp_dir, 'out')
        profile_dir = os.path.join(temp_dir, 'profile')
        os.makedirs(temp_outdir, exist_ok=True)
        os.makedirs(profile_dir, exist_ok=True)

        # Isolated user profile URI to avoid lock collisions under concurrent requests
        profile_uri = f"file:///{profile_dir.replace(os.sep, '/')}".replace('file:////', 'file:///')

        cmd = [
            soffice_bin,
            f"-env:UserInstallation={profile_uri}",
            '--headless',
            '--invisible',
            '--nodefault',
            '--nofirststartwizard',
            '--nolockcheck',
            '--nologo',
            '--norestore',
            '--convert-to',
            'pdf:writer_pdf_Export',
            '--outdir',
            temp_outdir,
            abs_file_path
        ]

        # Windows-specific: suppress console window popup
        extra_kwargs = {}
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            extra_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

        logger.info(
            f"PDF_CONVERSION_START | "
            f"File: {os.path.basename(abs_file_path)} ({file_size} bytes) | "
            f"LibreOffice: {soffice_bin} | "
            f"TempDir: {temp_dir} | OutDir: {temp_outdir}"
        )

        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, **extra_kwargs
        )

        conversion_duration = _time.monotonic() - conversion_start
        stdout_text = res.stdout.decode('utf-8', errors='ignore').strip()
        stderr_text = res.stderr.decode('utf-8', errors='ignore').strip()

        if res.returncode != 0:
            logger.error(
                f"PDF_CONVERSION_FAILED | Reason: LibreOffice exited with non-zero code | "
                f"ReturnCode: {res.returncode} | "
                f"Duration: {conversion_duration:.2f}s | "
                f"DOCX: '{abs_file_path}' ({file_size} bytes) | "
                f"LibreOffice: '{soffice_bin}' | "
                f"TempDir: '{temp_dir}' | "
                f"Stdout: {stdout_text[:500] if stdout_text else '(empty)'} | "
                f"Stderr: {stderr_text[:1000] if stderr_text else '(empty)'}"
            )
            return False, None, "Offer Letter PDF could not be generated. Please try again or use Download DOCX."

        # Search for the output PDF in temp_outdir
        generated_pdf = os.path.join(temp_outdir, f"{base_name}.pdf")
        if not os.path.exists(generated_pdf) or os.path.getsize(generated_pdf) == 0:
            pdf_files = glob.glob(os.path.join(temp_outdir, "*.pdf"))
            if pdf_files and os.path.getsize(pdf_files[0]) > 0:
                generated_pdf = pdf_files[0]
            else:
                output_dir_contents = os.listdir(temp_outdir) if os.path.exists(temp_outdir) else []
                logger.error(
                    f"PDF_CONVERSION_FAILED | Reason: LibreOffice exited 0 but no PDF produced | "
                    f"ReturnCode: {res.returncode} | "
                    f"Duration: {conversion_duration:.2f}s | "
                    f"DOCX: '{abs_file_path}' ({file_size} bytes) | "
                    f"ExpectedPDF: '{generated_pdf}' | "
                    f"OutDirContents: {output_dir_contents} | "
                    f"Stdout: {stdout_text[:500] if stdout_text else '(empty)'} | "
                    f"Stderr: {stderr_text[:500] if stderr_text else '(empty)'}"
                )
                return False, None, "Offer Letter PDF could not be generated. Please try again or use Download DOCX."

        # Verify generated PDF magic bytes (%PDF-)
        with open(generated_pdf, 'rb') as f:
            pdf_head = f.read(5)
        if not pdf_head.startswith(b'%PDF-'):
            pdf_size = os.path.getsize(generated_pdf)
            logger.error(
                f"PDF_CONVERSION_FAILED | Reason: Output file does not start with %PDF- | "
                f"File: '{generated_pdf}' ({pdf_size} bytes) | "
                f"FirstBytes: {pdf_head!r} | "
                f"DOCX: '{abs_file_path}' ({file_size} bytes)"
            )
            return False, None, "Offer Letter PDF could not be generated (invalid output). Please use Download DOCX."

        pdf_size = os.path.getsize(generated_pdf)

        # Copy validated PDF to cache path
        shutil.copyfile(generated_pdf, cached_pdf_path)
        final_duration = _time.monotonic() - conversion_start
        logger.info(
            f"PDF_CONVERSION_SUCCESS | "
            f"File: {os.path.basename(abs_file_path)} ({file_size} bytes) | "
            f"PDF: {cached_pdf_path} ({os.path.getsize(cached_pdf_path)} bytes) | "
            f"Duration: {final_duration:.2f}s"
        )
        return True, cached_pdf_path, None

    except subprocess.TimeoutExpired:
        duration = _time.monotonic() - conversion_start
        logger.error(
            f"PDF_CONVERSION_FAILED | Reason: LibreOffice timed out after 60s | "
            f"DOCX: '{abs_file_path}' ({file_size} bytes) | "
            f"LibreOffice: '{soffice_bin}' | "
            f"Duration: {duration:.2f}s"
        )
        return False, None, "Offer Letter PDF could not be generated (conversion timed out). Please try again."
    except Exception as exc:
        duration = _time.monotonic() - conversion_start
        logger.error(
            f"PDF_CONVERSION_FAILED | Reason: Unexpected exception | "
            f"Error: {exc} | "
            f"DOCX: '{abs_file_path}' ({file_size} bytes) | "
            f"LibreOffice: '{soffice_bin}' | "
            f"Duration: {duration:.2f}s",
            exc_info=True
        )
        return False, None, "Offer Letter PDF could not be generated. Please try again or use Download DOCX."
    finally:
        # Clean up temporary directory
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


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
