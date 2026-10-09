import pytest

from gridllm.GridMCPServer.languages.asm_parser import AsmParser

SOURCE = """\
    .section .text
    .globl main
# maximum buffer length
.equ MAXLEN, 64
.set FOO, 7
BAR = 9

.macro push_all
    push %rax
    push %rbx
.endm

# entry point
main: mov %eax, %ebx
    add $1, %eax
    ret

loop_start:
    dec %ecx
    jnz loop_start
"""


@pytest.fixture
def parser() -> AsmParser:
    return AsmParser()


def named(symbols, name):
    return [symbol for symbol in symbols if symbol["name"] == name]


def test_label_with_instruction_on_the_same_line_is_found(parser):
    labels = [s for s in parser.listSymbols(SOURCE) if s["kind"] == "label"]
    assert [s["name"] for s in labels] == ["main", "loop_start"]


def test_gas_equ_and_set_become_named_constants(parser):
    constants = {s["name"]: s["kind"] for s in parser.listSymbols(SOURCE) if s["kind"] == "constant"}
    assert constants == {"MAXLEN": "constant", "FOO": "constant", "BAR": "constant"}


def test_instructions_are_not_symbols(parser):
    kinds = {s["kind"] for s in parser.listSymbols(SOURCE)}
    assert "instruction" not in kinds
    assert kinds <= {"label", "constant", "macro", "section", "global"}


def test_macro_spans_from_macro_to_endm(parser):
    macro = named(parser.listSymbols(SOURCE), "push_all")[0]
    assert macro["kind"] == "macro"
    assert (macro["line"], macro["endLine"]) == (8, 11)


def test_label_body_covers_more_than_its_own_line(parser):
    body = next(b for b in parser.getSymbolBody(SOURCE, "main") if b["kind"] == "label")
    assert "mov %eax, %ebx" in body["body"]
    assert "ret" in body["body"]
    assert "dec %ecx" not in body["body"]


def test_preceding_comment_becomes_the_docstring(parser):
    label = next(s for s in parser.listSymbols(SOURCE) if s["name"] == "main" and s["kind"] == "label")
    assert label["docstring"] == "entry point"


def test_section_and_global_directives_are_reported(parser):
    symbols = parser.listSymbols(SOURCE)
    assert next(s for s in symbols if s["kind"] == "section")["name"] == ".text"
    assert next(s for s in symbols if s["kind"] == "global")["name"] == "main"


def test_comment_only_and_empty_source_yield_nothing(parser):
    assert parser.listSymbols("") == []
    assert parser.listSymbols("# just a comment\n\n; another\n") == []


PREPROCESSED = """\
#define MAGIC 0x10
#include "regs.h"
    .globl main
main:
    push %rbp
.Lloop:
    dec %eax
    jnz .Lloop
    ret
helper:
    ret
"""


def test_a_local_label_does_not_end_the_enclosing_body(parser):
    main = next(s for s in parser.listSymbols(PREPROCESSED) if s["name"] == "main" and s["kind"] == "label")
    assert (main["line"], main["endLine"]) == (4, 9)
    assert named(parser.listSymbols(PREPROCESSED), ".Lloop")


def test_a_preprocessor_define_is_a_constant_and_an_include_is_not(parser):
    symbols = parser.listSymbols(PREPROCESSED)
    assert named(symbols, "MAGIC")[0]["kind"] == "constant"
    assert not named(symbols, "include")
