"""只投影保存文本, 不泄漏任意payload或把HTML当作指令。"""

from investment_os.infrastructure.analysis_evidence import verified_texts


def test_text_projection_is_allowlisted_and_preserves_plain_untrusted_html():
    raw = {
        "summary": "<script>synthetic-only</script>",
        "content": "合成正文",
        "api_key": "must-not-project",  # pragma: allowlist secret - 合成拒绝投影夹具, 非凭据
        "headers": {"Authorization": "must-not-project"},
        "nested": {"content": "must-not-project"},
    }
    values = verified_texts(raw)
    assert [value.field for value in values] == ["summary", "content"]
    assert values[0].text == raw["summary"]
    assert "must-not-project" not in str(values)
    assert not any(value.truncated for value in values)


def test_projection_is_bounded_marks_truncation_and_ignores_duplicate_or_nontext_fields():
    raw = {
        key: str(i) * 25000
        for i, key in enumerate(("summary", "snippet", "text", "content", "description"))
    }
    values = verified_texts(raw)
    assert sum(len(value.text) for value in values) == 64000
    assert all(
        len(value.text) <= 20000 and value.original_length == 25000 and value.truncated
        for value in values
    )
    assert not verified_texts({"summary": " ", "text": 10, "content": ["not plain text"]})
    assert len(verified_texts({"summary": "same", "snippet": "same"})) == 1
