from pathlib import Path
from urllib.parse import parse_qs

import httpx2
import pytest

import telegram


@pytest.fixture(autouse=True)
def prepare_notification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    path = tmp_path / "notification.md"
    path.write_text(
        "## Example bundle\n- [owner/repo](https://github.com/owner/repo?ref=main&name=a_b)\n- `x < y`\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TG_TOKEN", "test-token")
    monkeypatch.setenv("TG_CHAT", "test-chat")
    return "Updates <daily> & news", path


def test_notification_payload_preserves_links_and_escapes_html(block_network, prepare_notification) -> None:
    block_network.side_effect = None
    telegram.send_notification(*prepare_notification)
    block_network.assert_called_once()
    request = block_network.call_args.args[0]
    payload = parse_qs(request.content.decode("utf-8"))
    assert request.method == "POST"
    assert payload["chat_id"] == ["test-chat"]
    assert payload["parse_mode"] == ["HTML"]
    text = payload["text"][0]
    assert "Updates &lt;daily&gt; &amp; news" in text
    assert 'href="https://github.com/owner/repo?ref=main&name=a_b"' in text
    assert "x &lt; y" in text


@pytest.mark.parametrize("failure_kind", ("api", "network"))
def test_notification_failure_stops_with_error(failure_kind, block_network, prepare_notification) -> None:
    if failure_kind == "api":
        block_network.side_effect = None
        block_network.return_value = httpx2.Response(400, json={"description": "Invalid HTML"})
    else:
        block_network.side_effect = httpx2.ConnectError("DNS lookup failed")
    with pytest.raises(SystemExit) as raised:
        telegram.send_notification(*prepare_notification)
    block_network.assert_called_once()
    assert raised.value.code not in (None, 0)
    assert "test-token" not in str(raised.value)
    if failure_kind == "api":
        assert "Invalid HTML" in str(raised.value)
