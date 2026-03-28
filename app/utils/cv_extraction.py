"""
CV text extraction and data parsing utilities.

Handles PDF text extraction and keyword-based parsing for:
- Email addresses
- Polish phone numbers
- Language names and levels
- Skills and keywords
"""

import re
from typing import Optional, List, Dict, Any


class ExtractedCVData:
    """Structured CV extraction results."""

    def __init__(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        languages: Optional[List[Dict[str, str]]] = None,
        skills: Optional[List[str]] = None,
    ):
        self.email = email
        self.phone = phone
        self.languages = languages or []
        self.skills = skills or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB storage."""
        return {
            "email": self.email,
            "phone": self.phone,
            "languages": self.languages,
            "skills": self.skills,
        }


# ─── Polish Language Names ────────────────────────────────────────
POLISH_LANGUAGE_NAMES = {
    "angielski": "English",
    "english": "English",
    "niemiecki": "German",
    "deutsch": "German",
    "german": "German",
    "francuski": "French",
    "français": "French",
    "french": "French",
    "rosyjski": "Russian",
    "русский": "Russian",
    "russian": "Russian",
    "hiszpański": "Spanish",
    "español": "Spanish",
    "spanish": "Spanish",
    "włoski": "Italian",
    "italiano": "Italian",
    "italian": "Italian",
    "polski": "Polish",
    "dutch": "Dutch",
    "chiński": "Chinese",
    "mandarin": "Chinese",
    "japoński": "Japanese",
    "koreański": "Korean",
    "português": "Portuguese",
    "portuguese": "Portuguese",
    "turecki": "Turkish",
    "turkish": "Turkish",
    "arabski": "Arabic",
    "svenska": "Swedish",
    "swedish": "Swedish",
    "norsk": "Norwegian",
    "norwegian": "Norwegian",
    "dansk": "Danish",
    "finnish": "Finnish",
}

# ─── Language Level Mapping ──────────────────────────────────────
LANGUAGE_LEVEL_PATTERNS = {
    "A1": r"\bA1\b",
    "A2": r"\bA2\b",
    "B1": r"\bB1\b",
    "B2": r"\bB2\b",
    "C1": r"\bC1\b",
    "C2": r"\bC2\b",
    "natywny": r"\b(natywny|native|ojczysty|fluent)\b",
    "zaawansowany": r"\b(zaawansowany|advanced|intermediate)\b",
}

# ─── Common IT & Soft Skills Keywords ──────────────────────────────
COMMON_SKILLS = [
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "vue",
    "angular",
    "nodejs",
    "node.js",
    "express",
    "fastapi",
    "django",
    "sql",
    "mongodb",
    "postgresql",
    "mysql",
    "docker",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "git",
    "github",
    "gitlab",
    "jira",
    "leadership",
    "communication",
    "teamwork",
    "problem-solving",
    "analytical",
    "project management",
    "agile",
    "scrum",
    "html",
    "css",
    "sass",
    "webpack",
    "rest",
    "api",
    "microservices",
    "linux",
    "windows",
    "macos",
    "bash",
    "shell",
    "salesforce",
    "sap",
    "excel",
    "powerpoint",
    "word",
    "powerbi",
    "tableau",
    "jenkins",
    "gitlab-ci",
    "ci/cd",
    "testing",
    "junit",
    "pytest",
    "selenium",
    "golang",
    "rust",
    "c++",
    "c#",
    ".net",
    "scala",
    "kotlin",
    "r",
    "matlab",
]


def extract_text_from_pdf(file_bytes: bytes) -> Optional[str]:
    """
    Extract text from PDF bytes using PyPDF2.

    Args:
        file_bytes: Raw PDF file content

    Returns:
        Extracted text or None if extraction fails
    """
    try:
        from PyPDF2 import PdfReader
        from io import BytesIO

        pdf_file = BytesIO(file_bytes)
        reader = PdfReader(pdf_file)

        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"

        return text if text.strip() else None

    except Exception as e:
        # If PyPDF2 fails, try pdfplumber as fallback
        try:
            import pdfplumber
            from io import BytesIO

            pdf_file = BytesIO(file_bytes)
            with pdfplumber.open(pdf_file) as pdf:
                text = ""
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
                return text if text.strip() else None
        except Exception:
            return None


def extract_email(text: str) -> Optional[str]:
    """
    Extract first email address from text using regex.

    Pattern matches: name@domain.extension

    Args:
        text: Extracted PDF text

    Returns:
        Email address or None
    """
    if not text:
        return None

    # Email pattern: basic but effective for CVs
    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    match = re.search(email_pattern, text)

    return match.group(0) if match else None


def extract_phone(text: str) -> Optional[str]:
    """
    Extract Polish phone number from text.

    Supports:
    - +48 XXX XXX XXX format
    - +48XXXXXXXXX format (no spaces)
    - XXX XXX XXX format (9 digits)
    - XXXXXXXXX format (9 digits, no spaces)

    Args:
        text: Extracted PDF text

    Returns:
        Formatted phone number or None
    """
    if not text:
        return None

    # Match various Polish phone number formats
    patterns = [
        r"\+48\s?\d{3}\s?\d{3}\s?\d{3}",  # +48 XXX XXX XXX or +48XXXXXXXXX
        r"\+48\d{9}",  # +48XXXXXXXXX (no spaces)
        r"(?:^|\D)\d{3}\s?\d{3}\s?\d{3}(?:\D|$)",  # XXX XXX XXX or XXXXXXXXX
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            phone = match.group(0).strip()
            # Normalize to +48 XXX XXX XXX format
            phone = re.sub(r"\D", "", phone)
            if len(phone) >= 9:
                phone = phone[-9:] if not phone.startswith("48") else phone
                if not phone.startswith("48"):
                    phone = "48" + phone
                return f"+{phone[:2]} {phone[2:5]} {phone[5:8]} {phone[8:11]}"

    return None


def extract_languages(text: str) -> List[Dict[str, str]]:
    """
    Extract language names and levels from text.

    Looks for Polish/English language names followed by level indicators (A1-C2).
    Falls back to "B1" if no level is found.

    Args:
        text: Extracted PDF text

    Returns:
        List of dicts: [{"name": "Polish", "level": "B1"}, ...]
    """
    if not text:
        return []

    languages_found: Dict[str, str] = {}  # {lang_name: best_level_found}
    text_lower = text.lower()

    # Find all language mentions
    for lang_key, lang_english in POLISH_LANGUAGE_NAMES.items():
        if lang_key in text_lower:
            if lang_english not in languages_found:
                languages_found[lang_english] = "B1"  # default level

            # Look for level indicators near the language name
            # Find position of language mention
            idx = text_lower.find(lang_key)
            if idx != -1:
                # Extract context around language mention (±50 chars)
                context_start = max(0, idx - 50)
                context_end = min(len(text), idx + len(lang_key) + 50)
                context = text[context_start:context_end]

                # Check for level indicators
                for level, level_pattern in LANGUAGE_LEVEL_PATTERNS.items():
                    if re.search(level_pattern, context, re.IGNORECASE):
                        languages_found[lang_english] = level
                        break

    return [
        {"jezyk": lang, "poziom": level}
        for lang, level in languages_found.items()
    ]


def extract_skills(text: str, limit: int = 15) -> List[str]:
    """
    Extract technical and soft skills from text.

    Matches against predefined COMMON_SKILLS list and returns unique matches.
    Case-insensitive. Limits results to avoid noise.

    Args:
        text: Extracted PDF text
        limit: Maximum number of skills to return

    Returns:
        List of skill names (as they appear in input)
    """
    if not text:
        return []

    text_lower = text.lower()
    found_skills: Dict[str, str] = {}  # {skill_lower: skill_original}

    for skill in COMMON_SKILLS:
        # Word boundary matching to avoid partial matches
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, text_lower):
            if skill.lower() not in found_skills:
                # Try to find the original casing in the text
                match = re.search(pattern, text_lower)
                if match:
                    start = match.start()
                    end = match.end()
                    original = text[start:end]
                    found_skills[skill.lower()] = original

    # Return unique skills, limited to avoid noise
    return list(dict.fromkeys(found_skills.values()))[:limit]


def parse_cv_text(text: str) -> ExtractedCVData:
    """
    Parse extracted CV text and return structured data.

    Args:
        text: Full text extracted from PDF

    Returns:
        ExtractedCVData object with email, phone, languages, skills
    """
    return ExtractedCVData(
        email=extract_email(text),
        phone=extract_phone(text),
        languages=extract_languages(text),
        skills=extract_skills(text),
    )


def extract_and_parse_cv(file_bytes: bytes) -> Optional[ExtractedCVData]:
    """
    Complete CV extraction pipeline: PDF text → parse fields.

    Args:
        file_bytes: Raw PDF file content

    Returns:
        ExtractedCVData or None if extraction fails
    """
    text = extract_text_from_pdf(file_bytes)
    if not text:
        return None

    return parse_cv_text(text)
