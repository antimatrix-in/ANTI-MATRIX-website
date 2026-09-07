import os
import re
import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timezone
from flask import current_app
from models import db, JobApplication, Employee, EmployeeDocument, EmailTemplate, EmailLog


# =====================================================================
# DEFAULT OFFICIAL ANTI MATRIX EMAIL TEMPLATES
# =====================================================================

DEFAULT_APPLICATION_SUCCESSFUL_SUBJECT = "Application Successfully Submitted — {{Internship Role}} | {{Application ID}}"

DEFAULT_APPLICATION_SUCCESSFUL_BODY = """Dear {{Student Name}},

Thank you for applying for the **{{Internship Role}} Internship Opportunity at Anti Matrix**.

We are pleased to inform you that your internship application has been **successfully submitted and received**.

### Application Details

**Application ID:** {{Application ID}}
**Internship Role:** {{Internship Role}}
**Application Date:** {{Application Date}}

Your application is currently **under review by our team**. We kindly request you to allow us some time while we evaluate your application and submitted details.

If your application is shortlisted, you will receive a **confirmation/selection email** with the next steps and further instructions.

Please keep your **Application ID** for future reference when communicating with Anti Matrix regarding your application.

Thank you for your interest in building your skills and gaining practical experience with **Anti Matrix**.

Best Regards,
**Anti Matrix Team**
Internship & Career Opportunities
{{Company Email}}
{{Website}}"""

DEFAULT_OFFER_LETTER_SUBJECT = "Congratulations! You Have Been Shortlisted — {{Internship Role}} | Anti Matrix"

DEFAULT_OFFER_LETTER_BODY = """Dear {{Student Name}},

**Congratulations! 🎉**

We are pleased to inform you that you have been **successfully shortlisted for the {{Internship Role}} Internship at Anti Matrix**.

After reviewing your application and profile, our team is happy to move forward with you for this internship opportunity.

We have attached your **Internship Offer Letter** to this email. Kindly go through the offer letter carefully, sign it, and send the **signed copy back to us at {{Company Email}}**.

### Your Internship Details

**Application ID:** {{Application ID}}
**Internship Role:** {{Internship Role}}
**Internship Duration:** {{Internship Duration}}
**Start Date:** {{Start Date}}

Please make sure to return the signed offer letter at your earliest convenience so that we can complete the next steps of your internship onboarding.

We are excited to have you join **Anti Matrix** and look forward to seeing you learn, contribute, and grow with us.

Once again, **congratulations and welcome to the Anti Matrix internship program!** 🚀

Warm regards,
**Anti Matrix Team**
Internship & Career Opportunities
{{Company Email}}
{{Website}}"""

DEFAULT_JOINING_SUBJECT = "Welcome to Anti Matrix — Your Internship Joining Details & Employee Credentials"

DEFAULT_JOINING_BODY = """Dear {{Student Name}},

Congratulations!

We are pleased to welcome you to the Anti Matrix internship program.

Your internship joining has been confirmed.

### Your Joining Details

**Employee ID:** {{Employee ID}}
**Internship Role:** {{Internship Role}}
**Internship Duration:** {{Internship Duration}}
**Joining Date:** {{Joining Date}}

### Internship Portal Login

You can access the internship portal using the credentials below:

**Portal:** {{Internship Portal Link}}
**Employee ID:** {{Employee ID}}
**Temporary Password:** {{Employee Password}}

Please keep these credentials confidential and do not share them with anyone.

For your first login, you may be required to change your temporary password.

We look forward to having you with us and wish you a successful and productive internship experience at Anti Matrix.

Best Regards,

**Anti Matrix Team**
Internship & Career Opportunities
{{Company Email}}
{{Website}}"""


# =====================================================================
# MARKDOWN TO HTML EMAIL CONVERTER
# =====================================================================

