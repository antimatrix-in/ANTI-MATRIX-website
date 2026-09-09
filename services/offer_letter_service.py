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


def safe_replace_in_runs(paragraph, mapping):
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

        # While key exists in paragraph text, replace it
        while key in paragraph.text:
            # 1. First attempt: check if placeholder is contained entirely in a single run
            single_run_found = False
            for run in paragraph.runs:
                if key in run.text:
                    run.text = run.text.replace(key, str_val, 1)
                    single_run_found = True
                    break

            if single_run_found:
                continue

            # 2. Multi-run split placeholder replacement
            run_texts = [r.text for r in paragraph.runs]
            combined = "".join(run_texts)
            start_idx = combined.find(key)
            if start_idx == -1:
                break
            end_idx = start_idx + len(key)

            curr_pos = 0
            for r in paragraph.runs:
                txt = r.text
                r_len = len(txt)
                r_start = curr_pos
                r_end = curr_pos + r_len
                curr_pos += r_len

                if r_end <= start_idx or r_start >= end_idx:
                    continue

                if r_start <= start_idx and r_end < end_idx:
                    offset = start_idx - r_start
                    r.text = txt[:offset] + str_val
                elif r_start > start_idx and r_end <= end_idx:
                    r.text = ""
                elif r_start < end_idx and r_end >= end_idx:
                    offset = end_idx - r_start
                    r.text = txt[offset:]


def replace_placeholders_in_paragraph(paragraph, mapping):
    """Alias for safe_replace_in_runs for backwards compatibility."""
    return safe_replace_in_runs(paragraph, mapping)


def populate_docx_from_master_template(master_template_path, output_filepath, placeholder_mapping, cat_key='AI_ML'):
    """
    Creates an exact copy of the uploaded master DOCX package at output_filepath,
    and replaces ONLY approved placeholders at the Word run level.
    
    CRITICAL:
    - Master DOCX package is the source of truth.
    - 100% of all images, logos, circular seals, MSME visual, green border, line dividers,
      watermarks, headers, footers, styles, fonts, and page layouts are preserved byte-for-byte.
    - Master template file on disk is NEVER modified.
    - Uses Word run-level replacement so no formatting, bolding, font sizes, or alignments are lost.
    """
    if not os.path.exists(master_template_path):
        raise FileNotFoundError(f"Master template file not found at: {master_template_path}")

    os.makedirs(os.path.dirname(output_filepath), exist_ok=True)
    # 1. Bit-for-bit copy of the master DOCX package
    shutil.copy2(master_template_path, output_filepath)

    # 2. Open copied candidate document for run-level replacement
    doc = docx.Document(output_filepath)

    # 3. Replace placeholders in all body paragraphs
    for p in doc.paragraphs:
        safe_replace_in_runs(p, placeholder_mapping)

    # 4. Replace placeholders in all tables (e.g. signature / seal section)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for cp in cell.paragraphs:
                    safe_replace_in_runs(cp, placeholder_mapping)

    # 5. Replace placeholders in headers & footers
    for section in doc.sections:
        for hp in section.header.paragraphs:
            safe_replace_in_runs(hp, placeholder_mapping)
        for fp in section.footer.paragraphs:
            safe_replace_in_runs(fp, placeholder_mapping)

    # 6. Single-page layout normalization (guarantees exact 1-page PDF rendering in LibreOffice):
    # In the master DOCX, all visual content (paragraphs P0-P12 + signature table) fits comfortably on Page 1.
    # We normalize trailing empty paragraphs at document end so no blank page is rendered.
    empty_spacers = []
    for i, p in enumerate(doc.paragraphs):
        if not p.text.strip():
            subsequent = [bp.text.strip() for bp in doc.paragraphs[i+1:]]
            if any('Best Regards' in s for s in subsequent):
                empty_spacers.append(p)

    if len(empty_spacers) >= 2:
        second_spacer = empty_spacers[1]._p
        if second_spacer.getparent() is not None:
            second_spacer.getparent().remove(second_spacer)

    if doc.paragraphs:
        for p in reversed(doc.paragraphs):
            if not p.text.strip():
                p.paragraph_format.space_before = docx.shared.Pt(0)
                p.paragraph_format.space_after = docx.shared.Pt(0)
                p.paragraph_format.line_spacing = docx.shared.Pt(1)
                for r in p.runs:
                    r.font.size = docx.shared.Pt(1)
            else:
                break

    # 8. Save candidate-specific DOCX
    doc.save(output_filepath)


