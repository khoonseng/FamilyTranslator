import pytest
from pydantic import ValidationError

from app.schemas import Hello, Mode, SegmentStart, TypedText, phone_message


def test_phone_messages_parse_by_type():
    assert isinstance(
        phone_message.validate_json('{"type": "hello", "role": "hub", "pin": "1", "token": "2"}'),
        Hello,
    )
    assert phone_message.validate_json('{"type": "mode", "mode": "guide"}') == Mode(mode="guide")
    assert phone_message.validate_json('{"type": "segment_start", "pause_s": 2.4}').pause_s == 2.4
    assert phone_message.validate_json('{"type": "text", "text": "你好"}') == TypedText(text="你好")


@pytest.mark.parametrize(
    "raw",
    [
        '{"type": "mode", "mode": "family"}',  # phase 2, not in the MVP
        '{"type": "segment_start", "pause_s": -1}',
        '{"type": "text", "text": ""}',
        '{"type": "unknown"}',
    ],
)
def test_bad_phone_messages_are_rejected(raw):
    with pytest.raises(ValidationError):
        phone_message.validate_json(raw)


def test_segment_start_pause_is_required():
    with pytest.raises(ValidationError):
        SegmentStart()