def markdown_to_html_email(markdown_text, title="Anti Matrix Notification"):
    """
    Renders structured Markdown content into clean, responsive HTML email markup
    compatible with major email clients (Gmail, Outlook, Apple Mail, Webmail).
    Renders bold text, headings, lists, links, paragraphs, and emojis.
    """
    if not markdown_text:
        return ""

    lines = markdown_text.strip().split('\n')
    rendered_blocks = []
    
    in_list = False
    current_list_items = []

    def flush_list():
        nonlocal in_list, current_list_items, rendered_blocks
        if in_list and current_list_items:
            list_html = '<ul style="margin: 8px 0 16px 20px; padding: 0; color: #2d3748; line-height: 1.6;">'
            for item in current_list_items:
                list_html += f'<li style="margin-bottom: 6px;">{item}</li>'
            list_html += '</ul>'
            rendered_blocks.append(list_html)
            current_list_items = []
            in_list = False

    def inline_format(text):
        # Escape HTML entities first to prevent XSS
        safe_text = html.escape(text)
        # **bold**
        safe_text = re.sub(r'\*\*(.+?)\*\*', r'<strong style="color: #000000; font-weight: 700;">\1</strong>', safe_text)
        # *italic*
        safe_text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', safe_text)
        # `code`
        safe_text = re.sub(r'`(.+?)`', r'<code style="font-family: monospace; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; color: #0f766e;">\1</code>', safe_text)
        # [link](url)
        safe_text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" target="_blank" style="color: #10b981; text-decoration: underline; font-weight: 600;">\1</a>', safe_text)
        return safe_text

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            flush_list()
            continue

        # ### Heading 3
        if line.startswith('### '):
            flush_list()
            heading_content = inline_format(line[4:].strip())
            rendered_blocks.append(
                f'<h3 style="font-size: 16px; font-weight: 800; color: #000000; margin: 20px 0 10px 0; padding-bottom: 6px; border-bottom: 2px solid #e2e8f0; text-transform: uppercase; letter-spacing: 0.04em;">{heading_content}</h3>'
            )
        # ## Heading 2
        elif line.startswith('## '):
            flush_list()
            heading_content = inline_format(line[3:].strip())
            rendered_blocks.append(
                f'<h2 style="font-size: 18px; font-weight: 800; color: #000000; margin: 24px 0 12px 0; padding-bottom: 6px; border-bottom: 2px solid #10b981;">{heading_content}</h2>'
            )
        # # Heading 1
        elif line.startswith('# '):
            flush_list()
            heading_content = inline_format(line[2:].strip())
            rendered_blocks.append(
                f'<h1 style="font-size: 22px; font-weight: 800; color: #000000; margin: 24px 0 14px 0;">{heading_content}</h1>'
            )
        # Bullet list item
        elif line.startswith('- ') or line.startswith('* ') or line.startswith('• '):
            in_list = True
            item_text = inline_format(line[2:].strip())
            current_list_items.append(item_text)
        # Standard paragraph
        else:
            flush_list()
            p_content = inline_format(line)
            rendered_blocks.append(
                f'<p style="margin: 0 0 14px 0; font-size: 15px; line-height: 1.65; color: #2d3748;">{p_content}</p>'
            )

    flush_list()
    body_content_html = "\n".join(rendered_blocks)

    # Full Email Wrapper HTML
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(title)}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; padding: 30px 15px;">
    <tr>
      <td align="center">
        <!-- Main Card Container -->
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 620px; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 10px 25px rgba(0,0,0,0.06);">
          
          <!-- Top Accent Header Banner -->
          <tr>
            <td style="background-color: #070a12; padding: 24px 32px; border-bottom: 3px solid #10b981; text-align: left;">
              <table width="100%" border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td>
                    <div style="font-size: 20px; font-weight: 900; color: #ffffff; letter-spacing: 0.06em;">
                      ANTI<span style="color: #10b981;">-</span>MATRIX
                    </div>
                    <div style="font-size: 11px; color: #94a3b8; letter-spacing: 0.12em; text-transform: uppercase; margin-top: 3px;">
                      Break The Matrix &bull; Think Different &bull; Create The Future
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Email Body Content -->
          <tr>
            <td style="padding: 32px 32px 24px 32px; color: #2d3748;">
              {body_content_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f1f5f9; padding: 20px 32px; border-top: 1px solid #e2e8f0; text-align: center;">
              <p style="margin: 0 0 6px 0; font-size: 12px; color: #64748b; font-weight: 600;">
                Anti-Matrix &bull; Chennai, Tamil Nadu, India
              </p>
              <p style="margin: 0; font-size: 11px; color: #94a3b8;">
                This is an official automated notification from Anti-Matrix. For inquiries, contact <a href="mailto:info@antimatrix.co.in" style="color: #10b981; text-decoration: none;">info@antimatrix.co.in</a>.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return full_html


# =====================================================================
# VARIABLE REPLACEMENT ENGINE
# =====================================================================

def replace_variables(template_str, variable_dict):
    """
    Replaces template variables dynamically, supporting multiple casing forms:
    e.g. {{Student Name}}, {{student_name}}, {{Student_Name}}
    """
    if not template_str:
        return ""

    result = template_str
    for key, val in variable_dict.items():
        val_str = str(val) if val is not None else ""
        
        # Handle given key
        result = result.replace(f"{{{{{key}}}}}", val_str)
        # Handle lower key
        result = result.replace(f"{{{{{key.lower()}}}}}", val_str)
        # Handle snake_case key
        snake_key = key.lower().replace(" ", "_")
        result = result.replace(f"{{{{{snake_key}}}}}", val_str)
        # Handle Title Case key
        title_key = key.title()
        result = result.replace(f"{{{{{title_key}}}}}", val_str)

    return result


# =====================================================================
# CORE EMAIL TRANSMISSION
# =====================================================================

# =====================================================================
# CORE EMAIL TRANSMISSION (BREVO API & SMTP RELAY)
# =====================================================================

def send_brevo_email(recipient_email, recipient_name, subject, body_text, body_html=None, attachment_path=None, attachment_name=None):
    """
    Sends transactional email using Brevo (Sendinblue) API v3 or SMTP relay.
    Endpoint: https://api.brevo.com/v3/smtp/email
    Header: api-key
    Falls back cleanly to SMTP relay / Simulation if BREVO_API_KEY is not configured.
    """
    api_key = (
        os.environ.get('BREVO_API_KEY', '').strip() or 
        (current_app.config.get('BREVO_API_KEY', '').strip() if current_app else '')
    )
    sender_email = (
        os.environ.get('BREVO_SENDER_EMAIL', '').strip() or 
        os.environ.get('SENDER_EMAIL', '').strip() or 
        (current_app.config.get('BREVO_SENDER_EMAIL', '').strip() if current_app else '') or
        (current_app.config.get('SENDER_EMAIL', '').strip() if current_app else '') or
        'info@antimatrix.co.in'
    )
    sender_name = (
        os.environ.get('BREVO_SENDER_NAME', '').strip() or 
        (current_app.config.get('BREVO_SENDER_NAME', '').strip() if current_app else '') or
        'Anti Matrix'
    )

    # If Brevo API key is not present, use SMTP / Simulation mode
    if not api_key:
        return send_mime_email(recipient_email, subject, body_text, body_html, attachment_path, attachment_name)

    import base64
    import requests

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    payload = {
        "sender": {
            "name": sender_name,
            "email": sender_email
        },
        "to": [
            {
                "email": recipient_email,
                "name": recipient_name or recipient_email
            }
        ],
        "subject": subject,
        "textContent": body_text,
        "htmlContent": body_html or markdown_to_html_email(body_text, title=subject)
    }

    if attachment_path and os.path.exists(attachment_path):
        att_name = attachment_name or os.path.basename(attachment_path)
        with open(attachment_path, "rb") as f:
            encoded_content = base64.b64encode(f.read()).decode('utf-8')
        payload["attachment"] = [
            {
                "name": att_name,
                "content": encoded_content
            }
        ]

    try:
        response = requests.post("https://api.brevo.com/v3/smtp/email", headers=headers, json=payload, timeout=25)
        if response.status_code in [200, 201, 202]:
            resp_data = response.json() if response.text else {}
            provider_id = resp_data.get('messageId') or f"brevo_api_{int(datetime.now(timezone.utc).timestamp())}"
            return True, "Email successfully sent via Brevo API", provider_id
        else:
            if current_app:
                current_app.logger.error(f"Brevo API error ({response.status_code}): {response.text}")
            err_msg = f"Brevo API error ({response.status_code})"
            try:
                err_data = response.json()
                if 'message' in err_data:
                    err_msg += f": {err_data['message']}"
            except Exception:
                pass
            return False, err_msg, None
    except Exception as e:
        if current_app:
            current_app.logger.error(f"Brevo API request exception: {str(e)}")
        return False, f"Email delivery failed: {str(e)}", None


def send_mime_email(recipient_email, subject, body_text, body_html=None, attachment_path=None, attachment_name=None):
    """
    Dispatches a multipart MIME email via SMTP (HTML + Plain Text + Optional Attachment).
    Connects to SMTP if configured; otherwise logs simulated transmission in development.
    Supports port 587 (STARTTLS) and port 465 (SSL).
    """
    smtp_server = (
        os.environ.get('SMTP_SERVER', '').strip() or 
        (current_app.config.get('SMTP_SERVER', '').strip() if current_app else '')
    )
    smtp_port_raw = (
        os.environ.get('SMTP_PORT', '').strip() or 
        (str(current_app.config.get('SMTP_PORT', '587')).strip() if current_app else '587') or 
        '587'
    )
    try:
        smtp_port = int(smtp_port_raw) if smtp_port_raw.isdigit() else 587
    except (ValueError, TypeError):
        smtp_port = 587

    smtp_user = (
        os.environ.get('SMTP_USER', '').strip() or 
        (current_app.config.get('SMTP_USER', '').strip() if current_app else '')
    )
    smtp_password = (
        os.environ.get('SMTP_PASSWORD', '').strip() or 
        (current_app.config.get('SMTP_PASSWORD', '').strip() if current_app else '')
    )
    sender_email = (
        os.environ.get('SENDER_EMAIL', '').strip() or 
        os.environ.get('BREVO_SENDER_EMAIL', '').strip() or 
        (current_app.config.get('SENDER_EMAIL', '').strip() if current_app else '') or
        (current_app.config.get('BREVO_SENDER_EMAIL', '').strip() if current_app else '') or
        (current_app.config.get('CONTACT_EMAIL', '').strip() if current_app else '') or
        'info@antimatrix.co.in'
    )
    sender_name = (
        os.environ.get('BREVO_SENDER_NAME', '').strip() or 
        (current_app.config.get('BREVO_SENDER_NAME', '').strip() if current_app else '') or
        'Anti Matrix'
    )

    try:
        if smtp_server and smtp_user and smtp_password:
            msg = MIMEMultipart('mixed')
            msg['From'] = f"{sender_name} <{sender_email}>"
            msg['To'] = recipient_email
            msg['Subject'] = subject

            # Create alternative container for text and html
            alt_part = MIMEMultipart('alternative')
            alt_part.attach(MIMEText(body_text, 'plain', 'utf-8'))
            if body_html:
                alt_part.attach(MIMEText(body_html, 'html', 'utf-8'))
            msg.attach(alt_part)

            # Optional attachment
            if attachment_path and os.path.exists(attachment_path):
                att_name = attachment_name or os.path.basename(attachment_path)
                with open(attachment_path, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{att_name}"')
                    msg.attach(part)

            if smtp_port == 465:
                # SSL-on-connect
                with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=25) as server:
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg)
            else:
                # Standard STARTTLS on port 587
                with smtplib.SMTP(smtp_server, smtp_port, timeout=25) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg)

            provider_id = f"smtp_{int(datetime.now(timezone.utc).timestamp())}"
            return True, "Email successfully sent via SMTP", provider_id
        else:
            # Simulated Sandbox Mode
            if current_app:
                current_app.logger.info(f"[EMAIL SIMULATION] Sent email to {recipient_email} | Subject: {subject}")
            else:
                print(f"[EMAIL SIMULATION] Sent email to {recipient_email} | Subject: {subject}")
            sim_id = "sim_msg_id_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            return True, "Email successfully sent (sandbox mode)", sim_id

    except smtplib.SMTPAuthenticationError:
        if current_app:
            current_app.logger.error("SMTP authentication failed. Please verify SMTP_USER and SMTP_PASSWORD.")
        return False, "Email authentication failed. Please verify the Brevo SMTP credentials.", None
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, OSError) as e:
        if current_app:
            current_app.logger.error(f"SMTP connection error: {str(e)}")
        return False, "Unable to connect to the email service. Please check network connection and SMTP server settings.", None
    except smtplib.SMTPException as e:
        if current_app:
            current_app.logger.error(f"SMTP protocol error: {str(e)}")
        return False, f"SMTP error occurred: {str(e)}", None
    except Exception as e:
        if current_app:
            current_app.logger.error(f"Unexpected email delivery exception: {str(e)}")
        return False, f"Email delivery failed: {str(e)}", None


