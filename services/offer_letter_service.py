import os
import shutil
import smtplib
import uuid
import time
import zipfile
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timezone, timedelta
import docx
from flask import current_app
from models import db, Employee, JobApplication, JobPosting, EmployeeDocument, DocumentTemplate, EmailTemplate


# OpenXML Namespaces
W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
w_p = f'{{{W_NS}}}p'
w_t = f'{{{W_NS}}}t'
space_attr = f'{{{XML_NS}}}space'

# Common OpenXML namespaces for ElementTree registration to avoid synthetic prefixes
OPENXML_NAMESPACES = {
    'w': W_NS,
    'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
    'w14': 'http://schemas.microsoft.com/office/word/2010/wordml',
    'w15': 'http://schemas.microsoft.com/office/word/2012/wordml',
    'w16': 'http://schemas.microsoft.com/office/word/2018/wordml',
    'w16cex': 'http://schemas.microsoft.com/office/word/2018/wordml/cex',
    'w16cid': 'http://schemas.microsoft.com/office/word/2016/wordml/cid',
    'w16se': 'http://schemas.microsoft.com/office/word/2015/wordml/symex',
    'v': 'urn:schemas-microsoft-com:vml',
    'o': 'urn:schemas-microsoft-com:office:office',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
    'dgm': 'http://schemas.openxmlformats.org/drawingml/2006/diagram',
}


OFFER_LETTER_CATEGORIES = {
    'AI_ML': {
        'type': 'offer_letter_ai_ml',
        'name': 'AI & ML Internship Offer Letter',
        'card_title': 'AI & ML Internship',
        'default_title': 'AI & ML Intern',
        'default_filename': 'offer_letter_ai_ml_master.docx',
        'badge': 'AI & ML Domain',
        'run0': 'During your internship, you will work on a ',
        'run1': 'real-time project',
        'run2': ' and gain practical experience in Artificial Intelligence and Machine Learning, including data processing, model development, training, testing, evaluation, and implementation.',
        'keywords': [
            'ai & ml', 'ai/ml', 'artificial intelligence', 'machine learning',
            'deep learning', 'data science', 'ai research', 'computer vision',
            'nlp', 'natural language processing', 'ai intern', 'ml intern', 'ai', 'ml'
        ]
    },
    'WEB_DEVELOPMENT': {
        'type': 'offer_letter_web_development',
        'name': 'Web Development Internship Offer Letter',
        'card_title': 'Web Development Internship',
        'default_title': 'Web Development Intern',
        'default_filename': 'offer_letter_web_development_master.docx',
        'badge': 'Web Dev Domain',
        'run0': 'During your internship, you will work on a ',
        'run1': 'real-time web development project',
        'run2': ' and gain practical experience in building responsive web applications, working with frontend and backend technologies, database integration, APIs, testing, and deployment.',
        'keywords': [
            'web development', 'web developer', 'frontend', 'front-end', 'front end',
            'backend', 'back-end', 'back end', 'full stack', 'fullstack', 'full-stack',
            'html', 'css', 'javascript', 'react', 'node', 'vue', 'angular',
            'flask', 'django', 'php', 'web intern', 'web'
        ]
    },
    'APP_DEVELOPMENT': {
        'type': 'offer_letter_app_development',
        'name': 'App Development Internship Offer Letter',
        'card_title': 'App Development Internship',
        'default_title': 'App Development Intern',
        'default_filename': 'offer_letter_app_development_master.docx',
        'badge': 'App Dev Domain',
        'run0': 'During your internship, you will work on a ',
        'run1': 'real-time application development project',
        'run2': ' and gain practical experience in designing and developing mobile applications, implementing user interfaces, integrating APIs and databases, testing, debugging, and preparing applications for deployment.',
        'keywords': [
            'app development', 'app developer', 'mobile application', 'mobile app',
            'mobile developer', 'android', 'ios', 'flutter', 'react native',
            'swift', 'kotlin', 'app intern', 'mobile intern', 'app'
        ]
    },
    'DATA_ANALYTICS': {
        'type': 'offer_letter_data_analytics',
        'name': 'Data Analytics Internship Offer Letter',
        'card_title': 'Data Analytics Internship',
        'default_title': 'Data Analytics Intern',
        'default_filename': 'offer_letter_data_analytics_master.docx',
        'badge': 'Data Analytics Domain',
        'run0': 'During your internship, you will work on a ',
        'run1': 'real-time data analytics project',
        'run2': ' and gain practical experience in data collection, cleaning, preprocessing, analysis, visualization, reporting, and deriving meaningful insights from data.',
        'keywords': [
            'data analytics', 'data analyst', 'business intelligence', 'bi analyst',
            'power bi', 'powerbi', 'tableau', 'data visualization', 'data analysis',
            'sql analyst', 'analytics intern', 'analytics'
        ]
    }
}


