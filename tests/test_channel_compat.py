import sys
import types
from types import SimpleNamespace

import pytest

try:
    import microsoft_agents.activity  # noqa: F401
except ImportError:
    _pkg = types.ModuleType("microsoft_agents")
    _activity = types.ModuleType("microsoft_agents.activity")
    _activity.Activity = object
    _pkg.activity = _activity
    sys.modules.setdefault("microsoft_agents", _pkg)
    sys.modules.setdefault("microsoft_agents.activity", _activity)

from fincrime_autopilot.email_channel_compat import (
    is_email_activity,
    is_wpx_comment_activity,
    supports_typing_indicator,
)


def _activity(channel, sub_channel="", entities=None):
    return SimpleNamespace(
        type="message",
        channel_id=SimpleNamespace(channel=channel, sub_channel=sub_channel),
        entities=entities or [],
    )


WORD_COMMENT = _activity("agents", "word", [{"type": "WpxComment", "documentId": "d1"}])
EMAIL = _activity("agents", "email", [{"type": "emailNotification"}])
TEAMS = _activity("msteams")


def test_word_comment_is_detected():
    assert is_wpx_comment_activity(WORD_COMMENT)
    assert not is_email_activity(WORD_COMMENT)


@pytest.mark.parametrize("activity", [WORD_COMMENT, EMAIL, _activity("agents", "excel"), None])
def test_agents_channel_never_gets_typing(activity):
    assert not supports_typing_indicator(activity)


@pytest.mark.parametrize("channel", ["msteams", "webchat", "emulator"])
def test_chat_channels_get_typing(channel):
    assert supports_typing_indicator(_activity(channel))


def test_string_channel_id_is_parsed():
    activity = SimpleNamespace(type="message", channel_id="agents:word", entities=[])
    assert not supports_typing_indicator(activity)
    assert supports_typing_indicator(TEAMS)