# =====================================================================
# 1. APPLICATION SUCCESSFUL EMAIL PREVIEW & DISPATCH
# =====================================================================

def render_application_successful_email(application):
    """
    Renders the official Application Successful confirmation email with real applicant data.
    Returns dictionary with rendered subject, plain text body, and responsive HTML body.
    """
    if not application:
        return {'to': '', 'subject': '', 'body_text': '', 'body_html': ''}

    job = application.job
    job_title = job.title if job and job.title else "Internship Position"
    app_date = (
        application.created_at.strftime("%d/%m/%Y") 
        if application.created_at 
        else datetime.now(timezone.utc).strftime("%d/%m/%Y")
    )
    company_email = (
        (current_app.config.get('CONTACT_EMAIL') if current_app else None) or 
        os.environ.get('CONTACT_EMAIL') or 
        os.environ.get('SENDER_EMAIL') or 
        'info@antimatrix.co.in'
    )
    website = "www.antimatrix.co.in"
    candidate_name = application.full_name or (f"{application.first_name or ''} {application.last_name or ''}".strip()) or "Applicant"
    formatted_code = application.formatted_code if hasattr(application, 'formatted_code') else f"AM-APP-{application.id:06d}"

    variables = {
        'Student Name': candidate_name,
        'Internship Role': job_title,
        'Application ID': formatted_code,
        'Application Date': app_date,
        'Company Email': company_email,
        'Website': website,
        'employee_name': candidate_name,
        'job_title': job_title,
        'application_id': formatted_code,
        'application_date': app_date,
        'company_email': company_email,
        'website': website
    }

    raw_subject = DEFAULT_APPLICATION_SUCCESSFUL_SUBJECT
    raw_body = DEFAULT_APPLICATION_SUCCESSFUL_BODY
    try:
        tmpl = EmailTemplate.query.filter_by(template_type='application_successful').first()
        if tmpl and tmpl.subject:
            raw_subject = tmpl.subject
        if tmpl and tmpl.body:
            raw_body = tmpl.body
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"Could not load custom EmailTemplate: {str(e)}")

    subject = replace_variables(raw_subject, variables)
    body_text = replace_variables(raw_body, variables)
    body_html = markdown_to_html_email(body_text, title=subject)

    return {
        'to': application.email or '',
        'subject': subject,
        'body_text': body_text,
        'body_html': body_html
    }


