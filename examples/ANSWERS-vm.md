# Answer key for `vm/` — six planted defects

Keep this file out of the example directory: with the workspace rooted at
`examples/vm`, the agents cannot reach it.

The example was written correct first, verified green under `make run` and
`make asan`, and only then broken in exactly six places. Nothing else differs from
the working version, so anything a run reports outside this list is either a real
extra finding or a false positive.

## 1. `vm.c:133` — the frame anchors on the arguments instead of the locals

```c
frame->slots = vm->sp - argc - 1;      /* wrong */
frame->slots = vm->sp - fn->nlocals - 1;
```

`call_fun` reserves `nlocals - arity` extra slots before anchoring the frame, so
the base has to step back over all of them. Stepping back over `argc` only leaves
`slots` pointing into the middle of the frame, and every `OP_GET_LOCAL` /
`OP_SET_LOCAL` addresses the wrong cell.

**Why it is subtle**: for any function whose locals are exactly its parameters,
`argc == nlocals` and the two expressions agree. `fib` has one parameter and one
local, so `fib(20)` keeps passing. Only `sum` (1 parameter, 3 locals) and `gcd`
(2 parameters, 3 locals) drift.

**Symptom**: `sum(1..100) = 0` — the loop counter is read from a cell that never
gets updated, so the guard is false on the first iteration.

## 2. `vm.c:213` — the operands of `%` are used in reverse

```c
Value divisor = pop(vm);
Value dividend = pop(vm);
push(vm, INT_VAL(AS_INT(divisor) % AS_INT(dividend)));   /* wrong order */
```

The stack pops right-hand side first, so the expression has to be
`dividend % divisor`. Every other binary operator goes through the `BINARY` macro,
which gets the order right; `OP_MOD` is the only one open-coded, which is exactly
what hides the inversion.

**Symptom**: `gcd(1071, 462) = 462`. Euclid still terminates, so the failure looks
like a wrong algorithm rather than a wrong operator.

## 3. `table.c:72` — growing the table does not rehash

```c
entries[i].key = entry->key;      /* wrong: keeps the old index */
entries[i].value = entry->value;
```

```c
Entry *dest = find_entry(entries, capacity, entry->key);
dest->key = entry->key;
dest->value = entry->value;
```

The bucket index is `hash & (capacity - 1)`: when the capacity doubles, the mask
changes and roughly half the entries belong in a different bucket. Copying by
index leaves them where they were, so a later lookup probes the right bucket,
finds an empty slot and reports "not found".

**Why it is subtle**: it only bites after the first growth, and only for the
entries whose bucket moved. Every table smaller than the load factor works
perfectly.

**Symptom**: `undefined global 'g1'` on a global assigned three instructions
earlier, and `undefined global 'fib'` on the *second* `fib` test but not the
first — the globals table grew in between.

## 4. `table.c:133` — deletion clears the slot instead of leaving a tombstone

```c
entry->tombstone = false;
table->count--;                   /* wrong on both lines */
```

```c
entry->tombstone = true;
```

Linear probing relies on a deleted entry still terminating nothing: an empty slot
stops the probe, a tombstone does not. Clearing the slot cuts every chain that ran
through it, and decrementing `count` also lets the table exceed its load factor
and, in the worst case, fill up completely.

**Symptom**: `table survivors found = 7` instead of 10 — three keys that were
never deleted become unreachable because a deleted neighbour broke their chain.

## 5. `table.c:171` — the interned string has no room for its terminator

```c
string->chars = arena_alloc(arena, len, 1);       /* wrong */
string->chars = arena_alloc(arena, len + 1, 1);
```

The next line writes `string->chars[len] = '\0'`, one byte past the allocation.
The arena hands out consecutive slices of one `malloc`ed block, so the write lands
on the first byte of whatever is allocated next.

**Symptom**: none on these inputs, and ASan cannot see it either — the overflow
stays inside a block the allocator already owns. It is the one defect here that
the tests do not catch, and the reason the review has to read the code rather than
trust the harness. It becomes a crash the day a string ends exactly on a block
boundary.

## 6. `arena.c:65` — a new block drops the previous ones

```c
arena->head = fresh;                  /* wrong: the chain is lost */
```

```c
fresh->next = arena->head;
arena->head = fresh;
```

`arena_free` walks `head->next`, so every block but the last is leaked. With
4096-byte blocks the example never allocated a second one and the defect was
invisible; `main.c` now initialises the arena with 256-byte blocks, which is what
makes it observable.

**Symptom**: `make asan` reports `SUMMARY: AddressSanitizer: 672 byte(s) leaked in
7 allocation(s)`. `make run` stays silent about it.

## Expected coverage

| defect | caught by |
|---|---|
| 1 frame anchor | `sum(1..100)` |
| 2 modulo order | `gcd(1071, 462)` |
| 3 missing rehash | `globals g0..g11`, `fib(24)`, `table survivors found` |
| 4 lost tombstone | `table survivors found` |
| 5 missing terminator byte | nothing — reading only |
| 6 leaked arena blocks | `make asan` |
