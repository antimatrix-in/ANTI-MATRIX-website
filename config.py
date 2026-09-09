import os
import socket
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Centralized Server-Side Application Base Fee Mapping (Enforced strictly on server)
INTERNSHIP_FEES = {
    '1_month': 199,
    '3_months': 399,
    '1 Month': 199,
    '3 Months': 399
}

INTERNSHIP_PRICING = {
    '1_month': {
        'duration_key': '1_month',
        'label': '1 Month',
        'base_amount': 199.00,
        'gst_rate': 18.0,
        'gst_amount': 35.82,
        'total_amount': 234.82,
        'amount_inr': 234.82,
        'amount_paise': 23482,
        'formatted': '₹199 + 18% GST (₹234.82)',
        'formatted_base': '₹199.00',
        'formatted_gst': '₹35.82',
        'formatted_total': '₹234.82'
    },
    '3_months': {
        'duration_key': '3_months',
        'label': '3 Months',
        'base_amount': 399.00,
        'gst_rate': 18.0,
        'gst_amount': 71.82,
        'total_amount': 470.82,
        'amount_inr': 470.82,
        'amount_paise': 47082,
        'formatted': '₹399 + 18% GST (₹470.82)',
        'formatted_base': '₹399.00',
        'formatted_gst': '₹71.82',
        'formatted_total': '₹470.82'
    },
    '1 Month': {
        'duration_key': '1_month',
        'label': '1 Month',
        'base_amount': 199.00,
        'gst_rate': 18.0,
        'gst_amount': 35.82,
        'total_amount': 234.82,
        'amount_inr': 234.82,
        'amount_paise': 23482,
        'formatted': '₹199 + 18% GST (₹234.82)',
        'formatted_base': '₹199.00',
        'formatted_gst': '₹35.82',
        'formatted_total': '₹234.82'
    },
    '3 Months': {
        'duration_key': '3_months',
        'label': '3 Months',
        'base_amount': 399.00,
        'gst_rate': 18.0,
        'gst_amount': 71.82,
        'total_amount': 470.82,
        'amount_inr': 470.82,
        'amount_paise': 47082,
        'formatted': '₹399 + 18% GST (₹470.82)',
        'formatted_base': '₹399.00',
        'formatted_gst': '₹71.82',
        'formatted_total': '₹470.82'
    }
}

