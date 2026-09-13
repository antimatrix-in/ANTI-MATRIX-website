import json
from datetime import datetime, timezone
from . import db


class InternshipBenefit(db.Model):
    __tablename__ = 'internship_benefits'

    id = db.Column(db.Integer, primary_key=True)
    duration = db.Column(db.String(50), nullable=False, index=True)  # '1_month', '3_months'
    title = db.Column(db.String(100), nullable=False)  # e.g., '1-Month Internship', '3-Month Internship'
    subtitle = db.Column(db.String(255), nullable=True)  # Optional helper subtitle
    benefits = db.Column(db.Text, nullable=False)  # JSON-encoded array of benefit item strings
    badge_text = db.Column(db.String(50), nullable=True)  # e.g. 'Fast Track', 'Comprehensive'
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    display_order = db.Column(db.Integer, default=0, nullable=False)

    # Optional relationship to support future job-specific benefit overrides while keeping default shared
    job_posting_id = db.Column(db.Integer, db.ForeignKey('job_postings.id', ondelete='CASCADE'), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    job_posting = db.relationship('JobPosting', backref=db.backref('internship_benefits', lazy=True, cascade='all, delete-orphan'))

    def get_benefits_list(self):
        """
        Parses the stored benefits text into a clean list of strings.
        Handles JSON arrays or fallback newline-separated strings safely.
        """
        if not self.benefits:
            return []
        
        text = self.benefits.strip()
        if text.startswith('[') and text.endswith(']'):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Fallback for plain lines
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return lines

    def set_benefits_list(self, items):
        """
        Serializes a list of benefit strings into JSON format.
        Strips empty entries and whitespace.
        """
        if isinstance(items, str):
            # Parse newline-separated string
            items = [line.strip() for line in items.split('\n') if line.strip()]
        elif not isinstance(items, (list, tuple)):
            items = []
        
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        self.benefits = json.dumps(cleaned, ensure_ascii=False)

    @property
    def duration_label(self):
        """Human-friendly duration display label."""
        normalized = (self.duration or '').strip().lower()
        if normalized in ['1_month', '1 month', '1']:
            return '1 Month'
        elif normalized in ['3_months', '3 months', '3']:
            return '3 Months'
        return self.duration or 'Internship'

    @property
    def duration_clean(self):
        """Normalized duration key for queries/routing."""
        normalized = (self.duration or '').strip().lower()
        if '1' in normalized:
            return '1_month'
        elif '3' in normalized:
            return '3_months'
        return normalized

    @property
    def items_count(self):
        """Returns the number of benefit points configured."""
        return len(self.get_benefits_list())

    def __repr__(self):
        return f"<InternshipBenefit id={self.id} duration='{self.duration}' title='{self.title}' items={self.items_count} active={self.is_active}>"