def send_application_successful_email(application):
    """
    Sends the official Application Successful confirmation email via Brevo.
    Enforces strict duplicate sending protection and safe database transactions.
    """
    if not application:
        return False, "Invalid application record."

    recipient_email = (application.email or "").strip()
    if not recipient_email:
        return False, "Candidate email address is missing for this application."

    # Duplicate send check
    if application.application_success_email_status == 'SENT':
        sent_time = application.application_success_email_sent_at.strftime('%b %d, %Y') if application.application_success_email_sent_at else 'earlier'
        return False, f"Application Successful email already sent on {sent_time}."

    try:
        rendered = render_application_successful_email(application)
        subject = rendered.get('subject') or DEFAULT_APPLICATION_SUCCESSFUL_SUBJECT
        body_text = rendered.get('body_text') or DEFAULT_APPLICATION_SUCCESSFUL_BODY
        body_html = rendered.get('body_html')

        success, msg, provider_id = send_brevo_email(
            recipient_email=recipient_email,
            recipient_name=application.full_name or recipient_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html
        )

        now_utc = datetime.now(timezone.utc)
        if success:
            application.application_success_email_status = 'SENT'
            application.application_success_email_sent_at = now_utc
            log_status = 'SENT'
            error_msg = None
        else:
            application.application_success_email_status = 'FAILED'
            log_status = 'FAILED'
            error_msg = msg

        # Log to EmailLog
        try:
            email_log = EmailLog(
                recipient_email=recipient_email,
                template_type='application_successful',
                reference_id=application.formatted_code,
                subject=subject,
                body_preview=body_text[:200] if body_text else '',
                status=log_status,
                provider_message_id=provider_id,
                error_message=error_msg,
                has_attachment=False,
                sent_at=now_utc
            )
            db.session.add(email_log)
            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            if current_app:
                current_app.logger.error(f"Database error saving EmailLog: {str(db_err)}")

        return success, msg
    except Exception as e:
        if current_app:
            current_app.logger.error(f"Unexpected error in send_application_successful_email: {str(e)}", exc_info=True)
        return False, f"Failed to send email: {str(e)}"