def determine_job_category(job_or_title_or_dept):
    """
    Determines the matching internship category key ('AI_ML', 'WEB_DEVELOPMENT', 'APP_DEVELOPMENT', 'DATA_ANALYTICS')
    from a JobPosting object, title string, or department string.
    Returns None if no supported category matches.
    """
    if not job_or_title_or_dept:
        return None

    if isinstance(job_or_title_or_dept, str):
        text = job_or_title_or_dept.strip().lower()
    elif isinstance(job_or_title_or_dept, JobPosting):
        job = job_or_title_or_dept
        # Check explicit category attribute if present
        if hasattr(job, 'category') and job.category:
            cat_upper = str(job.category).upper()
            if cat_upper in OFFER_LETTER_CATEGORIES:
                return cat_upper
        # Combine title, department, skills, short_description
        parts = [
            job.title or '',
            job.department or '',
            getattr(job, 'skills', '') or '',
            getattr(job, 'short_description', '') or ''
        ]
        text = " ".join(parts).lower()
    else:
        text = str(job_or_title_or_dept).lower()

    # Step 1: Check multi-word / specific keyword matches in priority order
    for cat_key in ['DATA_ANALYTICS', 'AI_ML', 'APP_DEVELOPMENT', 'WEB_DEVELOPMENT']:
        cat_info = OFFER_LETTER_CATEGORIES[cat_key]
        for kw in cat_info['keywords']:
            # For multi-word keywords (e.g. "data analytics", "web development", "mobile app")
            if ' ' in kw or '/' in kw or '-' in kw or '&' in kw:
                if kw in text:
                    return cat_key

    # Step 2: Check word tokens / single-word keywords
    words = set(text.replace('/', ' ').replace('-', ' ').replace('&', ' ').replace(',', ' ').split())
    for cat_key in ['DATA_ANALYTICS', 'AI_ML', 'APP_DEVELOPMENT', 'WEB_DEVELOPMENT']:
        cat_info = OFFER_LETTER_CATEGORIES[cat_key]
        for kw in cat_info['keywords']:
            if kw in words or kw in text:
                return cat_key

    return None


