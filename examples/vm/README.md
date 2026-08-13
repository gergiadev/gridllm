# mvm — a small bytecode virtual machine

`mvm` is a self-contained stack machine written in C11. It is the specification of
itself: `main.c` builds a handful of programs with the bytecode emitter, runs them
and compares the result with the value each one is supposed to produce.

**The build is clean, the program runs to completion, and it produces wrong answers.**

## Components

| file | what it holds |
|---|---|
| `arena.c` | bump allocator: blocks chained together, allocation with alignment |
| `table.c` | hash table with open addressing, linear probing, tombstones, and string interning |
| `chunk.c` | bytecode buffer: opcode emission, constant pool, forward jump patching, backward loops |
| `vm.c` | the interpreter: value stack that grows, call frames, locals, globals, dispatch loop |
| `main.c` | the programs under test and the expectations they must meet |

## The machine

Values are 64-bit integers, interned strings or functions. The interpreter keeps a
growable value stack and up to 64 call frames. On a call the caller leaves the
callee and its arguments on the stack, the machine reserves the remaining locals,
and the frame's `slots` pointer is anchored so that `slots[0]` is the function and
`slots[1..nlocals]` are the locals. `OP_RET` unwinds the frame down to `slots` and
leaves the result on top.

Jumps are relative: `chunk_emit_jump` reserves a two-byte hole that
`chunk_patch_jump` fills once the destination is known, while `chunk_emit_loop`
computes a backward offset directly.

## Building and running

```bash
make            # build
make run        # build and run the test programs
make asan       # rebuild with AddressSanitizer + UndefinedBehaviorSanitizer and run
make clean
```

## What it must print

```
[ok]   fib(20)                      = 6765
[ok]   sum(1..100)                  = 5050
[ok]   gcd(1071, 462)               = 21
[ok]   globals g0..g11              = 506
[ok]   fib(24)                      = 46368
[ok]   intern identity              = 1
[ok]   intern prefix distinct       = 1
[ok]   intern prefix length         = 5
[ok]   table survivors found        = 10
[ok]   table survivors correct      = 0
[ok]   table deleted stay gone      = 0

all tests passed
```

Exit status must be 0, and `make asan` must report neither an error nor a leak.

## What it prints today

```
[ok]   fib(20)                      = 6765
[FAIL] sum(1..100)                  = 0 (want 5050)
[FAIL] gcd(1071, 462)               = 462 (want 21)
[FAIL] globals g0..g11              ! undefined global 'g1' (want 506)
[FAIL] fib(24)                      ! undefined global 'fib' (want 46368)
[ok]   intern identity              = 1
[ok]   intern prefix distinct       = 1
[ok]   intern prefix length         = 5
[FAIL] table survivors found        = 7 (want 10)
[ok]   table survivors correct      = 0
[ok]   table deleted stay gone      = 0

5 test(s) failed
```

`make asan` adds `LeakSanitizer: detected memory leaks`.

The expected values are correct and the test programs are the specification: the
defects are in the implementation, not in the expectations. Note that `fib(20)`
passes while `fib(24)` fails, and that `globals` fails on a name it has just
defined — the same code path behaves differently depending on how much state it
has accumulated.
