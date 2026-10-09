from gridllm.GridMCPServer.readers import NativeReader, choose_reader
from gridllm.GridMCPServer.workspace import expandBraces, matchesInclude


def test_expand_braces_produces_one_pattern_per_alternative():
    assert expandBraces("*.{c,h,s}") == ["*.c", "*.h", "*.s"]
    assert expandBraces("*.py") == ["*.py"]
    assert expandBraces("src/{a,b}/*.{c,h}") == [
        "src/a/*.c", "src/a/*.h", "src/b/*.c", "src/b/*.h",
    ]


def test_matches_include_checks_path_and_bare_name():
    assert matchesInclude("src/vm.c", ["*.c"])
    assert matchesInclude("src/vm.c", ["vm.c"])
    assert not matchesInclude("src/vm.c", ["*.py"])


def test_brace_pattern_actually_filters_a_search(examples, quiet_logger):
    reader = choose_reader(quiet_logger, ignore=(".git", "build"))
    patterns = tuple(expandBraces("*.{c,h}"))

    matched = reader.search("void", examples, examples, False, patterns)
    assert matched
    assert all(hit["path"].endswith((".c", ".h")) for hit in matched)

    assert reader.search("void", examples, examples, False, ("*.py",)) == []


def test_include_does_not_change_which_lines_match(examples, quiet_logger):
    reader = choose_reader(quiet_logger, ignore=(".git", "build"))
    everything = reader.search("void", examples, examples, False)
    sources = reader.search("void", examples, examples, False, ("*.c", "*.h"))
    assert sources == [hit for hit in everything if hit["path"].endswith((".c", ".h"))]


def test_query_starting_with_a_dash_is_not_read_as_a_flag(examples, quiet_logger, tmp_path):
    (tmp_path / "sample.c").write_text("int x = -1;\nint y = 2;\n", encoding="utf-8")
    reader = choose_reader(quiet_logger, ignore=())
    hits = reader.search("-1", tmp_path, tmp_path, False)
    assert [hit["line"] for hit in hits] == [1]


def test_native_reader_agrees_with_the_external_backend(examples, quiet_logger):
    reader = choose_reader(quiet_logger, ignore=(".git", "build"))
    native = NativeReader(ignore=(".git", "build"))
    assert reader.search("void", examples, examples, False, ("*.h",)) == \
        native.search("void", examples, examples, False, ("*.h",))


def test_double_star_also_matches_direct_children():
    assert matchesInclude("src/vm.c", ["src/**/*.c"])
    assert matchesInclude("src/deep/vm.c", ["src/**/*.c"])
    assert not matchesInclude("lib/vm.c", ["src/**/*.c"])


def test_a_file_that_is_not_utf8_does_not_break_the_search(quiet_logger, tmp_path):
    (tmp_path / "latin.c").write_bytes(b"int caf\xe9 = 1; /* needle */\n")
    reader = choose_reader(quiet_logger, ignore=())
    assert reader.search("needle", tmp_path, tmp_path, False) in (
        [],
        [{"path": "latin.c", "line": 1, "text": "int caf\ufffd = 1; /* needle */"}],
    )