# =====================================================================
# 2. SHORTLISTED / OFFER LETTER EMAIL PREVIEW & DISPATCH
# =====================================================================

def render_shortlisted_offer_email(application, custom_params=None):
    """
    Renders the official Shortlisted / Offer Letter email with real applicant data.
    Returns dictionary with rendered subject, plain text body, and responsive HTML body.
    """
    if not application:
        return {'to': '', 'subject': '', 'body_text': '', 'body_html': ''}

    custom_params = custom_params or {}
    job = application.job
    job_title = job.title if job and job.title else "Internship Position"
    duration = application.duration_display if application.duration_display else (f"{job.duration.replace('_', ' ').title()}" if job and job.duration else "3 Months")
    joining_date = custom_params.get('start_date') or custom_params.get('joining_date') or "Immediate / As mutually agreed"
    company_email = (
        (current_app.config.get('CONTACT_EMAIL') if current_app else None) or 
        os.environ.get('CONTACT_EMAIL') or 
        os.environ.get('SENDER_EMAIL') or 
        'info@antimatrix.co.in'
    )
    website = "www.antimatrix.co.in"
    candidate_name = application.full_name or (f"{application.first_name or ''} {application.last_name or ''}".strip()) or "Applicant"
    formatted_code = application.formatted_code if hasattr(application, 'formatted_code') else f"AM-APP-{application.id:06d}"
    emp_id = application.employee.employee_id if application.employee else formatted_code

    variables = {
        'Student Name': candidate_name,
        'Internship Role': job_title,
        'Application ID': formatted_code,
        'Internship Duration': duration,
        'Start Date': joining_date,
        'Company Email': company_email,
        'Website': website,
        'employee_name': candidate_name,
        'employee_id': emp_id,
        'job_title': job_title,
        'department': job.department if job and job.department else 'Engineering',
        'application_id': formatted_code,
        'internship_duration': duration,
        'start_date': joining_date,
        'company_email': company_email,
        'website': website
    }

    raw_subject = DEFAULT_OFFER_LETTER_SUBJECT
    raw_body = DEFAULT_OFFER_LETTER_BODY
    try:
        tmpl = EmailTemplate.query.filter_by(template_type='offer_letter').first()
        if tmpl and tmpl.subject:
            raw_subject = tmpl.subject
        if tmpl and tmpl.body:
            raw_body = tmpl.body
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"Could not load custom EmailTemplate: {str(e)}")

    subject = replace_variables(raw_subject, variables)
    body_text = replace_variables(raw_body, variables)
    body_html = markdown_to_html_email(body_text, title=subject)

    return {
        'to': application.email or '',
        'subject': subject,
        'body_text': body_text,
        'body_html': body_html
    }


