from services.ai_service import AIService


def _service() -> AIService:
    return AIService()


def test_parse_json_from_markdown_fence():
    service = _service()
    raw = """```json
{"approved": true, "feedback": "ok", "confidence": 92}
```"""
    parsed = service.parse_json_response(raw)
    assert parsed["approved"] is True
    assert parsed["confidence"] == 92


def test_parse_json_with_common_issues():
    service = _service()
    raw = "{'approved': True, 'feedback': 'looks good', 'confidence': 91,}"
    parsed = service.parse_json_response(raw)
    assert parsed["approved"] is True
    assert parsed["confidence"] == 91


def test_parse_json_with_text_wrapper():
    service = _service()
    raw = "Result below:\n{\"approved\": false, \"feedback\": \"wrong fix\", \"confidence\": 45}\nThanks"
    parsed = service.parse_json_response(raw)
    assert parsed["approved"] is False
    assert parsed["confidence"] == 45


def test_validator_fallback_extracts_confidence():
    service = _service()
    raw = "approved: yes\nconfidence: 93\nfeedback: Patch addresses the failing assertion."
    parsed = service.extract_validator_fallback(raw)
    assert parsed["approved"] is True
    assert parsed["confidence"] == 93
    assert "feedback" in parsed