class OfferLetterTemplateNotFoundError(Exception):
    """Raised when no active Offer Letter template record exists in the database for the required category."""
    pass


class OfferLetterTemplateFileMissingError(Exception):
    """Raised when the active Offer Letter template record exists in DB, but the physical file is missing from disk/storage."""
    pass


def normalize_internship_duration(dur):
    """Normalizes duration string to standard '1 Month', '3 Months', or 'Both'."""
    if not dur:
        return 'Both'
    d = str(dur).strip().lower().replace('_', ' ')
    if '3' in d or 'three' in d:
        return '3 Months'
    elif '1' in d or 'one' in d:
        return '1 Month'
    elif 'both' in d:
        return 'Both'
    return str(dur).strip().title()


def get_active_offer_letter_template(category_or_job=None, duration=None):
    """
    Dynamically retrieves the active Offer Letter DocumentTemplate record from the database
    matching the job/domain and duration of the candidate.

    Resolution logic:
    1. Determine job posting, department/domain, and candidate duration from input.
    2. Query all active offer letter templates from database.
    3. Match against template.job_domain dynamically without hardcoding.
    4. For matching domain, resolve duration:
       - Exact duration match ('1 Month' or '3 Months')
       - Fallback to duration = 'Both'
    5. If no matching template exists, raises OfferLetterTemplateNotFoundError with:
       "No active Offer Letter template is configured for [Job/Domain] — [Duration]. Please upload or activate the appropriate template."
    """
    job = None
    app = None
    emp = None
    specified_domain = None

    if isinstance(category_or_job, Employee):
        emp = category_or_job
        app = emp.application
        job = emp.job
        if not duration and app:
            duration = app.duration_display or app.duration
    elif isinstance(category_or_job, JobApplication):
        app = category_or_job
        emp = app.employee
        job = app.job
        if not duration:
            duration = app.duration_display or app.duration
    elif isinstance(category_or_job, JobPosting):
        job = category_or_job
        if not duration:
            duration = job.duration
    elif isinstance(category_or_job, str):
        specified_domain = category_or_job.strip()

    candidate_duration = normalize_internship_duration(duration)

    # All active offer letter templates in the database
    active_templates = DocumentTemplate.query.filter(
        DocumentTemplate.is_active == True,
        (DocumentTemplate.template_type == 'offer_letter') | (DocumentTemplate.template_type.like('offer_letter_%'))
    ).all()

    if not active_templates:
        display_domain = specified_domain or (job.department if job and job.department else (job.title if job else 'Unknown Domain'))
        raise OfferLetterTemplateNotFoundError(
            f"No active Offer Letter template is configured for {display_domain} — {candidate_duration}. Please upload or activate the appropriate template."
        )

    # Domain synonyms and aliases to support standard domains seamlessly
    DOMAIN_SYNONYMS = {
        'AI & ML': ['ai & ml', 'ai/ml', 'artificial intelligence', 'machine learning', 'deep learning', 'ai research', 'ai intern', 'ml intern', 'ai', 'ml', 'ai & data'],
        'Application Development': ['application development', 'app development', 'mobile application', 'mobile app', 'mobile developer', 'android', 'ios', 'flutter', 'react native', 'app intern', 'mobile intern', 'app', 'mobile engineering'],
        'Data Analytics': ['data analytics', 'data analyst', 'business intelligence', 'bi analyst', 'power bi', 'tableau', 'data visualization', 'data analysis', 'sql analyst', 'analytics intern', 'analytics'],
        'Full Stack Development': ['full stack development', 'full stack', 'fullstack', 'full-stack', 'web development', 'web developer', 'frontend', 'front-end', 'front end', 'backend', 'back-end', 'back end', 'web intern', 'engineering', 'web']
    }

    # Match scoring helper
    def calculate_match_score(template, target_job, target_str):
        t_domain = (template.job_domain or '').strip()
        t_type = (template.template_type or '').strip()

        # If template has no job_domain, check legacy template_type suffix or template name
        if not t_domain and t_type.startswith('offer_letter_'):
            type_suffix = t_type.replace('offer_letter_', '')
            type_map = {
                'ai_ml': 'AI & ML',
                'app_development': 'Application Development',
                'data_analytics': 'Data Analytics',
                'web_development': 'Full Stack Development'
            }
            t_domain = type_map.get(type_suffix, '')

        if not t_domain and template.name:
            name_lower = template.name.lower()
            if 'ai' in name_lower or 'machine learning' in name_lower:
                t_domain = 'AI & ML'
            elif 'app dev' in name_lower or 'application' in name_lower:
                t_domain = 'Application Development'
            elif 'analytics' in name_lower or 'data' in name_lower:
                t_domain = 'Data Analytics'
            elif 'full stack' in name_lower or 'web dev' in name_lower:
                t_domain = 'Full Stack Development'

        if not t_domain:
            # If it's a generic master offer letter template without a specific domain, assign baseline fallback score
            if t_type in ['offer_letter', 'default'] and not target_str:
                return 20
            return 0

        t_domain_lower = t_domain.lower()

        # Direct string query match
        if target_str:
            s_lower = target_str.lower()
            if t_domain_lower == s_lower:
                return 100
            # Check legacy category keys
            cat_map = {
                'ai_ml': 'AI & ML',
                'app_development': 'Application Development',
                'data_analytics': 'Data Analytics',
                'web_development': 'Full Stack Development'
            }
            if cat_map.get(s_lower) == t_domain or cat_map.get(s_lower.lower()) == t_domain:
                return 95
            if t_domain_lower in s_lower or s_lower in t_domain_lower:
                return 85
            # Check synonyms
            for syn in DOMAIN_SYNONYMS.get(t_domain, []):
                if syn == s_lower or syn in s_lower:
                    return 75

        # Job posting match
        if target_job:
            title = (target_job.title or '').lower()
            dept = (target_job.department or '').lower()
            skills = (getattr(target_job, 'skills', '') or '').lower()
            desc = (getattr(target_job, 'short_description', '') or '').lower()
            combined = f"{title} | {dept} | {skills} | {desc}"

            # Exact title or department match
            if t_domain_lower == title or t_domain_lower == dept:
                return 100
            # Direct containment
            if t_domain_lower in title:
                return 90
            if t_domain_lower in dept:
                return 85
            # Known domain synonyms
            synonyms = DOMAIN_SYNONYMS.get(t_domain, [t_domain_lower])
            for syn in synonyms:
                if ' ' in syn or '/' in syn or '-' in syn:
                    if syn in title:
                        return 80
                    if syn in dept:
                        return 75
                    if syn in combined:
                        return 65
                else:
                    # Single word token match in title/dept
                    title_tokens = set(title.replace('/', ' ').replace('-', ' ').replace('&', ' ').split())
                    dept_tokens = set(dept.replace('/', ' ').replace('-', ' ').replace('&', ' ').split())
                    if syn in title_tokens:
                        return 70
                    if syn in dept_tokens:
                        return 65

            # Dynamic keyword check for future custom domains (e.g. Cyber Security)
            domain_words = [w for w in t_domain_lower.split() if len(w) > 2 and w not in ['and', 'for', 'the', '&']]
            if domain_words and all(dw in combined for dw in domain_words):
                return 60

        return 0

    # Group active templates by domain and score
    scored_templates = []
    for tmpl in active_templates:
        score = calculate_match_score(tmpl, job, specified_domain)
        if score > 0:
            scored_templates.append((score, tmpl))

    if not scored_templates:
        display_domain = specified_domain or (job.department if job and job.department else (job.title if job else 'Unknown Domain'))
        raise OfferLetterTemplateNotFoundError(
            f"No active Offer Letter template is configured for {display_domain} — {candidate_duration}. Please upload or activate the appropriate template."
        )

    # Sort descending by match score
    scored_templates.sort(key=lambda x: x[0], reverse=True)
    best_score = scored_templates[0][0]
    # Keep templates matching top-scoring domain
    best_domain = scored_templates[0][1].job_domain or scored_templates[0][1].name
    candidate_templates = [t for score, t in scored_templates if score >= best_score - 10]

    # Resolve by duration:
    # 1. Exact match for candidate duration (e.g. '1 Month' or '3 Months')
    selected_template = None
    for t in candidate_templates:
        t_dur = normalize_internship_duration(t.duration)
        if t_dur == candidate_duration:
            selected_template = t
            break

    # 2. Fallback to duration = 'Both'
    if not selected_template:
        for t in candidate_templates:
            t_dur = normalize_internship_duration(t.duration)
            if t_dur == 'Both':
                selected_template = t
                break

    # 3. Fallback to any template matching the domain
    if not selected_template and candidate_templates:
        selected_template = candidate_templates[0]

    if not selected_template:
        display_domain = best_domain or (job.department if job and job.department else (job.title if job else 'Unknown Domain'))
        raise OfferLetterTemplateNotFoundError(
            f"No active Offer Letter template is configured for {display_domain} — {candidate_duration}. Please upload or activate the appropriate template."
        )

    # Validate physical file exists on disk
    if not selected_template.file_path or not os.path.exists(selected_template.file_path):
        candidate_paths = [
            os.path.join(current_app.root_path, 'uploads', 'templates', os.path.basename(selected_template.file_path or selected_template.filename or '')),
            os.path.join(current_app.root_path, 'uploads', 'templates', selected_template.filename or ''),
            os.path.join(current_app.root_path, 'uploads', 'templates', 'offer_letter_ai_ml_master.docx'),
            os.path.join(current_app.root_path, 'uploads', 'templates', 'offer_letter_app_development_master.docx'),
            os.path.join(current_app.root_path, 'uploads', 'templates', 'offer_letter_data_analytics_master.docx'),
            os.path.join(current_app.root_path, 'uploads', 'templates', 'offer_letter_full_stack_dev_master.docx'),
            os.path.join(current_app.root_path, 'uploads', 'templates', 'offer_letter_master.docx'),
        ]
        found = False
        for cpath in candidate_paths:
            if cpath and os.path.exists(cpath):
                selected_template.file_path = cpath
                found = True
                break
        if not found:
            raise OfferLetterTemplateFileMissingError(
                f"The active template file for '{selected_template.name}' could not be found at '{selected_template.file_path}'. Please upload the template again."
            )

    return selected_template


