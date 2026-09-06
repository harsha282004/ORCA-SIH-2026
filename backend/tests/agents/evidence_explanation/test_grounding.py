from app.agents.evidence_explanation.grounding import (
    check_grounding,
    check_no_false_safety_claim,
    extract_numeric_tokens,
    is_grounded_and_safe,
)


def test_extract_numeric_tokens_finds_integers_and_floats() -> None:
    assert extract_numeric_tokens("risk score is 0.27, wave height 1.4m, wind 12") == [0.27, 1.4, 12.0]


def test_check_grounding_passes_when_every_number_traces_to_evidence() -> None:
    assert check_grounding("risk score is 0.27", [0.27, 0.9]) is True


def test_check_grounding_fails_on_a_fabricated_number() -> None:
    assert check_grounding("risk score is 0.99", [0.27, 0.9]) is False


def test_check_grounding_tolerates_rounding_differences() -> None:
    assert check_grounding("risk score is 0.270", [0.2701]) is True


def test_check_grounding_passes_trivially_when_no_numbers_present() -> None:
    assert check_grounding("conditions look calm today", [0.27]) is True


def test_no_false_safety_claim_passes_when_decision_is_not_no_safe_recommendation() -> None:
    assert check_no_false_safety_claim("it is safe to proceed", decision_outcome="RECOMMEND") is True


def test_no_false_safety_claim_fails_when_blocked_decision_claims_safety() -> None:
    assert check_no_false_safety_claim("conditions are safe to fish", decision_outcome="NO_SAFE_RECOMMENDATION") is False


def test_no_false_safety_claim_passes_for_blocked_decision_with_no_safety_claim() -> None:
    text = "ORCA cannot provide a safe recommendation for this query at this time."
    assert check_no_false_safety_claim(text, decision_outcome="NO_SAFE_RECOMMENDATION") is True


def test_is_grounded_and_safe_requires_both_checks_to_pass() -> None:
    assert is_grounded_and_safe("risk score is 0.27", [0.27], decision_outcome="RECOMMEND") is True
    assert is_grounded_and_safe("risk score is 0.99", [0.27], decision_outcome="RECOMMEND") is False
    assert is_grounded_and_safe("it is safe", [], decision_outcome="NO_SAFE_RECOMMENDATION") is False


# --- Phase 6: the same false-safety-claim check must also work in Hindi/Kannada ---


def test_no_false_safety_claim_fails_on_hindi_unsafe_affirmation() -> None:
    text = "आज मछली पकड़ने के लिए स्थिति सुरक्षित है, आप जा सकते हैं।"
    assert check_no_false_safety_claim(text, decision_outcome="NO_SAFE_RECOMMENDATION") is False


def test_no_false_safety_claim_fails_on_kannada_unsafe_affirmation() -> None:
    text = "ಈ ಪ್ರದೇಶ ಸುರಕ್ಷಿತವಾಗಿದೆ, ನೀವು ಮೀನುಗಾರಿಕೆ ಮಾಡಬಹುದು."
    assert check_no_false_safety_claim(text, decision_outcome="NO_SAFE_RECOMMENDATION") is False


def test_no_false_safety_claim_passes_for_hindi_text_with_no_safety_claim() -> None:
    text = "जोखिम अधिक है, इसलिए ORCA अभी कोई सिफारिश नहीं कर सकता।"
    assert check_no_false_safety_claim(text, decision_outcome="NO_SAFE_RECOMMENDATION") is True


def test_no_false_safety_claim_passes_for_kannada_text_with_no_safety_claim() -> None:
    text = "ಅಪಾಯ ಹೆಚ್ಚಿದೆ, ಆದ್ದರಿಂದ ORCA ಈಗ ಯಾವುದೇ ಸಲಹೆ ನೀಡಲು ಸಾಧ್ಯವಿಲ್ಲ."
    assert check_no_false_safety_claim(text, decision_outcome="NO_SAFE_RECOMMENDATION") is True


def test_hindi_kannada_safety_claims_pass_when_decision_is_not_blocked() -> None:
    # The check only applies when the decision is NO_SAFE_RECOMMENDATION —
    # a legitimate "it is safe" claim in a RECOMMEND response is fine.
    assert check_no_false_safety_claim("यह सुरक्षित है", decision_outcome="RECOMMEND") is True
    assert check_no_false_safety_claim("ಇದು ಸುರಕ್ಷಿತವಾಗಿದೆ", decision_outcome="RECOMMEND") is True
