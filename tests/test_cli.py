import pytest

from qbt_migrate.cli import main, parse_args


class MockQBTBatchMove:
    instance = None
    run_call = None

    def __init__(self, bt_backup_path: str = None):
        self.bt_backup_path = bt_backup_path
        self.add_instance(self)

    @classmethod
    def run(cls, *args, **kwargs):
        cls.run_call = (args, kwargs)

    @classmethod
    def add_instance(cls, instance):
        cls.instance = instance


class MockUserInput:
    def __init__(self, items):
        self.index = 0
        self.items = items

    def next(self):
        if self.index < len(self.items):
            cur, self.index = self.items[self.index], self.index + 1
            print(f"Returning {cur}")
            return cur


def test_parse_args_defaults():
    # Check defaults
    args = parse_args([])
    assert all(
        hasattr(args, key)
        for key in ["existing_path", "new_path", "regex", "target_os", "bt_backup_path", "skip_bad_files", "log_level"]
    )
    assert args.existing_path is None
    assert args.new_path is None
    assert args.regex is None
    assert args.target_os is None
    assert args.bt_backup_path is None
    assert args.skip_bad_files is False
    assert args.log_level == "INFO"


def test_parse_args_shorthand():
    # Check shorthand values
    args = parse_args(
        ["-e", "existing-path", "-n", "new-path", "-r", "-t", "Linux", "-b", "bt-backup-path", "-s", "-l", "DEBUG"]
    )
    assert args.existing_path == "existing-path"
    assert args.new_path == "new-path"
    assert args.regex is True
    assert args.target_os == "Linux"
    assert args.bt_backup_path == "bt-backup-path"
    assert args.skip_bad_files is True
    assert args.log_level == "DEBUG"


def test_parse_args_longhand():
    # Check valid values
    args = parse_args(
        [
            "--existing-path",
            "existing-path",
            "--new-path",
            "new-path",
            "--regex",
            "--target-os",
            "Linux",
            "--bt-backup-path",
            "bt-backup-path",
            "--skip-bad-files",
            "--log-level",
            "DEBUG",
        ]
    )
    assert args.existing_path == "existing-path"
    assert args.new_path == "new-path"
    assert args.regex is True
    assert args.target_os == "Linux"
    assert args.bt_backup_path == "bt-backup-path"
    assert args.skip_bad_files is True
    assert args.log_level == "DEBUG"


def test_parse_args_target_os():
    args = parse_args(["-t", "Windows"])
    assert args.target_os == "Windows"
    args = parse_args(["-t", "Linux"])
    assert args.target_os == "Linux"
    args = parse_args(["-t", "Mac"])
    assert args.target_os == "Mac"

    with pytest.raises(SystemExit):
        args = parse_args(["-t", "windows"])


def test_main_with_inputs(monkeypatch):
    mock_user_input = MockUserInput(["bt-backup-path", "existing-path", "new-path", "no", "windows"])
    monkeypatch.setattr("builtins.input", lambda _: mock_user_input.next())
    monkeypatch.setattr("qbt_migrate.cli.QBTBatchMove", MockQBTBatchMove)
    monkeypatch.setattr("sys.argv", ["qbt_migrate"])
    main()
    assert MockQBTBatchMove.instance.bt_backup_path == "bt-backup-path"
    assert len(MockQBTBatchMove.run_call[0]) == 6
    assert MockQBTBatchMove.run_call[0][0] == "existing-path"
    assert MockQBTBatchMove.run_call[0][1] == "new-path"
    assert MockQBTBatchMove.run_call[0][2] is False
    assert MockQBTBatchMove.run_call[0][3] == "windows"
    assert MockQBTBatchMove.run_call[0][4] is True
    assert MockQBTBatchMove.run_call[0][5] is False


def test_main_with_args(monkeypatch):
    monkeypatch.setattr("qbt_migrate.cli.QBTBatchMove", MockQBTBatchMove)
    monkeypatch.setattr(
        "sys.argv",
        [
            "qbt_migrate",
            "-b",
            "different-bt-backup-path",
            "-e",
            "different-existing-path",
            "-n",
            "different-new-path",
            "-r",
            "-t",
            "Windows",
            "-s",
        ],
    )
    main()
    assert MockQBTBatchMove.instance.bt_backup_path == "different-bt-backup-path"
    assert len(MockQBTBatchMove.run_call[0]) == 6
    assert MockQBTBatchMove.run_call[0][0] == "different-existing-path"
    assert MockQBTBatchMove.run_call[0][1] == "different-new-path"
    assert MockQBTBatchMove.run_call[0][2] is True
    assert MockQBTBatchMove.run_call[0][3] == "Windows"
    assert MockQBTBatchMove.run_call[0][4] is True
    assert MockQBTBatchMove.run_call[0][5] is True


def test_main_invalid_input_loops(monkeypatch):
    monkeypatch.setattr("qbt_migrate.cli.QBTBatchMove", MockQBTBatchMove)
    monkeypatch.setattr("sys.argv", ["qbt_migrate", "-b", "backup-path", "-e", "e-path", "-n", "n-path", "-s"])
    mock_user_input = MockUserInput(["not-valid", "yes", "not-valid", "windows"])
    monkeypatch.setattr("builtins.input", lambda _: mock_user_input.next())
    main()
    assert MockQBTBatchMove.instance.bt_backup_path == "backup-path"
    assert len(MockQBTBatchMove.run_call[0]) == 6
    assert MockQBTBatchMove.run_call[0][0] == "e-path"
    assert MockQBTBatchMove.run_call[0][1] == "n-path"
    assert MockQBTBatchMove.run_call[0][2] is True
    assert MockQBTBatchMove.run_call[0][3] == "windows"
    assert MockQBTBatchMove.run_call[0][4] is True
    assert MockQBTBatchMove.run_call[0][5] is True


def test_main_target_os_auto_detect(monkeypatch):
    monkeypatch.setattr("qbt_migrate.cli.QBTBatchMove", MockQBTBatchMove)

    # Test no OS change
    mock_user_input = MockUserInput(["bt-backup-path", "existing-path", "new-path", "no", ""])
    monkeypatch.setattr("builtins.input", lambda _: mock_user_input.next())
    main()
    assert MockQBTBatchMove.run_call[0][3] is None

    # Test Windows to Linux
    mock_user_input = MockUserInput(["bt-backup-path", "C:\\existing\\path", "/new/path", "no", ""])
    monkeypatch.setattr("builtins.input", lambda _: mock_user_input.next())
    main()
    assert MockQBTBatchMove.run_call[0][3] == "linux"

    # Test Linux to Windows
    mock_user_input = MockUserInput(["bt-backup-path", "/existing/path", "C:\\new\\path", "no", ""])
    monkeypatch.setattr("builtins.input", lambda _: mock_user_input.next())
    main()
    assert MockQBTBatchMove.run_call[0][3] == "windows"