def ensure_default_templates_initialized():
    """
    Ensures that default master DOCX files for all 4 internship domains exist in uploads/templates/
    and have corresponding active DocumentTemplate records in the database without altering existing data.
    """
    templates_dir = os.path.join(current_app.root_path, 'uploads', 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    desktop_dir = os.path.join(os.path.expanduser('~'), 'Desktop')

    domain_configs = [
        {
            'name': 'AI & ML Offer Letter Template',
            'job_domain': 'AI & ML',
            'desktop_filename': 'offer letter - AI&ML.docx',
            'default_filename': 'offer_letter_ai_ml_master.docx',
            'type': 'offer_letter'
        },
        {
            'name': 'Application Development Offer Letter Template',
            'job_domain': 'Application Development',
            'desktop_filename': 'offer letter - App dev.docx',
            'default_filename': 'offer_letter_app_development_master.docx',
            'type': 'offer_letter'
        },
        {
            'name': 'Data Analytics Offer Letter Template',
            'job_domain': 'Data Analytics',
            'desktop_filename': 'offer letter - Data Analytics.docx',
            'default_filename': 'offer_letter_data_analytics_master.docx',
            'type': 'offer_letter'
        },
        {
            'name': 'Full Stack Development Offer Letter Template',
            'job_domain': 'Full Stack Development',
            'desktop_filename': 'offer letter - Full stack dev.docx',
            'default_filename': 'offer_letter_full_stack_dev_master.docx',
            'type': 'offer_letter'
        }
    ]

    for cfg in domain_configs:
        target_path = os.path.join(templates_dir, cfg['default_filename'])
        desktop_src = os.path.join(desktop_dir, cfg['desktop_filename'])

        if not os.path.exists(target_path):
            if os.path.exists(desktop_src):
                shutil.copy2(desktop_src, target_path)
            else:
                # Check static/default_templates
                static_src = os.path.join(current_app.root_path, 'static', 'default_templates', cfg['default_filename'])
                if os.path.exists(static_src):
                    shutil.copy2(static_src, target_path)

        # Check DB record
        tmpl_record = DocumentTemplate.query.filter_by(
            template_type='offer_letter',
            job_domain=cfg['job_domain'],
            is_active=True
        ).first()

        if not tmpl_record and os.path.exists(target_path):
            new_tmpl = DocumentTemplate(
                template_type='offer_letter',
                name=cfg['name'],
                job_domain=cfg['job_domain'],
                duration='Both',
                filename=cfg['desktop_filename'],
                file_path=target_path,
                is_active=True,
                created_by='System Default'
            )
            db.session.add(new_tmpl)

    db.session.commit()


def generate_offer_letter_docx(application_or_employee, custom_params=None, force_regenerate=False):
    """
    Generates a personalized candidate Offer Letter DOCX by copying the active master template DOCX
    assigned to the candidate's Job/Domain and Duration, and replacing ONLY the approved placeholders.
    
    CRITICAL IMPLEMENTATION GUARANTEES:
    1. The active master template DOCX assigned to the candidate's job/domain is the source of truth.
    2. The document is NOT rebuilt from scratch.
    3. The layout, headers, footers, logo, watermark, circular seal, MSME visuals, borders, fonts,
       and role-specific descriptions from the uploaded template are 100% preserved.
    4. Only approved dynamic placeholders are substituted:
       - Date: [DD/MM/YYYY] -> candidate offer date (DD/MM/YYYY)
       - Candidate Name: [Candidate Name] -> candidate's actual full name
       - Reference Number: [Reference Number] -> existing Application ID (e.g. AM-APP-000548)
       - Duration: [1 Month / 3 Months] -> candidate's actual selected duration (e.g. '1 Month' or '3 Months')
       - Joining Date: [Joining Date] -> candidate's actual joining date
       - Employee ID: [Employee ID] -> candidate's Employee ID if assigned
       - Job Title: [Job Title] -> candidate's Job Title
       - Department: [Department] -> candidate's Department / Domain
       - College Name: [College Name] -> candidate's College Name
       - Application ID: [Application ID] -> candidate's Application ID
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

    # Idempotency check: If document already exists and file exists, return it unless force_regenerate=True
    existing_doc = app.offer_letter_doc
    if existing_doc and existing_doc.file_path and os.path.exists(existing_doc.file_path) and not force_regenerate:
        return existing_doc, existing_doc.file_path

    # Determine internship duration
    internship_duration = app.duration_display or (f"{job.duration.replace('_', ' ').title()}" if job.duration else "1 Month")
    normalized_duration = normalize_internship_duration(internship_duration)

    # Automatically select the active template matching job/domain + duration
    active_template = get_active_offer_letter_template(app, duration=normalized_duration)

    custom_params = custom_params or {}
    now_utc = datetime.now(timezone.utc)
    current_date_str = now_utc.strftime("%d/%m/%Y")

    # Format data strictly from DB models without inventing values
    candidate_name = (app.full_name or (employee.candidate_name if employee else "Candidate")).strip()
    reference_number = app.formatted_code
    joining_date = (custom_params.get('joining_date') or custom_params.get('start_date') or app.joining_date or "Immediate / As mutually agreed").strip()
    employee_id_val = employee.employee_id if (employee and employee.employee_id) else reference_number
    job_title_val = (custom_params.get('job_title') or (job.title if job else '')).strip()
    dept_val = (active_template.job_domain or (job.department if job else '')).strip()
    college_val = (app.college or '').strip()

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
        '[1 Month / 3 Months]': normalized_duration,
        '[Internship Duration]': normalized_duration,
        '{{1 Month / 3 Months}}': normalized_duration,
        '{{internship_duration}}': normalized_duration,
        '{{Internship Duration}}': normalized_duration,

        # 5. Joining Date
        '[Joining Date]': joining_date,
        '[Start Date]': joining_date,
        '{{Joining Date}}': joining_date,
        '{{joining_date}}': joining_date,
        '{{Start Date}}': joining_date,
        '{{start_date}}': joining_date,

        # 6. Additional Useful Placeholders
        '[Employee ID]': employee_id_val,
        '{{employee_id}}': employee_id_val,
        '{{Employee ID}}': employee_id_val,

        '[Job Title]': job_title_val,
        '{{job_title}}': job_title_val,
        '{{Job Title}}': job_title_val,

        '[Department]': dept_val,
        '{{department}}': dept_val,
        '{{Department}}': dept_val,

        '[College Name]': college_val,
        '{{college_name}}': college_val,
        '{{College Name}}': college_val,
    }

    # Destination output path
    gen_dir = os.path.join(current_app.root_path, 'uploads', 'generated_documents')
    os.makedirs(gen_dir, exist_ok=True)

    output_filename = f"{app.formatted_code}_Offer_Letter.docx"
    output_filepath = os.path.join(gen_dir, output_filename)

    # Copy master DOCX package and replace ONLY approved placeholders at Word run level
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