def replace_placeholders_in_xml(xml_bytes, replacements):
    """
    Safely replaces placeholder keys in OpenXML document parts (e.g. word/document.xml, header, footer).
    Preserves exact font, size, bold, italic, underline, color, borders, and run properties.
    Handles placeholders that span multiple XML <w:r><w:t> runs without altering surrounding styling.
    """
    for prefix, uri in OPENXML_NAMESPACES.items():
        ET.register_namespace(prefix, uri)

    root = ET.fromstring(xml_bytes)

    # Process all paragraphs across the entire XML hierarchy (body, tables, textboxes, headers, footers)
    for p in root.iter(w_p):
        t_elems = list(p.iter(w_t))
        if not t_elems:
            continue

        for ph, repl in replacements.items():
            if not ph:
                continue
            repl_str = str(repl) if repl is not None else ''

            # Continue finding & replacing occurrences within the paragraph
            while True:
                full_text = ''.join(e.text or '' for e in t_elems)
                start_idx = full_text.find(ph)
                if start_idx == -1:
                    break
                end_idx = start_idx + len(ph)

                curr_pos = 0
                for e in t_elems:
                    txt = e.text or ''
                    l = len(txt)
                    e_start = curr_pos
                    e_end = curr_pos + l

                    if e_end <= start_idx:
                        # Before the match
                        pass
                    elif e_start >= end_idx:
                        # After the match
                        pass
                    elif e_start <= start_idx and e_end >= end_idx:
                        # Entire placeholder inside this single run
                        l_start = start_idx - e_start
                        l_end = end_idx - e_start
                        e.text = txt[:l_start] + repl_str + txt[l_end:]
                        if e.text.startswith(' ') or e.text.endswith(' '):
                            e.set(space_attr, 'preserve')
                        break
                    elif e_start <= start_idx and e_end < end_idx:
                        # Match starts in this run and spans next runs
                        l_start = start_idx - e_start
                        e.text = txt[:l_start] + repl_str
                        if e.text.startswith(' ') or e.text.endswith(' '):
                            e.set(space_attr, 'preserve')
                    elif e_start > start_idx and e_end <= end_idx:
                        # Fully consumed intermediate run
                        e.text = ''
                    elif e_start < end_idx and e_end >= end_idx:
                        # Match ends in this run
                        l_end = end_idx - e_start
                        e.text = txt[l_end:]
                        if e.text.startswith(' ') or e.text.endswith(' '):
                            e.set(space_attr, 'preserve')

                    curr_pos += l

    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def populate_docx_from_master_template(master_template_path, output_filepath, placeholder_mapping):
    """
    Creates an exact copy of the uploaded master DOCX package at output_filepath,
    and replaces ONLY approved placeholders in the document XML (word/document.xml, word/header*.xml, word/footer*.xml).
    
    CRITICAL:
    - Master DOCX package is the source of truth.
    - 100% of all images, logos, circular seals, MSME visual, green border, line dividers,
      watermarks, headers, footers, styles, fonts, and page layouts are preserved byte-for-byte.
    - Master template file on disk is NEVER modified.
    """
    if not os.path.exists(master_template_path):
        raise FileNotFoundError(f"Master template file not found at: {master_template_path}")

    xml_targets = set()
    file_contents = {}

    with zipfile.ZipFile(master_template_path, 'r') as src_zip:
        for name in src_zip.namelist():
            if name == 'word/document.xml' or \
               (name.startswith('word/header') and name.endswith('.xml')) or \
               (name.startswith('word/footer') and name.endswith('.xml')) or \
               (name.startswith('word/footnotes') and name.endswith('.xml')) or \
               (name.startswith('word/endnotes') and name.endswith('.xml')):
                xml_targets.add(name)
            file_contents[name] = src_zip.read(name)

    # Replace placeholders in relevant XML parts
    for target_name in xml_targets:
        if target_name in file_contents:
            file_contents[target_name] = replace_placeholders_in_xml(
                file_contents[target_name],
                placeholder_mapping
            )

    # Write output candidate-specific DOCX package
    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)
    with zipfile.ZipFile(output_filepath, 'w', compression=zipfile.ZIP_DEFLATED) as dst_zip:
        for name, data in file_contents.items():
            dst_zip.writestr(name, data)


def replace_placeholders_in_paragraph(paragraph, mapping):
    """
    Safely replaces placeholder keys with replacement values in a docx Paragraph.
    Preserves exact font, size, bold, italic, color, and run-level styles.
    Handles placeholders both inside individual runs and spanning multiple runs.
    """
    full_text = paragraph.text
    if not full_text:
        return

    # Check if any placeholder exists in the paragraph text
    needs_replacement = any(key in full_text for key in mapping)
    if not needs_replacement:
        return

    for key, val in mapping.items():
        if key not in paragraph.text:
            continue

        str_val = str(val) if val is not None else ''

        # 1. First attempt: check if placeholder is contained entirely in a single run
        replaced_in_single_run = False
        for run in paragraph.runs:
            if key in run.text:
                run.text = run.text.replace(key, str_val)
                replaced_in_single_run = True

        # 2. Fallback: if placeholder spans multiple adjacent runs
        if not replaced_in_single_run and key in paragraph.text:
            combined = "".join([r.text for r in paragraph.runs])
            new_text = combined.replace(key, str_val)
            if paragraph.runs:
                paragraph.runs[0].text = new_text
                for r in paragraph.runs[1:]:
                    r.text = ""


