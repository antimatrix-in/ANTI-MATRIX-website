import logging
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger(__name__)

GST_RATE_PERCENT = Decimal('18.00')


def calculate_payment_total(base_amount) -> dict:
    """
    Authoritative, reusable GST calculation using decimal-safe currency arithmetic.
    Applies 18% GST to any base_amount.
    
    Formula:
        gst_amount = round(base_amount * 18 / 100, 2)
        total_amount = base_amount + gst_amount
        
    Returns:
        {
            'base_amount': float,
            'gst_rate': 18.0,
            'gst_amount': float,
            'total_amount': float,
            'formatted_base': str (e.g. '₹199.00'),
            'formatted_gst': str (e.g. '₹35.82'),
            'formatted_total': str (e.g. '₹234.82')
        }
    """
    if base_amount is None:
        base_amount = 0

    try:
        b = Decimal(str(base_amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:
        b = Decimal('0.00')

    if b <= Decimal('0.00'):
        return {
            'base_amount': 0.0,
            'gst_rate': 18.0,
            'gst_amount': 0.0,
            'total_amount': 0.0,
            'amount_paise': 0,
            'formatted_base': '₹0.00',
            'formatted_gst': '₹0.00',
            'formatted_total': '₹0.00',
        }

    gst = (b * GST_RATE_PERCENT / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    tot = (b + gst).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    return {
        'base_amount': float(b),
        'gst_rate': 18.0,
        'gst_amount': float(gst),
        'total_amount': float(tot),
        'amount_paise': int(tot * 100),
        'formatted_base': f"₹{b:.2f}",
        'formatted_gst': f"₹{gst:.2f}",
        'formatted_total': f"₹{tot:.2f}",
    }
