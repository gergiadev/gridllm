# examples

Codebases to point gridllm at.

| example | language | what it exercises |
|---|---|---|
| [`vm/`](vm/) | C11 | a bytecode virtual machine with an arena allocator and a hash table, carrying six planted defects |

## Running gridllm on an example

The agents work on the current directory, so run the tool from inside the example:

```bash
cd examples/vm
make run                     # see it fail
gridllm --tui "the test programs in main.c produce wrong results: find out why and fix it"
```

`ANSWERS-vm.md` in this directory is the answer key. It sits one level above the
example on purpose: with the workspace rooted at `examples/vm`, the MCP server
refuses every path outside it, so the agents cannot read it. Do not copy it into
the example directory unless you want the debate to find the answers instead of
the bugs.

## Judging the outcome

The example is designed so that success is not a matter of opinion:

```bash
make run     # exit status 0 and "all tests passed"
make asan    # no sanitizer error, no leak
```

Both must hold before and after any change the worker applies. The defects sit in
five different mechanisms (frame layout, arithmetic dispatch, rehashing, deletion,
allocation), so a run that fixes one test and breaks another is a partial result,
not a success.
