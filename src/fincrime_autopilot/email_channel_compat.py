# Copyright (c) Microsoft. All rights reserved.

"""Classification helpers for Microsoft 365 channel activities."""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from microsoft_agents.activity import Activity

_AGENTS_CHANNEL = "agents"
_EMAIL_CHANNEL = "email"
_WPX_COMMENT_ENTITY = "wpxcomment"

# Agent 365 puts an email's subject in conversation.topic, which the SDK's
# ConversationAccount model doesn't keep. The host captures it from the raw
# request; the turn runs inside that request, so a context variable carries it.
_raw_conversation_topic: ContextVar[str] = ContextVar("raw_conversation_topic", default="")


def capture_raw_conversation_topic(body: bytes | str) -> None:
    topic = ""
    try:
        payload = json.loads(body)
        conversation = payload.get("conversation") if isinstance(payload, dict) else None
        if isinstance(conversation, dict):
            topic = str(conversation.get("topic") or "")
    except (TypeError, ValueError):
        pass
    _raw_conversation_topic.set(topic)


def raw_conversation_topic() -> str:
    return _raw_conversation_topic.get()


def is_email_notification(notification_activity: Any) -> bool:
    notification_type = getattr(notification_activity, "notification_type", None)
    value = getattr(notification_type, "value", notification_type)
    return "email" in str(value or "").lower()


def is_email_activity(activity: Activity | None) -> bool:
    if activity is None:
        return False

    channel, sub_channel = _split_channel_id(getattr(activity, "channel_id", None))
    if channel == _EMAIL_CHANNEL or (
        channel == _AGENTS_CHANNEL and sub_channel == _EMAIL_CHANNEL
    ):
        return True

    return _get_product_id(activity) == _EMAIL_CHANNEL


def is_wpx_comment_activity(activity: Activity | None) -> bool:
    if activity is None:
        return False

    return _has_entity_type(activity, _WPX_COMMENT_ENTITY)


def supports_typing_indicator(activity: Activity | None) -> bool:
    """Return False for channels that reject ``typing`` activities.

    The Agent 365 ``agents`` channel (email, Word/Excel/PowerPoint comments)
    accepts only ``message`` and ``event`` activities and answers a ``typing``
    activity with HTTP 400 BadArgument.
    """
    if activity is None:
        return False

    channel, _ = _split_channel_id(getattr(activity, "channel_id", None))
    if channel in (_AGENTS_CHANNEL, _EMAIL_CHANNEL):
        return False

    return not (is_email_activity(activity) or is_wpx_comment_activity(activity))


def _split_channel_id(channel_id: Any) -> tuple[str, str]:
    if channel_id is None:
        return "", ""

    channel = str(getattr(channel_id, "channel", "") or "")
    sub_channel = str(getattr(channel_id, "sub_channel", "") or "")
    if not channel:
        value = str(channel_id)
        channel, _, sub_channel = value.partition(":")

    return channel.lower(), sub_channel.lower()


def _get_product_info(activity: Activity) -> Any:
    get_product_info_entity = getattr(activity, "get_product_info_entity", None)
    if not callable(get_product_info_entity):
        return None
    return get_product_info_entity()


def _get_product_id(activity: Activity) -> str:
    product_info = _get_product_info(activity)
    product_id = _get_first_value(product_info, "id")
    if product_id:
        return str(product_id).lower()

    for entity in getattr(activity, "entities", None) or []:
        if _entity_type(entity) == "productinfo":
            return str(_get_first_value(entity, "id") or "").lower()

    return ""


def _has_entity_type(activity: Activity, entity_type: str) -> bool:
    expected = entity_type.lower()
    return any(
        _entity_type(entity) == expected
        for entity in getattr(activity, "entities", None) or []
    )


def _entity_type(entity: Any) -> str:
    return str(_get_first_value(entity, "type") or "").lower()


def _get_first_value(value: Any, *names: str) -> Any:
    if value is None:
        return ""

    if isinstance(value, dict):
        lower_map = {str(key).lower(): item for key, item in value.items()}
        for name in names:
            item = value.get(name)
            if item is not None and item != "":
                return item
            item = lower_map.get(name.lower())
            if item is not None and item != "":
                return item
        return ""

    for name in names:
        item = getattr(value, name, None)
        if item is not None and item != "":
            return item
    return ""
