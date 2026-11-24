from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

import main as sync
from common.files import load_json, save_json


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    tasks = MagicMock()
    client = MagicMock()
    git_status = MagicMock(return_value=b"")
    summary = MagicMock()
    tasks.discover.return_value = 0
    tasks.update.return_value = 0
    tasks.fetch.return_value = 1
    monkeypatch.setattr(sync, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(sync.discover, "run", tasks.discover)
    monkeypatch.setattr(sync.fetch, "fetch_all_repos", tasks.fetch)
    monkeypatch.setattr(sync.update, "run", tasks.update)
    monkeypatch.setattr(sync.telegram, "send_notification", tasks.telegram)
    monkeypatch.setattr(sync.http, "HTTP_CLIENT", client)
    monkeypatch.setattr(sync.subprocess, "check_output", git_status)
    tasks.audit.return_value = "Audit"
    tasks.find_projects.return_value = "Projects"
    monkeypatch.setattr(sync.audit_readme, "audit_repos_and_links", tasks.audit)
    monkeypatch.setattr(sync.find_projects, "run", tasks.find_projects)
    monkeypatch.setattr(sync, "append_step_summary", summary)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    return tasks, git_status, client, summary


@pytest.mark.parametrize(
    "arguments,changes,mode",
    (
        ([], b"", None),
        ([], b" M data/repos.json\n", "default"),
        (["--daily"], b"", "daily"),
    ),
)
def test_sync_preserves_update_gate_and_stage_order(arguments, changes, mode, pipeline, tmp_path: Path) -> None:
    tasks, git_status, _client, summary = pipeline
    git_status.return_value = changes
    assert sync.main(arguments) == 0
    daily = "--daily" in arguments
    expected = [call.audit(), call.find_projects()] if daily else []
    expected.extend([call.discover(), call.fetch(daily, 0)])
    if mode:
        expected.append(call.update(daily))
    assert (tmp_path / "output").read_text(encoding="utf-8") == "updated=true\n"
    assert load_json(sync.STATE_PATH)["nextRepoGroup"] == 1
    assert tasks.mock_calls == expected
    if daily:
        summary.assert_called_once()
        report = summary.call_args.args[0]
        assert report.index("Audit") < report.index("Projects")
    else:
        summary.assert_not_called()
    if arguments:
        git_status.assert_not_called()
    else:
        git_status.assert_called_once_with(
            ["git", "status", "--porcelain", "--", "data/", "web/public/"], cwd=sync.ROOT_DIR
        )


@pytest.mark.parametrize("stage", ("discover", "fetch", "update"))
def test_sync_failure_stops_later_tasks_and_does_not_mark_update(stage, pipeline, tmp_path: Path) -> None:
    tasks, _git_status, client, _summary = pipeline
    if stage == "fetch":
        tasks.fetch.side_effect = RuntimeError("Fetch failed")
        with pytest.raises(RuntimeError, match="Fetch failed"):
            sync.main(["--daily"])
    else:
        getattr(tasks, stage).return_value = 1
        assert sync.main(["--daily"]) == 1
    stages = ["discover", "fetch", "update"]
    assert [task[0] for task in tasks.mock_calls] == ["audit", "find_projects"] + stages[: stages.index(stage) + 1]
    assert not (tmp_path / "output").exists()
    assert not sync.STATE_PATH.exists()
    client.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "arguments,expected",
    (
        (["audit-readme"], call.audit()),
        (["find-projects"], call.find_projects()),
        (["discover"], call.discover()),
        (["fetch", "--daily"], call.fetch(True, 0)),
        (["--daily", "fetch"], call.fetch(True, 0)),
        (["update", "--daily"], call.update(True)),
        (["--daily", "update"], call.update(True)),
        (["telegram", "Custom title", "notification.md"], call.telegram("Custom title", Path("notification.md"))),
    ),
)
def test_selected_task_runs_alone(arguments, expected, pipeline) -> None:
    tasks, git_status, _client, _summary = pipeline
    assert sync.main(arguments) == 0
    assert tasks.mock_calls == [expected]
    git_status.assert_not_called()
    assert sync.STATE_PATH.exists() == (expected[0] == "fetch")


def test_group_rotation_without_data_changes_skips_update(pipeline) -> None:
    tasks, _git_status, _client, _summary = pipeline
    tasks.fetch.side_effect = lambda daily, group: (group + 1) % 2
    for expected_group in (1, 0, 1):
        assert sync.main([]) == 0
        assert load_json(sync.STATE_PATH)["nextRepoGroup"] == expected_group
    tasks.update.assert_not_called()
    assert tasks.fetch.call_args_list == [call(False, 0), call(False, 1), call(False, 0)]


def test_group_save_preserves_state_written_by_update(pipeline) -> None:
    tasks, _git_status, _client, _summary = pipeline
    state = {"lastDaily": "2026-11-24", "appHashes": {"github:1": {"app": "hash"}}, "history": {}}

    def update(daily):
        save_json(sync.STATE_PATH, state)
        return 0

    tasks.update.side_effect = update
    assert sync.main(["--daily"]) == 0
    assert load_json(sync.STATE_PATH) == {**state, "nextRepoGroup": 1}
    assert list(load_json(sync.STATE_PATH)) == ["lastDaily", "nextRepoGroup", "appHashes", "history"]