class OfferLetterTemplateNotFoundError(Exception):
    """Raised when no active Offer Letter template record exists in the database for the required category."""
    pass


class OfferLetterTemplateFileMissingError(Exception):
    """Raised when the active Offer Letter template record exists in DB, but the physical file is missing from disk/storage."""
    pass


def get_active_offer_letter_template(category_or_job=None):
    """
    Retrieves the active Offer Letter DocumentTemplate record from the database for the specified category or job.
    If category_or_job is None, defaults to 'AI_ML' (with backward compatibility for 'offer_letter').
    Strictly queries the database for an active template and validates that its stored file exists.
    """
    if category_or_job is None:
        cat_key = 'AI_ML'
    elif isinstance(category_or_job, str):
        if category_or_job.upper() in OFFER_LETTER_CATEGORIES:
            cat_key = category_or_job.upper()
        else:
            # Check if it is a template_type string directly (e.g. 'offer_letter_web_development')
            matched_key = None
            for k, info in OFFER_LETTER_CATEGORIES.items():
                if info['type'] == category_or_job:
                    matched_key = k
                    break
            if matched_key:
                cat_key = matched_key
            else:
                cat_key = determine_job_category(category_or_job)
    elif isinstance(category_or_job, JobPosting):
        cat_key = determine_job_category(category_or_job)
    elif isinstance(category_or_job, (JobApplication, Employee)):
        job = category_or_job.job if hasattr(category_or_job, 'job') else None
        cat_key = determine_job_category(job) if job else None
    else:
        cat_key = None

    if not cat_key or cat_key not in OFFER_LETTER_CATEGORIES:
        raise OfferLetterTemplateNotFoundError(
            "No job-specific offer letter template is available for this internship. Please upload the appropriate template before generating the offer letter."
        )

    cat_info = OFFER_LETTER_CATEGORIES[cat_key]
    template_type = cat_info['type']

    # Query active template for this specific category
    active_template = DocumentTemplate.query.filter_by(
        template_type=template_type,
        is_active=True
    ).order_by(DocumentTemplate.id.desc()).first()

    # Backward compatibility for AI_ML category if offer_letter_ai_ml is not yet uploaded
    if not active_template and cat_key == 'AI_ML':
        active_template = DocumentTemplate.query.filter_by(
            template_type='offer_letter',
            is_active=True
        ).order_by(DocumentTemplate.id.desc()).first()

    if not active_template:
        raise OfferLetterTemplateNotFoundError(
            f"No active template found for {cat_info['card_title']}. Please upload the template from Admin Dashboard → Templates."
        )

    if not active_template.file_path or not os.path.exists(active_template.file_path):
        # Fallback to local filename in uploads/templates or static/default_templates
        candidate_paths = [
            os.path.join(current_app.root_path, 'uploads', 'templates', os.path.basename(active_template.file_path or active_template.filename or '')),
            os.path.join(current_app.root_path, 'uploads', 'templates', cat_info['default_filename']),
            os.path.join(current_app.root_path, 'static', 'default_templates', cat_info['default_filename']),
            os.path.join(current_app.root_path, 'uploads', 'templates', 'offer letter (Anti-matrix).docx'),
            os.path.join(current_app.root_path, 'uploads', 'templates', 'offer_letter_master.docx'),
        ]
        found = False
        for cpath in candidate_paths:
            if cpath and os.path.exists(cpath):
                active_template.file_path = cpath
                found = True
                break
        if not found:
            raise OfferLetterTemplateFileMissingError(
                f"The active template file for {cat_info['card_title']} could not be found at '{active_template.file_path}'. Please upload the template again."
            )

    return active_template