# Indian States and Dependent Cities Mapping
INDIA_STATES_AND_CITIES = {
    "Andhra Pradesh": ["Visakhapatnam", "Vijayawada", "Guntur", "Nellore", "Kurnool", "Rajahmundry", "Tirupati", "Kakinada", "Kadapa", "Anantapur", "Eluru", "Ongole", "Other"],
    "Arunachal Pradesh": ["Itanagar", "Naharlagun", "Pasighat", "Tawang", "Ziro", "Bomdila", "Other"],
    "Assam": ["Guwahati", "Silchar", "Dibrugarh", "Jorhat", "Nagaon", "Tinsukia", "Tezpur", "Bongaigaon", "Other"],
    "Bihar": ["Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Purnia", "Darbhanga", "Bihar Sharif", "Arrah", "Begusarai", "Katihar", "Other"],
    "Chhattisgarh": ["Raipur", "Bhilai", "Bilaspur", "Korba", "Durg", "Rajnandgaon", "Jagdalpur", "Ambikapur", "Other"],
    "Goa": ["Panaji", "Margao", "Vasco da Gama", "Mapusa", "Ponda", "Other"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Bhavnagar", "Jamnagar", "Junagadh", "Gandhinagar", "Anand", "Navsari", "Morbi", "Bharuch", "Other"],
    "Haryana": ["Gurugram", "Faridabad", "Panipat", "Ambala", "Yamunanagar", "Rohtak", "Hisar", "Karnal", "Sonipat", "Panchkula", "Other"],
    "Himachal Pradesh": ["Shimla", "Dharamshala", "Solan", "Mandi", "Kullu", "Manali", "Baddi", "Bilaspur", "Hamirpur", "Other"],
    "Jharkhand": ["Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Deoghar", "Hazaribagh", "Giridih", "Ramgarh", "Other"],
    "Karnataka": ["Bengaluru", "Mysuru", "Hubballi-Dharwad", "Mangaluru", "Belagavi", "Davanagere", "Ballari", "Kalaburagi", "Shivamogga", "Tumakuru", "Udupi", "Hassan", "Other"],
    "Kerala": ["Thiruvananthapuram", "Kochi", "Kozhikode", "Thrissur", "Kollam", "Palakkad", "Alappuzha", "Kannur", "Kottayam", "Malappuram", "Other"],
    "Madhya Pradesh": ["Bhopal", "Indore", "Jabalpur", "Gwalior", "Ujjain", "Sagar", "Dewas", "Satna", "Ratlam", "Rewa", "Other"],
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Thane", "Nashik", "Kalyan-Dombivli", "Vasai-Virar", "Chhatrapati Sambhaji Nagar (Aurangabad)", "Navi Mumbai", "Solapur", "Kolhapur", "Amravati", "Nanded", "Other"],
    "Manipur": ["Imphal", "Churachandpur", "Thoubal", "Kakching", "Ukhrul", "Other"],
    "Meghalaya": ["Shillong", "Tura", "Jowai", "Nongpoh", "Baghmara", "Other"],
    "Mizoram": ["Aizawl", "Lunglei", "Champhai", "Serchhip", "Kolasib", "Other"],
    "Nagaland": ["Kohima", "Dimapur", "Mokokchung", "Tuensang", "Wokha", "Other"],
    "Odisha": ["Bhubaneswar", "Cuttack", "Rourkela", "Berhampur", "Sambalpur", "Puri", "Balasore", "Bhadrak", "Other"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Bathinda", "Mohali", "Hoshiarpur", "Pathankot", "Other"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Kota", "Bikaner", "Ajmer", "Udaipur", "Bhilwara", "Alwar", "Sikar", "Sri Ganganagar", "Other"],
    "Sikkim": ["Gangtok", "Namchi", "Geyzing", "Mangan", "Rangpo", "Other"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem", "Tirunelveli", "Tiruppur", "Vellore", "Erode", "Thoothukudi", "Dindigul", "Thanjavur", "Nagercoil", "Kanchipuram", "Hosur", "Other"],
    "Telangana": ["Hyderabad", "Warangal", "Nizamabad", "Karimnagar", "Ramagundam", "Khammam", "Mahbubnagar", "Nalgonda", "Adilabad", "Siddipet", "Other"],
    "Tripura": ["Agartala", "Udaipur", "Dharmanagar", "Kailashahar", "Belonia", "Other"],
    "Uttar Pradesh": ["Lucknow", "Kanpur", "Varanasi", "Agra", "Prayagraj", "Noida", "Greater Noida", "Ghaziabad", "Meerut", "Bareilly", "Aligarh", "Moradabad", "Saharanpur", "Gorakhpur", "Jhansi", "Mathura", "Other"],
    "Uttarakhand": ["Dehradun", "Haridwar", "Roorkee", "Haldwani", "Rudrapur", "Rishikesh", "Nainital", "Kashipur", "Other"],
    "West Bengal": ["Kolkata", "Howrah", "Durgapur", "Asansol", "Siliguri", "Bardhaman", "Kharagpur", "Malda", "Haldia", "Other"],
    "Andaman and Nicobar Islands": ["Port Blair", "Other"],
    "Chandigarh": ["Chandigarh", "Other"],
    "Dadra and Nagar Haveli and Daman and Diu": ["Daman", "Diu", "Silvassa", "Other"],
    "Delhi": ["New Delhi", "Central Delhi", "North Delhi", "South Delhi", "East Delhi", "West Delhi", "Dwarka", "Rohini", "Other"],
    "Jammu and Kashmir": ["Srinagar", "Jammu", "Anantnag", "Baramulla", "Udhampur", "Kathua", "Sopore", "Other"],
    "Ladakh": ["Leh", "Kargil", "Other"],
    "Lakshadweep": ["Kavaratti", "Agatti", "Amini", "Andrott", "Other"],
    "Puducherry": ["Puducherry", "Karaikal", "Mahe", "Yanam", "Other"]
}

# Education Levels
EDUCATION_LEVELS = [
    "High School / 12th Standard",
    "Diploma",
    "Bachelor's Degree",
    "Master's Degree",
    "Doctorate / Ph.D",
    "Other"
]

# Common Degrees
COMMON_DEGREES = [
    "B.Tech / B.E. (Bachelor of Technology / Engineering)",
    "B.Sc (Bachelor of Science)",
    "BCA (Bachelor of Computer Applications)",
    "B.Com (Bachelor of Commerce)",
    "BBA (Bachelor of Business Administration)",
    "M.Tech / M.E. (Master of Technology / Engineering)",
    "M.Sc (Master of Science)",
    "MCA (Master of Computer Applications)",
    "MBA (Master of Business Administration)",
    "Diploma in Engineering",
    "Other"
]

# Available Graduation Years (Up to 2029 maximum)
GRADUATION_YEARS = [2022, 2023, 2024, 2025, 2026, 2027, 2028, 2029]


def normalize_internship_duration(val: str) -> str:
    """
    Validates and normalizes duration input string.
    Only allows:
      - 1 Month ('1_month', '1 month', '1') -> '1_month'
      - 3 Months ('3_months', '3 months', '3') -> '3_months'
    Rejects unsupported values (e.g. '6 Months', '12 Months', '₹1', etc.) by returning None.
    """
    if not val:
        return None
    cleaned = str(val).strip().lower().replace('-', '_').replace(' ', '_')
    if cleaned in ['1_month', '1', 'month_1', '1month']:
        return '1_month'
    elif cleaned in ['3_months', '3', '3_month', 'month_3', '3months']:
        return '3_months'
    return None


def get_internship_fee(duration: str) -> int:
    """Retrieve exact server-calculated base fee in INR for given duration."""
    norm = normalize_internship_duration(duration)
    if norm:
        return INTERNSHIP_FEES.get(norm, 199)
    if duration in INTERNSHIP_FEES:
        return INTERNSHIP_FEES[duration]
    return 199


def get_internship_fee_breakdown(duration: str) -> dict:
    """
    Retrieve exact server-calculated base, 18% GST, and total fee breakdown.
    Strictly enforces 18% GST calculation using decimal-safe arithmetic.
    1 Month: Base ₹199.00, GST ₹35.82, Total ₹234.82
    3 Months: Base ₹399.00, GST ₹71.82, Total ₹470.82
    """
    from services.payment_service import calculate_payment_total
    norm = normalize_internship_duration(duration) or '1_month'
    base = INTERNSHIP_FEES.get(norm, 199)
    res = calculate_payment_total(base)
    res['duration_key'] = norm
    res['duration_label'] = '1 Month' if norm == '1_month' else '3 Months'
    return res


import urllib.parse
import socket


def normalize_database_url(raw_url: str) -> str:
    """
    Safely parses and normalizes database connection strings for SQLAlchemy & Supabase.
    - Normalizes 'postgres://' to 'postgresql://'.
    - Handles unencoded special characters in passwords (e.g. '@', ':', '#', '%', '+').
    - Handles Supabase IPv6 direct URLs by routing through IPv4 Supabase pooler if direct IPv4 DNS resolution is unavailable.
    - Prevents double-encoding.
    """
    if not raw_url:
        return raw_url
    url = raw_url.strip()
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    if not url.startswith('postgresql://'):
        return url
    
    scheme, remainder = url.split('://', 1)
    if '@' in remainder:
        # Split on the LAST '@' to safely isolate host[:port]/database from user:password
        auth_part, host_part = remainder.rsplit('@', 1)
        if ':' in auth_part:
            username, password = auth_part.split(':', 1)
        else:
            username, password = auth_part, ''
        
        # Unquote first to avoid double-encoding pre-encoded components
        username = urllib.parse.unquote(username)
        password = urllib.parse.unquote(password)
        
        host = host_part
        port = 5432
        db_and_query = 'postgres'
        
        if '/' in host_part:
            host_and_port, db_and_query = host_part.split('/', 1)
        else:
            host_and_port = host_part
            
        if ':' in host_and_port:
            host, port_str = host_and_port.split(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 5432
        else:
            host = host_and_port

        # Supabase Direct IPv6 to Pooler IPv4 translation fallback:
        if host.startswith('db.') and host.endswith('.supabase.co'):
            project_ref = host[3:-len('.supabase.co')]
            resolves = False
            try:
                orig_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(3.0)
                socket.getaddrinfo(host, port)
                resolves = True
            except Exception:
                resolves = False
            finally:
                try:
                    socket.setdefaulttimeout(orig_timeout)
                except Exception:
                    pass
            
            if not resolves:
                host = 'aws-0-ap-south-1.pooler.supabase.com'
                if not username.endswith(f'.{project_ref}'):
                    username = f"{username}.{project_ref}" if username else f"postgres.{project_ref}"

        # RFC 3986 percent-encode user and password
        encoded_username = urllib.parse.quote(username, safe='')
        encoded_password = urllib.parse.quote(password, safe='')
        
        url = f"{scheme}://{encoded_username}:{encoded_password}@{host}:{port}/{db_and_query}"
    return url


def get_database_uri(force_production_check=False):
    """
    Retrieves and normalizes the database URI.
    Supports PostgreSQL (Supabase) and SQLite.
    In production environments, raises RuntimeError if DATABASE_URL is not set.
    """
    raw_url = os.environ.get('DATABASE_URL', '').strip()
    if raw_url:
        return normalize_database_url(raw_url)

    # Check if production is explicitly configured or running on Render
    is_prod = (
        force_production_check
        or os.environ.get('FLASK_CONFIG', '').lower() == 'production'
        or os.environ.get('FLASK_ENV', '').lower() == 'production'
        or os.environ.get('RENDER', '').lower() == 'true'
    )
    if is_prod and not raw_url:
        raise RuntimeError(
            "CRITICAL CONFIGURATION ERROR: DATABASE_URL environment variable is missing in Production. "
            "Production on Render requires a valid Supabase PostgreSQL connection string."
        )

    return f"sqlite:///{os.path.join(BASE_DIR, 'antimatrix.db')}"



class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'antimatrix-dev-secret-key-change-in-prod-2026')
    
    # Database configuration with postgres:// to postgresql:// normalization
    SQLALCHEMY_DATABASE_URI = get_database_uri(force_production_check=False)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # SQLAlchemy Engine & Connection Pool Options (Optimized for Supabase Pooler / Supavisor & Web Services)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Session & Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    # Application settings
    APP_NAME = 'Anti-Matrix'
    CONTACT_EMAIL = os.environ.get('CONTACT_EMAIL', 'contact@anti-matrix.com')
    CAREERS_EMAIL = os.environ.get('CAREERS_EMAIL', 'careers@anti-matrix.com')

    # File Uploads (Resumes and Sensitive Identity Documents)
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads', 'resumes')
    UPLOAD_FOLDER_RESUMES = os.path.join(BASE_DIR, 'uploads', 'resumes')
    UPLOAD_FOLDER_DOCUMENTS = os.path.join(BASE_DIR, 'uploads', 'documents')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max limit
    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}
    ALLOWED_RESUME_EXTENSIONS = {'pdf', 'doc', 'docx'}
    ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}

    # Cashfree Payment Gateway Settings (Render & Environment Compatible)
    CASHFREE_APP_ID = (os.environ.get('CASHFREE_APP_ID', '').strip() or os.environ.get('CASHFREE_CLIENT_ID', '').strip())
    CASHFREE_SECRET_KEY = (os.environ.get('CASHFREE_SECRET_KEY', '').strip() or os.environ.get('CASHFREE_CLIENT_SECRET', '').strip())
    CASHFREE_CLIENT_ID = CASHFREE_APP_ID
    CASHFREE_CLIENT_SECRET = CASHFREE_SECRET_KEY
    CASHFREE_ENV = (os.environ.get('CASHFREE_ENV', '').strip() or os.environ.get('CASHFREE_ENVIRONMENT', '').strip() or 'sandbox').lower()
    CASHFREE_ENVIRONMENT = CASHFREE_ENV
    CASHFREE_API_VERSION = (os.environ.get('CASHFREE_API_VERSION', '').strip() or '2025-01-01')
    CASHFREE_RETURN_URL = os.environ.get('CASHFREE_RETURN_URL', '').strip()
    CASHFREE_WEBHOOK_URL = os.environ.get('CASHFREE_WEBHOOK_URL', '').strip()

    # Brevo (Sendinblue) Email Service Settings
    BREVO_API_KEY = os.environ.get('BREVO_API_KEY', '').strip()
    BREVO_SENDER_EMAIL = os.environ.get('BREVO_SENDER_EMAIL', os.environ.get('SENDER_EMAIL', 'info@antimatrix.co.in')).strip()
    BREVO_SENDER_NAME = os.environ.get('BREVO_SENDER_NAME', 'Anti Matrix').strip()

    # SMTP Relay Settings (Brevo SMTP or custom relay)
    SMTP_SERVER = os.environ.get('SMTP_SERVER', '').strip()
    _smtp_port_raw = os.environ.get('SMTP_PORT', '587').strip()
    SMTP_PORT = int(_smtp_port_raw) if _smtp_port_raw.isdigit() else 587
    SMTP_USER = os.environ.get('SMTP_USER', '').strip()
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '').strip()
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'info@antimatrix.co.in').strip()

    # Payment Test Mode Switch (Defaults to false so real Cashfree Sandbox is used)
    PAYMENT_TEST_MODE = os.environ.get('PAYMENT_TEST_MODE', 'false').lower() in ('true', '1', 'yes')

    # Application Public URL (used for OAuth redirects & notifications)
    APP_URL = os.environ.get('APP_URL', 'http://localhost:5000').rstrip('/')

    # Google OAuth 2.0 Settings
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()
    GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', '').strip()

    # GitHub OAuth Settings
    GITHUB_CLIENT_ID = os.environ.get('GITHUB_CLIENT_ID', '').strip()
    GITHUB_CLIENT_SECRET = os.environ.get('GITHUB_CLIENT_SECRET', '').strip()
    GITHUB_REDIRECT_URI = os.environ.get('GITHUB_REDIRECT_URI', '').strip()


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    PAYMENT_TEST_MODE = os.environ.get('PAYMENT_TEST_MODE', 'false').lower() in ('true', '1', 'yes')


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() in ('true', '1')
    PAYMENT_TEST_MODE = os.environ.get('PAYMENT_TEST_MODE', 'false').lower() in ('true', '1', 'yes')
    
    # In production, pool sizing is added for PostgreSQL
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': 10,
        'max_overflow': 20,
    }


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    DEBUG = True
    PAYMENT_TEST_MODE = False
    CASHFREE_ENV = 'test'
    CASHFREE_ENVIRONMENT = 'test'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig if os.environ.get('FLASK_ENV') != 'production' else ProductionConfig
}


