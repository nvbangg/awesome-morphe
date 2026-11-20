from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

import main as sync


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[MagicMock, MagicMock, MagicMock]:
    tasks = MagicMock()
    client = MagicMock()
    git_status = MagicMock(return_value=b"")
    tasks.discover.return_value = 0
    tasks.update.return_value = 0
    monkeypatch.setattr(sync.discover, "run", tasks.discover)
    monkeypatch.setattr(sync.fetch, "fetch_all_repos", tasks.fetch)
    monkeypatch.setattr(sync.update, "run", tasks.update)
    monkeypatch.setattr(sync.telegram, "send_notification", tasks.telegram)
    monkeypatch.setattr(sync.http, "HTTP_CLIENT", client)
    monkeypatch.setattr(sync.subprocess, "check_output", git_status)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    return tasks, git_status, client


@pytest.mark.parametrize(
    "arguments,changes,mode",
    (
        ([], b"", None),
        ([], b" M data/repos.json\n", "default"),
        (["--daily"], b"", "daily"),
        (["--weekly"], b"", "weekly"),
    ),
)
def test_sync_preserves_update_gate_and_stage_order(arguments, changes, mode, pipeline, tmp_path: Path) -> None:
    tasks, git_status, _client = pipeline
    git_status.return_value = changes
    assert sync.main(arguments) == 0
    daily, weekly = "--daily" in arguments, "--weekly" in arguments
    expected = [call.discover(daily, weekly), call.fetch(daily, weekly)]
    if mode:
        expected.append(call.update(mode))
        assert (tmp_path / "output").read_text(encoding="utf-8") == "updated=true\n"
    else:
        assert not (tmp_path / "output").exists()
    assert tasks.mock_calls == expected
    if arguments:
        git_status.assert_not_called()
    else:
        git_status.assert_called_once_with(
            ["git", "status", "--porcelain", "--", "data/", "web/public/"], cwd=sync.ROOT_DIR
        )


@pytest.mark.parametrize("stage", ("discover", "fetch", "update"))
def test_sync_failure_stops_later_tasks_and_does_not_mark_update(stage, pipeline, tmp_path: Path) -> None:
    tasks, _git_status, client = pipeline
    if stage == "fetch":
        tasks.fetch.side_effect = RuntimeError("Fetch failed")
        with pytest.raises(RuntimeError, match="Fetch failed"):
            sync.main(["--daily"])
    else:
        getattr(tasks, stage).return_value = 1
        assert sync.main(["--daily"]) == 1
    stages = ["discover", "fetch", "update"]
    assert [task[0] for task in tasks.mock_calls] == stages[: stages.index(stage) + 1]
    assert not (tmp_path / "output").exists()
    client.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "arguments,expected",
    (
        (["--daily", "discover"], call.discover(True, False)),
        (["fetch", "--weekly"], call.fetch(False, True)),
        (["update", "--daily"], call.update("daily")),
        (["telegram", "Custom title", "notification.md"], call.telegram("Custom title", Path("notification.md"))),
    ),
)
def test_selected_task_runs_alone(arguments, expected, pipeline) -> None:
    tasks, git_status, _client = pipeline
    assert sync.main(arguments) == 0
    assert tasks.mock_calls == [expected]
    git_status.assert_not_called()