def ensure_default_templates_initialized():
    """
    Ensures that default master DOCX files for all 4 internship categories exist in uploads/templates/
    and have corresponding active DocumentTemplate records in the database without altering existing data.
    """
    templates_dir = os.path.join(current_app.root_path, 'uploads', 'templates')
    os.makedirs(templates_dir, exist_ok=True)

    static_defaults_dir = os.path.join(current_app.root_path, 'static', 'default_templates')
    master_ref = os.path.join(templates_dir, 'offer letter (Anti-matrix).docx')
    if not os.path.exists(master_ref):
        alt_ref = os.path.join(templates_dir, 'offer_letter_master.docx')
        if os.path.exists(alt_ref):
            master_ref = alt_ref

    for cat_key, cat_data in OFFER_LETTER_CATEGORIES.items():
        target_path = os.path.join(templates_dir, cat_data['default_filename'])
        static_src = os.path.join(static_defaults_dir, cat_data['default_filename'])
        
        # 1. Create file if missing
        if not os.path.exists(target_path):
            if os.path.exists(static_src):
                shutil.copy2(static_src, target_path)
            elif os.path.exists(master_ref):
                shutil.copy2(master_ref, target_path)

        # 2. Check / insert active DocumentTemplate record in DB
        tmpl_record = DocumentTemplate.query.filter_by(
            template_type=cat_data['type'],
            is_active=True
        ).first()

        if not tmpl_record and os.path.exists(target_path):
            new_tmpl = DocumentTemplate(
                template_type=cat_data['type'],
                name=cat_data['name'],
                filename=cat_data['default_filename'],
                file_path=target_path,
                is_active=True
            )
            db.session.add(new_tmpl)

    db.session.commit()