def send_offer_letter_shortlisted_email(application_or_employee, start_date=None):
    """
    Sends the official Offer Letter / Shortlisted email with the generated employee DOCX attached via Brevo.
    Enforces strict ONE-TIME send protection.
    """
    # Normalize input
    if isinstance(application_or_employee, Employee):
        employee = application_or_employee
        app = employee.application
    elif isinstance(application_or_employee, JobApplication):
        app = application_or_employee
        employee = app.employee
    else:
        return False, "Invalid application or employee record."

    if not app:
        return False, "Missing associated candidate application record."

    recipient_email = (app.email or "").strip()
    if not recipient_email:
        return False, "Candidate email address is missing for this application."

    # Retrieve candidate-specific Offer Letter document
    emp_doc = app.offer_letter_doc
    if not emp_doc or not emp_doc.file_path or not os.path.exists(emp_doc.file_path):
        return False, "Offer Letter DOCX has not been generated yet. Please generate it first."

    # ONE-TIME SEND PROTECTION
    if emp_doc.email_status == 'sent':
        sent_time = emp_doc.sent_at.strftime('%b %d, %Y') if emp_doc.sent_at else 'earlier'
        return False, f"Offer Letter already sent on {sent_time}. Duplicate sending is prevented."

    try:
        rendered = render_shortlisted_offer_email(app, custom_params={'start_date': start_date})
        subject = rendered.get('subject') or DEFAULT_OFFER_LETTER_SUBJECT
        body_text = rendered.get('body_text') or DEFAULT_OFFER_LETTER_BODY
        body_html = rendered.get('body_html')

        success, msg, provider_id = send_brevo_email(
            recipient_email=recipient_email,
            recipient_name=app.full_name or recipient_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachment_path=emp_doc.file_path,
            attachment_name=emp_doc.file_name
        )

        now_utc = datetime.now(timezone.utc)
        if success:
            emp_doc.email_status = 'sent'
            emp_doc.status = 'SENT'
            emp_doc.sent_at = now_utc
            emp_doc.verified_at = now_utc
            emp_doc.email_error = None
            log_status = 'SENT'
            error_msg = None
        else:
            emp_doc.email_status = 'failed'
            emp_doc.email_error = msg
            log_status = 'FAILED'
            error_msg = msg

        # Log to EmailLog
        try:
            email_log = EmailLog(
                recipient_email=recipient_email,
                template_type='offer_letter',
                reference_id=employee.employee_id if employee else app.formatted_code,
                subject=subject,
                body_preview=body_text[:200] if body_text else '',
                status=log_status,
                provider_message_id=provider_id,
                error_message=error_msg,
                has_attachment=True,
                attachment_name=emp_doc.file_name,
                sent_at=now_utc
            )
            db.session.add(email_log)
            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            if current_app:
                current_app.logger.error(f"Database error saving EmailLog: {str(db_err)}")

        return success, msg
    except Exception as e:
        if current_app:
            current_app.logger.error(f"Unexpected error in send_offer_letter_shortlisted_email: {str(e)}", exc_info=True)
        return False, f"Failed to send Offer Letter email: {str(e)}"


# =====================================================================
# 3. JOINING & EMPLOYEE CREDENTIALS EMAIL PREVIEW & DISPATCH
# =====================================================================

