"""Deterministic script-based language detection — Phase 6 task §39."""
from __future__ import annotations

from app.i18n.detect import detect_script_language


def test_english_text_detected_as_en() -> None:
    assert detect_script_language("Find a suitable fishing area near Mangaluru tomorrow.") == "en"


def test_kannada_text_detected_as_kn() -> None:
    assert detect_script_language("ಸುರಕ್ಷಿತ ಮೀನುಗಾರಿಕೆ ಪ್ರದೇಶವನ್ನು ಹುಡುಕಿ.") == "kn"


def test_hindi_text_detected_as_hi() -> None:
    assert detect_script_language("एक सुरक्षित मछली पकड़ने का क्षेत्र खोजें।") == "hi"


def test_tamil_text_detected_as_ta() -> None:
    assert detect_script_language("பாதுகாப்பான மீன்பிடி பகுதியைக் கண்டறியவும்") == "ta"


def test_telugu_text_detected_as_te() -> None:
    assert detect_script_language("సురక్షితమైన చేపల వేట ప్రాంతాన్ని కనుగొనండి") == "te"


def test_malayalam_text_detected_as_ml() -> None:
    assert detect_script_language("സുരക്ഷിതമായ മത്സ്യബന്ധന മേഖല കണ്ടെത്തുക") == "ml"


def test_mixed_script_picks_the_dominant_script() -> None:
    # Overwhelmingly Kannada, with one short English loanword.
    assert detect_script_language("ನಾಳೆ ಬೆಳಿಗ್ಗೆ ಮಂಗಳೂರಿನ ಹತ್ತಿರ ಮೀನುಗಾರಿಕೆಗೆ ಸೂಕ್ತವಾದ ಸ್ಥಳ ಹುಡುಕಿ safe") == "kn"

    # Overwhelmingly English, with one Kannada place name.
    assert detect_script_language("Find a safe fishing area near ಮಂಗಳೂರು tomorrow morning please") == "en"


def test_digits_and_punctuation_only_returns_none() -> None:
    assert detect_script_language("12.80, 74.20") is None


def test_empty_string_returns_none() -> None:
    assert detect_script_language("") is None


def test_bare_place_name_alone_is_not_confidently_english() -> None:
    # A single Latin-script place name gives no real evidence of English
    # specifically (it could appear in a French/German/Spanish sentence
    # too) — correctly defers to the LLM's own language field.
    assert detect_script_language("Mangaluru") is None


def test_french_text_is_not_misclassified_as_english() -> None:
    # Pure Latin script, but none of the closed-class English signal words
    # — must defer to the LLM (return None), never claim "en" and silently
    # override a correct "fr" answer.
    assert detect_script_language("est-ce sûr?") is None
