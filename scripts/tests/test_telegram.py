import io
import json
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

import pytest

import telegram


@pytest.fixture(autouse=True)
def prepare_notification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "notification.md"
    path.write_text(
        "## Example bundle\n"
        "- [owner/repo](https://github.com/owner/repo?ref=main&name=a_b)\n"
        "- `x < y`\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TG_TOKEN", "test-token")
    monkeypatch.setenv("TG_CHAT", "test-chat")
    monkeypatch.setattr(
        telegram.sys, "argv", ["telegram.py", "Updates <daily> & news", str(path)]
    )


def test_notification_payload_preserves_links_and_escapes_html(block_network) -> None:
    block_network.side_effect = None
    telegram.main()
    block_network.assert_called_once()
    request = block_network.call_args.args[0]
    payload = parse_qs(request.data.decode("utf-8"))
    assert request.get_method() == "POST"
    assert payload["chat_id"] == ["test-chat"]
    assert payload["parse_mode"] == ["HTML"]
    text = payload["text"][0]
    assert "Updates &lt;daily&gt; &amp; news" in text
    assert 'href="https://github.com/owner/repo?ref=main&name=a_b"' in text
    assert "x &lt; y" in text


@pytest.mark.parametrize("failure_kind", ("api", "network"))
def test_notification_failure_stops_with_error(
    failure_kind, block_network, patch_context
) -> None:
    if failure_kind == "api":
        error = HTTPError(
            "https://api.telegram.org",
            400,
            "Bad Request",
            Message(),
            io.BytesIO(json.dumps({"description": "Invalid HTML"}).encode()),
        )
        patch_context.callback(error.close)
    else:
        error = URLError("DNS lookup failed")
    block_network.side_effect = error
    with pytest.raises(SystemExit) as raised:
        telegram.main()
    block_network.assert_called_once()
    assert raised.value.code not in (None, 0)
    if failure_kind == "api":
        assert "Invalid HTML" in str(raised.value)