def render_joining_credentials_email(application, custom_params=None):
    """
    Renders the official Joining & Employee Credentials email with real applicant data.
    Returns dictionary with rendered subject, plain text body, and responsive HTML body.
    """
    if not application:
        return {'to': '', 'subject': '', 'body_text': '', 'body_html': ''}

    custom_params = custom_params or {}
    job = application.job
    job_title = job.title if job and job.title else "Internship Position"
    duration = application.duration_display if application.duration_display else (f"{job.duration.replace('_', ' ').title()}" if job and job.duration else "3 Months")
    joining_date = custom_params.get('joining_date') or custom_params.get('start_date') or application.joining_date or "Immediate"
    company_email = (
        (current_app.config.get('CONTACT_EMAIL') if current_app else None) or 
        os.environ.get('CONTACT_EMAIL') or 
        os.environ.get('SENDER_EMAIL') or 
        'info@antimatrix.co.in'
    )
    website = "www.antimatrix.co.in"
    candidate_name = application.full_name or (f"{application.first_name or ''} {application.last_name or ''}".strip()) or "Applicant"
    formatted_code = application.formatted_code if hasattr(application, 'formatted_code') else f"AM-APP-{application.id:06d}"
    
    employee = application.employee
    emp_id = employee.employee_id if employee else formatted_code
    
    secret_key = current_app.config.get('SECRET_KEY', 'default-key') if current_app else 'default-key'
    temp_password = (
        custom_params.get('temp_password') or 
        (employee.get_temp_password(secret_key) if employee else '') or 
        "Provided during onboarding"
    )
    
    portal_link = (
        custom_params.get('portal_url') or 
        (current_app.config.get('INTERNSHIP_PORTAL_URL') if current_app else None) or 
        os.environ.get('INTERNSHIP_PORTAL_URL') or 
        "https://www.antimatrix.co.in/internship"
    )

    variables = {
        'Student Name': candidate_name,
        'Employee ID': emp_id,
        'Employee Password': temp_password,
        'Internship Role': job_title,
        'Internship Duration': duration,
        'Joining Date': joining_date,
        'Internship Portal Link': portal_link,
        'Company Email': company_email,
        'Website': website,
        'employee_name': candidate_name,
        'employee_id': emp_id,
        'employee_password': temp_password,
        'temp_password': temp_password,
        'job_title': job_title,
        'department': job.department if job and job.department else 'Engineering',
        'application_id': formatted_code,
        'internship_duration': duration,
        'joining_date': joining_date,
        'portal_url': portal_link,
        'portal_link': portal_link,
        'company_email': company_email,
        'website': website
    }

    raw_subject = DEFAULT_JOINING_SUBJECT
    raw_body = DEFAULT_JOINING_BODY
    try:
        tmpl = EmailTemplate.query.filter_by(template_type='joining_credentials').first()
        if tmpl and tmpl.subject:
            raw_subject = tmpl.subject
        if tmpl and tmpl.body:
            raw_body = tmpl.body
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"Could not load custom EmailTemplate for joining: {str(e)}")

    subject = replace_variables(raw_subject, variables)
    body_text = replace_variables(raw_body, variables)
    body_html = markdown_to_html_email(body_text, title=subject)

    return {
        'to': application.email or '',
        'subject': subject,
        'body_text': body_text,
        'body_html': body_html
    }


def send_joining_credentials_email(application_or_employee, joining_date=None, portal_url=None, temp_password=None):
    """
    Sends the official Joining & Employee Credentials email via Brevo.
    Enforces duplicate sending protection and audit logging.
    """
    if isinstance(application_or_employee, Employee):
        employee = application_or_employee
        app = employee.application
    elif isinstance(application_or_employee, JobApplication):
        app = application_or_employee
        employee = app.employee
    else:
        return False, "Invalid application or employee record."

    if not app:
        return False, "Missing associated candidate application record."

    recipient_email = (app.email or "").strip()
    if not recipient_email:
        return False, "Candidate email address is missing for this application."

    # Duplicate send protection
    if app.joining_email_status == 'SENT':
        sent_time = app.joining_email_sent_at.strftime('%b %d, %Y') if app.joining_email_sent_at else 'earlier'
        return False, f"Joining & Credentials email already sent on {sent_time}."

    secret_key = current_app.config.get('SECRET_KEY', 'default-key') if current_app else 'default-key'
    resolved_pwd = temp_password or (employee.get_temp_password(secret_key) if employee else '')

    effective_joining_date = joining_date or app.joining_date
    if not effective_joining_date:
        return False, "Joining date is required before sending the joining email."

    try:
        rendered = render_joining_credentials_email(
            app,
            custom_params={
                'joining_date': effective_joining_date,
                'portal_url': portal_url,
                'temp_password': resolved_pwd
            }
        )
        subject = rendered.get('subject') or DEFAULT_JOINING_SUBJECT
        body_text = rendered.get('body_text') or DEFAULT_JOINING_BODY
        body_html = rendered.get('body_html')

        success, msg, provider_id = send_brevo_email(
            recipient_email=recipient_email,
            recipient_name=app.full_name or recipient_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html
        )

        now_utc = datetime.now(timezone.utc)
        if success:
            app.joining_email_status = 'SENT'
            app.joining_email_sent_at = now_utc
            app.joining_date = effective_joining_date
            if employee:
                employee.clear_temp_password()
            log_status = 'SENT'
            error_msg = None
        else:
            app.joining_email_status = 'FAILED'
            log_status = 'FAILED'
            error_msg = msg

        # Log to EmailLog
        try:
            email_log = EmailLog(
                recipient_email=recipient_email,
                template_type='joining_credentials',
                reference_id=employee.employee_id if employee else app.formatted_code,
                subject=subject,
                body_preview=body_text[:200] if body_text else '',
                status=log_status,
                provider_message_id=provider_id,
                error_message=error_msg,
                has_attachment=False,
                sent_at=now_utc
            )
            db.session.add(email_log)
            db.session.commit()
        except Exception as db_err:
            db.session.rollback()
            if current_app:
                current_app.logger.error(f"Database error saving EmailLog: {str(db_err)}")

        return success, msg
    except Exception as e:
        if current_app:
            current_app.logger.error(f"Unexpected error in send_joining_credentials_email: {str(e)}", exc_info=True)
        return False, f"Failed to send Joining email: {str(e)}"


