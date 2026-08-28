from gridllm.orchestrator import _norm


def test_equivalent_spellings_collapse_to_one_string(tmp_path):
    workspace = tmp_path.resolve()
    (workspace / "src").mkdir()
    target = "src/vm.c"
    spellings = [target, f"./{target}", str(workspace / target), "src/../src/vm.c"]
    assert {_norm(spelling, workspace) for spelling in spellings} == {target}


def test_a_path_outside_the_workspace_stays_distinguishable(tmp_path):
    workspace = tmp_path.resolve()
    assert _norm("../outside.c", workspace) == "../outside.c"


def test_declared_and_touched_agree_on_mixed_spellings(tmp_path):
    workspace = tmp_path.resolve()
    (workspace / "src").mkdir()
    touched = {_norm(p, workspace) for p in [str(workspace / "src/vm.c")]}
    declared = {_norm(p, workspace) for p in ["./src/vm.c"]}
    assert declared == touched
