"""T10: a run task can carry its code (input.files) so any executor can run it; paths stay inside the run dir."""
import pytest

from lab.executor.worker import write_files


def test_files_are_written_inside_the_run_dir(tmp_path):
    written = write_files({"train.py": "print('hi')\n", "src/util.py": "X = 1\n"}, tmp_path)
    assert written == ["src/util.py", "train.py"]
    assert (tmp_path / "train.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert (tmp_path / "src" / "util.py").read_text(encoding="utf-8") == "X = 1\n"


@pytest.mark.parametrize("path", ["../escape.py", "C:/Windows/x.py", "/etc/x", "src/../../x.py", ""])
def test_paths_outside_the_run_dir_are_refused(tmp_path, path):
    with pytest.raises(ValueError, match="run dir"):
        write_files({path: "x"}, tmp_path / "run")
    assert not (tmp_path / "escape.py").exists()


def test_non_text_content_is_refused(tmp_path):
    with pytest.raises(ValueError, match="text"):
        write_files({"a.py": 3}, tmp_path)


def test_advertised_caps_add_host_and_agent_without_duplicates():
    from lab.executor.worker import advertised_caps
    assert advertised_caps("laptop-b", ["smoke", "train", "agent"]) == ["smoke", "train", "agent", "host:laptop-b"]