def generate_offer_letter_docx(application_or_employee, custom_params=None, force_regenerate=False):
    """
    Generates a personalized candidate Offer Letter DOCX by copying the active master template DOCX
    and replacing ONLY the approved placeholders in the OpenXML parts.
    
    CRITICAL IMPLEMENTATION GUARANTEES:
    1. The master template DOCX is the authoritative source of truth.
    2. The document is NOT rebuilt from scratch.
    3. The layout, headers, footers, logo, watermark, circular seal, MSME visuals, borders, fonts, and styles are 100% preserved.
    4. Only approved dynamic values are substituted:
       - Date: [DD/MM/YYYY] -> candidate offer date (DD/MM/YYYY)
       - Candidate Name: [Candidate Name] -> candidate's actual name
       - Reference Number: [Reference Number] -> existing Application ID (e.g. AM-APP-000156)
       - Duration: [1 Month / 3 Months] -> candidate's actual selected internship duration
       - Joining Date: [Joining Date] -> candidate's actual joining date
    5. The master template on disk is NEVER modified.
    6. Returns (emp_doc, output_filepath).
    """
    if isinstance(application_or_employee, Employee):
        employee = application_or_employee
        app = employee.application
    elif isinstance(application_or_employee, JobApplication):
        app = application_or_employee
        employee = app.employee
    else:
        raise ValueError("Invalid application or employee record provided.")

    if not app:
        raise ValueError("Candidate application record is missing.")

    job = app.job
    if not job:
        raise ValueError(f"Application {app.formatted_code} is missing associated Job Posting.")

    # Determine job-specific category
    cat_key = determine_job_category(job)
    if not cat_key:
        raise OfferLetterTemplateNotFoundError(
            "No job-specific offer letter template is available for this internship. Please upload the appropriate template before generating the offer letter."
        )

    # Idempotency check: If document already exists and file exists, return it unless force_regenerate=True
    existing_doc = app.offer_letter_doc
    if existing_doc and existing_doc.file_path and os.path.exists(existing_doc.file_path) and not force_regenerate:
        return existing_doc, existing_doc.file_path

    # Retrieve active master template for this specific category
    active_template = get_active_offer_letter_template(cat_key)

    custom_params = custom_params or {}
    now_utc = datetime.now(timezone.utc)
    current_date_str = now_utc.strftime("%d/%m/%Y")

    # Format data strictly from DB models
    candidate_name = (app.full_name or (employee.candidate_name if employee else "Candidate")).strip()
    reference_number = app.formatted_code
    internship_duration = app.duration_display or (f"{job.duration.replace('_', ' ').title()}" if job.duration else "1 Month")

    # Joining date
    joining_date = (custom_params.get('joining_date') or custom_params.get('start_date') or app.joining_date or "Immediate / As mutually agreed").strip()

    # Strict allowlist of replaceable placeholders
    placeholder_mapping = {
        # 1. Date
        '[DD/MM/YYYY]': current_date_str,
        '[Date]': current_date_str,
        '{{offer_date}}': current_date_str,
        '{{Date}}': current_date_str,
        '{{date}}': current_date_str,

        # 2. Candidate Name
        '[Candidate Name]': candidate_name,
        '[Candidate\'s Name]': candidate_name,
        '{{Candidate Name}}': candidate_name,
        '{{candidate_name}}': candidate_name,
        '{{employee_name}}': candidate_name,

        # 3. Reference Number / Application ID
        '[Reference Number]': reference_number,
        '[Application ID]': reference_number,
        '{{Reference Number}}': reference_number,
        '{{reference_number}}': reference_number,
        '{{Application ID}}': reference_number,
        '{{application_id}}': reference_number,

        # 4. Duration
        '[1 Month / 3 Months]': internship_duration,
        '[Internship Duration]': internship_duration,
        '{{1 Month / 3 Months}}': internship_duration,
        '{{internship_duration}}': internship_duration,
        '{{Internship Duration}}': internship_duration,

        # 5. Joining Date
        '[Joining Date]': joining_date,
        '[Start Date]': joining_date,
        '{{Joining Date}}': joining_date,
        '{{joining_date}}': joining_date,
        '{{Start Date}}': joining_date,
        '{{start_date}}': joining_date,
    }

    # Destination output path
    gen_dir = os.path.join(current_app.root_path, 'uploads', 'generated_documents')
    os.makedirs(gen_dir, exist_ok=True)

    output_filename = f"{app.formatted_code}_Offer_Letter.docx"
    output_filepath = os.path.join(gen_dir, output_filename)

    # Copy master DOCX package and replace ONLY approved placeholders in XML
    populate_docx_from_master_template(
        active_template.file_path,
        output_filepath,
        placeholder_mapping
    )

    # Create or update EmployeeDocument record in DB
    emp_doc = EmployeeDocument.query.filter_by(
        application_id=app.id,
        document_type='offer_letter'
    ).first()

    if not emp_doc and employee:
        emp_doc = EmployeeDocument.query.filter_by(
            employee_id=employee.id,
            document_type='offer_letter'
        ).first()

    if not emp_doc:
        emp_doc = EmployeeDocument(
            application_id=app.id,
            employee_id=employee.id if employee else None,
            template_id=active_template.id,
            document_type='offer_letter',
            file_name=output_filename,
            file_path=output_filepath,
            status='GENERATED',
            email_status='not_sent',
            generated_at=now_utc
        )
        db.session.add(emp_doc)
    else:
        emp_doc.application_id = app.id
        if employee:
            emp_doc.employee_id = employee.id
        emp_doc.template_id = active_template.id
        emp_doc.file_name = output_filename
        emp_doc.file_path = output_filepath
        emp_doc.status = 'GENERATED'
        emp_doc.generated_at = now_utc

    db.session.commit()
    return emp_doc, output_filepath


def send_offer_letter_email(application_or_employee, start_date=None):
    """
    Sends the generated Offer Letter to the candidate's registered email with attachment.
    Enforces strict ONE-TIME send protection, Markdown-to-HTML rendering, and audit logging.
    """
    from services.email_service import send_offer_letter_shortlisted_email
    return send_offer_letter_shortlisted_email(application_or_employee, start_date=start_date)
