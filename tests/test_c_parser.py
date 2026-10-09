from gridllm.GridMCPServer.languages.c_parser import CParser

SOURCE = """\
struct point { int x; int y; };
enum color { RED, GREEN };
union word { int i; char c[4]; };
typedef struct node { int v; } node_t;
static int counter = 1;
int add(int a, int b) { return a + b; }
"""


def kinds(name: str) -> list[str]:
    return [s["kind"] for s in CParser().listSymbols(SOURCE) if s["name"] == name]


def test_file_level_tagged_types_are_listed():
    assert kinds("point") == ["struct"]
    assert kinds("color") == ["enum"]
    assert kinds("word") == ["union"]


def test_enumerators_of_a_file_level_enum_are_constants():
    assert kinds("RED") == ["const"]
    assert kinds("GREEN") == ["const"]


def test_typedefs_functions_and_globals_are_still_listed():
    assert kinds("node") == ["struct"]
    assert kinds("node_t") == ["typedef"]
    assert kinds("counter") == ["variable"]
    assert kinds("add") == ["function"]


def test_a_struct_body_can_be_extracted_by_name():
    body = CParser().getSymbolBody(SOURCE, "point")
    assert [entry["body"] for entry in body] == ["struct point { int x; int y; };"]