# =====================================================================
# 4. PREVIEW & TEST EMAIL UTILITIES
# =====================================================================

def render_sample_email_preview(template_type):
    """
    Renders email subject and body using sample preview values.
    Does not modify any live database records.
    """
    sample_variables = {
        'Student Name': 'Rahul Kumar',
        'Internship Role': 'AI Engineer Intern',
        'Application ID': 'AM-APP-1001',
        'Application Date': '15/09/2026',
        'Internship Duration': '3 Months',
        'Start Date': '15/09/2026',
        'Joining Date': '15/09/2026',
        'Employee ID': 'AM4827',
        'Employee Password': 'AMx7P9k2Q',
        'Internship Portal Link': 'https://www.antimatrix.co.in/internship',
        'Company Email': 'info@antimatrix.co.in',
        'Website': 'www.antimatrix.co.in',
        'employee_name': 'Rahul Kumar',
        'employee_id': 'AM4827',
        'employee_password': 'AMx7P9k2Q',
        'temp_password': 'AMx7P9k2Q',
        'job_title': 'AI Engineer Intern',
        'application_id': 'AM-APP-1001',
        'internship_duration': '3 Months',
        'start_date': '15/09/2026',
        'joining_date': '15/09/2026',
        'portal_url': 'https://www.antimatrix.co.in/internship',
        'portal_link': 'https://www.antimatrix.co.in/internship',
        'company_email': 'info@antimatrix.co.in',
        'website': 'www.antimatrix.co.in'
    }

    tmpl = EmailTemplate.query.filter_by(template_type=template_type).first()
    if template_type == 'application_successful':
        raw_subject = tmpl.subject if tmpl and tmpl.subject else DEFAULT_APPLICATION_SUCCESSFUL_SUBJECT
        raw_body = tmpl.body if tmpl and tmpl.body else DEFAULT_APPLICATION_SUCCESSFUL_BODY
    elif template_type == 'joining_credentials':
        raw_subject = tmpl.subject if tmpl and tmpl.subject else DEFAULT_JOINING_SUBJECT
        raw_body = tmpl.body if tmpl and tmpl.body else DEFAULT_JOINING_BODY
    else:
        raw_subject = tmpl.subject if tmpl and tmpl.subject else DEFAULT_OFFER_LETTER_SUBJECT
        raw_body = tmpl.body if tmpl and tmpl.body else DEFAULT_OFFER_LETTER_BODY

    subject = replace_variables(raw_subject, sample_variables)
    body_text = replace_variables(raw_body, sample_variables)
    body_html = markdown_to_html_email(body_text, title=subject)

    return {
        'subject': subject,
        'body_text': body_text,
        'body_html': body_html
    }


def send_test_email(template_type, recipient_email):
    """
    Sends a sample test email to the specified recipient.
    Does NOT create or modify any live application or employee records.
    """
    preview = render_sample_email_preview(template_type)
    test_subject = f"[TEST PREVIEW] {preview['subject']}"
    
    success, msg, provider_id = send_brevo_email(
        recipient_email=recipient_email,
        recipient_name=recipient_email,
        subject=test_subject,
        body_text=preview['body_text'],
        body_html=preview['body_html']
    )

    # Log test send
    now_utc = datetime.now(timezone.utc)
    try:
        email_log = EmailLog(
            recipient_email=recipient_email,
            template_type='test',
            reference_id=f"TEST_{template_type.upper()}",
            subject=test_subject,
            body_preview=preview['body_text'][:200] if preview['body_text'] else '',
            status='SENT' if success else 'FAILED',
            provider_message_id=provider_id,
            error_message=None if success else msg,
            has_attachment=False,
            sent_at=now_utc
        )
        db.session.add(email_log)
        db.session.commit()
    except Exception as db_err:
        db.session.rollback()
        if current_app:
            current_app.logger.error(f"Database error saving test EmailLog: {str(db_err)}")

    return success, msg
