import logging
from models import db, InternshipBenefit
from config import normalize_internship_duration

logger = logging.getLogger('anti_matrix')

DEFAULT_1_MONTH_BENEFITS = [
    'Digital internship offer letter',
    'Intern employee ID',
    'Intern working portal access',
    'Weekly assigned tasks',
    'Practical hands-on experience',
    'Internship completion certificate',
    'Performance-based stipend up to ₹5,000'
]

DEFAULT_3_MONTH_BENEFITS = [
    'Digital internship offer letter',
    'Intern employee ID',
    'Intern working portal access',
    'Structured project-based assignments',
    'Practical hands-on industry experience',
    'Regular task and performance evaluation',
    'Internship completion certificate',
    'Performance-based benefits/stipend as configured'
]


def ensure_default_internship_benefits():
    """
    Safely seeds default 1-Month and 3-Month internship benefits ONLY IF no records exist.
    DATA SAFETY: Never deletes, resets, or overwrites existing records.
    """
    try:
        count = InternshipBenefit.query.count()
        if count > 0:
            return

        logger.info("Initializing default internship benefits configuration...")

        b1 = InternshipBenefit(
            duration='1_month',
            title='1-Month Internship',
            subtitle='Accelerated hands-on program with core industry deliverables.',
            badge_text='Fast-Track',
            is_active=True,
            display_order=1,
            job_posting_id=None
        )
        b1.set_benefits_list(DEFAULT_1_MONTH_BENEFITS)
        db.session.add(b1)

        b3 = InternshipBenefit(
            duration='3_months',
            title='3-Month Internship',
            subtitle='In-depth project development with structured evaluation and mentorship.',
            badge_text='Comprehensive',
            is_active=True,
            display_order=2,
            job_posting_id=None
        )
        b3.set_benefits_list(DEFAULT_3_MONTH_BENEFITS)
        db.session.add(b3)

        db.session.commit()
        logger.info("Default internship benefits initialized successfully.")
    except Exception as e:
        db.session.rollback()
        logger.warning(f"Note on internship benefits auto-init: {str(e)}")


def get_active_internship_benefits(job_id=None):
    """
    Retrieves active benefits for 1-month and 3-month durations.
    Prioritizes job-specific configuration if present, otherwise shared global config.
    Falls back gracefully to safe defaults if not found in database.
    """
    ensure_default_internship_benefits()

    # Query all active benefits
    query = InternshipBenefit.query.filter_by(is_active=True)
    if job_id:
        # Job specific or shared (job_posting_id is null)
        records = query.filter(
            (InternshipBenefit.job_posting_id == job_id) | (InternshipBenefit.job_posting_id.is_(None))
        ).order_by(InternshipBenefit.job_posting_id.desc(), InternshipBenefit.display_order.asc()).all()
    else:
        records = query.filter(InternshipBenefit.job_posting_id.is_(None)).order_by(InternshipBenefit.display_order.asc()).all()

    benefits_map = {}
    for rec in records:
        key = rec.duration_clean
        # Only take first matching (prioritizes job-specific if present)
        if key not in benefits_map:
            benefits_map[key] = {
                'id': rec.id,
                'duration': rec.duration,
                'duration_label': rec.duration_label,
                'duration_clean': rec.duration_clean,
                'title': rec.title,
                'subtitle': rec.subtitle or '',
                'badge_text': rec.badge_text or '',
                'benefits': rec.get_benefits_list(),
                'items_count': rec.items_count,
                'is_active': rec.is_active,
                'is_fallback': False
            }

    # Fallback for 1_month if missing
    if '1_month' not in benefits_map:
        benefits_map['1_month'] = {
            'id': None,
            'duration': '1_month',
            'duration_label': '1 Month',
            'duration_clean': '1_month',
            'title': '1-Month Internship',
            'subtitle': 'Accelerated hands-on program with core industry deliverables.',
            'badge_text': 'Fast-Track',
            'benefits': list(DEFAULT_1_MONTH_BENEFITS),
            'items_count': len(DEFAULT_1_MONTH_BENEFITS),
            'is_active': True,
            'is_fallback': True
        }

    # Fallback for 3_months if missing
    if '3_months' not in benefits_map:
        benefits_map['3_months'] = {
            'id': None,
            'duration': '3_months',
            'duration_label': '3 Months',
            'duration_clean': '3_months',
            'title': '3-Month Internship',
            'subtitle': 'In-depth project development with structured evaluation and mentorship.',
            'badge_text': 'Comprehensive',
            'benefits': list(DEFAULT_3_MONTH_BENEFITS),
            'items_count': len(DEFAULT_3_MONTH_BENEFITS),
            'is_active': True,
            'is_fallback': True
        }

    return benefits_map


def save_or_update_internship_benefit(duration, title, benefits_items, subtitle=None, badge_text=None, is_active=True, job_posting_id=None, benefit_id=None):
    """
    Saves or updates an internship benefit record.
    Guarantees duplicate prevention: if an entry already exists for this duration/job,
    it updates the existing record instead of creating a duplicate.
    """
    norm_duration = normalize_internship_duration(duration) or ('3_months' if '3' in str(duration) else '1_month')
    
    # Clean benefit items
    if isinstance(benefits_items, str):
        cleaned_items = [line.strip() for line in benefits_items.split('\n') if line.strip()]
    elif isinstance(benefits_items, (list, tuple)):
        cleaned_items = [str(it).strip() for it in benefits_items if str(it).strip()]
    else:
        cleaned_items = []

    benefit = None
    if benefit_id:
        benefit = db.session.get(InternshipBenefit, benefit_id)

    # Check for existing record to prevent duplicates
    if not benefit:
        query = InternshipBenefit.query.filter_by(duration=norm_duration)
        if job_posting_id:
            query = query.filter_by(job_posting_id=job_posting_id)
        else:
            query = query.filter(InternshipBenefit.job_posting_id.is_(None))
        benefit = query.first()

    is_new = False
    if not benefit:
        benefit = InternshipBenefit(
            duration=norm_duration,
            job_posting_id=job_posting_id,
            display_order=1 if norm_duration == '1_month' else 2
        )
        db.session.add(benefit)
        is_new = True

    # Update fields
    benefit.duration = norm_duration
    benefit.title = (title or '').strip() or ('1-Month Internship' if norm_duration == '1_month' else '3-Month Internship')
    benefit.subtitle = (subtitle or '').strip()
    benefit.badge_text = (badge_text or '').strip()
    benefit.is_active = bool(is_active)
    benefit.set_benefits_list(cleaned_items)

    db.session.commit()
    return benefit, is_new
