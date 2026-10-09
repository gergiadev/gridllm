from gridllm.GridMCPServer.languages.php_parser import PhpParser

SOURCE = """\
<?php
$global = 1;
$handler = function () { $captured = 2; };
function free() { $local = 3; return $local; }
class Shape {
    const SIDES = 4, NAME = "shape";
    public $width, $height;
    function area() { $inner = 5; }
}
"""


def symbols() -> list[tuple[str, str]]:
    return [(s["kind"], s["name"]) for s in PhpParser().listSymbols(SOURCE)]


def test_only_file_level_assignments_are_variables():
    assert [name for kind, name in symbols() if kind == "variable"] == ["global", "handler"]


def test_every_name_of_a_const_or_property_declaration_is_listed():
    assert ("const", "SIDES") in symbols()
    assert ("const", "NAME") in symbols()
    assert ("property", "width") in symbols()
    assert ("property", "height") in symbols()


def test_functions_classes_and_methods_keep_their_kinds():
    assert ("function", "free") in symbols()
    assert ("class", "Shape") in symbols()
    assert ("method", "area") in symbols()
