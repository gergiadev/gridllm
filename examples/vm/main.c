#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "arena.h"
#include "chunk.h"
#include "table.h"
#include "value.h"
#include "vm.h"

#define MAX_CHUNKS 32
#define GLOBAL_COUNT 12
#define KEY_COUNT 20

static Chunk *tracked[MAX_CHUNKS];
static size_t tracked_count;

static int failures;

static Fun *fun_new(Arena *arena, VM *vm, const char *name, int arity, int nlocals)
{
    Fun *fn = arena_alloc(arena, sizeof(Fun), sizeof(void *));
    if (fn == NULL) {
        return NULL;
    }
    fn->chunk = chunk_new();
    fn->arity = arity;
    fn->nlocals = nlocals;
    fn->name = vm_intern(vm, name);
    tracked[tracked_count++] = fn->chunk;
    return fn;
}

static Fun *build_fib(Arena *arena, VM *vm)
{
    Fun *fn = fun_new(arena, vm, "fib", 1, 1);
    Chunk *chunk = fn->chunk;
    uint8_t two = chunk_constant(chunk, INT_VAL(2));
    uint8_t one = chunk_constant(chunk, INT_VAL(1));
    uint8_t self = chunk_constant(chunk, STR_VAL(vm_intern(vm, "fib")));

    chunk_emit_arg(chunk, OP_GET_LOCAL, 1);
    chunk_emit_arg(chunk, OP_CONST, two);
    chunk_emit(chunk, OP_LT);
    size_t recurse = chunk_emit_jump(chunk, OP_JUMP_IF_FALSE);

    chunk_emit_arg(chunk, OP_GET_LOCAL, 1);
    chunk_emit(chunk, OP_RET);

    chunk_patch_jump(chunk, recurse);
    chunk_emit_arg(chunk, OP_GET_GLOBAL, self);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 1);
    chunk_emit_arg(chunk, OP_CONST, one);
    chunk_emit(chunk, OP_SUB);
    chunk_emit_arg(chunk, OP_CALL, 1);
    chunk_emit_arg(chunk, OP_GET_GLOBAL, self);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 1);
    chunk_emit_arg(chunk, OP_CONST, two);
    chunk_emit(chunk, OP_SUB);
    chunk_emit_arg(chunk, OP_CALL, 1);
    chunk_emit(chunk, OP_ADD);
    chunk_emit(chunk, OP_RET);
    return fn;
}

static Fun *build_sum(Arena *arena, VM *vm)
{
    Fun *fn = fun_new(arena, vm, "sum", 1, 3);
    Chunk *chunk = fn->chunk;
    uint8_t zero = chunk_constant(chunk, INT_VAL(0));
    uint8_t one = chunk_constant(chunk, INT_VAL(1));

    chunk_emit_arg(chunk, OP_CONST, zero);
    chunk_emit_arg(chunk, OP_SET_LOCAL, 2);
    chunk_emit_arg(chunk, OP_CONST, one);
    chunk_emit_arg(chunk, OP_SET_LOCAL, 3);

    size_t start = chunk_here(chunk);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 3);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 1);
    chunk_emit_arg(chunk, OP_CONST, one);
    chunk_emit(chunk, OP_ADD);
    chunk_emit(chunk, OP_LT);
    size_t done = chunk_emit_jump(chunk, OP_JUMP_IF_FALSE);

    chunk_emit_arg(chunk, OP_GET_LOCAL, 2);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 3);
    chunk_emit(chunk, OP_ADD);
    chunk_emit_arg(chunk, OP_SET_LOCAL, 2);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 3);
    chunk_emit_arg(chunk, OP_CONST, one);
    chunk_emit(chunk, OP_ADD);
    chunk_emit_arg(chunk, OP_SET_LOCAL, 3);
    chunk_emit_loop(chunk, start);

    chunk_patch_jump(chunk, done);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 2);
    chunk_emit(chunk, OP_RET);
    return fn;
}

static Fun *build_gcd(Arena *arena, VM *vm)
{
    Fun *fn = fun_new(arena, vm, "gcd", 2, 3);
    Chunk *chunk = fn->chunk;
    uint8_t zero = chunk_constant(chunk, INT_VAL(0));

    size_t start = chunk_here(chunk);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 2);
    chunk_emit_arg(chunk, OP_CONST, zero);
    chunk_emit(chunk, OP_EQ);
    size_t body = chunk_emit_jump(chunk, OP_JUMP_IF_FALSE);

    chunk_emit_arg(chunk, OP_GET_LOCAL, 1);
    chunk_emit(chunk, OP_RET);

    chunk_patch_jump(chunk, body);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 1);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 2);
    chunk_emit(chunk, OP_MOD);
    chunk_emit_arg(chunk, OP_SET_LOCAL, 3);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 2);
    chunk_emit_arg(chunk, OP_SET_LOCAL, 1);
    chunk_emit_arg(chunk, OP_GET_LOCAL, 3);
    chunk_emit_arg(chunk, OP_SET_LOCAL, 2);
    chunk_emit_loop(chunk, start);
    return fn;
}

static Fun *build_call1(Arena *arena, VM *vm, const char *callee, long argument)
{
    Fun *fn = fun_new(arena, vm, "main", 0, 0);
    Chunk *chunk = fn->chunk;
    uint8_t name = chunk_constant(chunk, STR_VAL(vm_intern(vm, callee)));
    uint8_t value = chunk_constant(chunk, INT_VAL(argument));

    chunk_emit_arg(chunk, OP_GET_GLOBAL, name);
    chunk_emit_arg(chunk, OP_CONST, value);
    chunk_emit_arg(chunk, OP_CALL, 1);
    chunk_emit(chunk, OP_HALT);
    return fn;
}

static Fun *build_call2(Arena *arena, VM *vm, const char *callee, long first, long second)
{
    Fun *fn = fun_new(arena, vm, "main", 0, 0);
    Chunk *chunk = fn->chunk;
    uint8_t name = chunk_constant(chunk, STR_VAL(vm_intern(vm, callee)));
    uint8_t left = chunk_constant(chunk, INT_VAL(first));
    uint8_t right = chunk_constant(chunk, INT_VAL(second));

    chunk_emit_arg(chunk, OP_GET_GLOBAL, name);
    chunk_emit_arg(chunk, OP_CONST, left);
    chunk_emit_arg(chunk, OP_CONST, right);
    chunk_emit_arg(chunk, OP_CALL, 2);
    chunk_emit(chunk, OP_HALT);
    return fn;
}

static Fun *build_globals(Arena *arena, VM *vm)
{
    Fun *fn = fun_new(arena, vm, "main", 0, 0);
    Chunk *chunk = fn->chunk;
    uint8_t names[GLOBAL_COUNT];
    uint8_t squares[GLOBAL_COUNT];
    char buffer[16];

    for (int i = 0; i < GLOBAL_COUNT; i++) {
        snprintf(buffer, sizeof(buffer), "g%d", i);
        names[i] = chunk_constant(chunk, STR_VAL(vm_intern(vm, buffer)));
        squares[i] = chunk_constant(chunk, INT_VAL((long)i * i));
    }

    for (int i = 0; i < GLOBAL_COUNT; i++) {
        chunk_emit_arg(chunk, OP_CONST, squares[i]);
        chunk_emit_arg(chunk, OP_SET_GLOBAL, names[i]);
    }

    uint8_t zero = chunk_constant(chunk, INT_VAL(0));
    chunk_emit_arg(chunk, OP_CONST, zero);
    for (int i = 0; i < GLOBAL_COUNT; i++) {
        chunk_emit_arg(chunk, OP_GET_GLOBAL, names[i]);
        chunk_emit(chunk, OP_ADD);
    }
    chunk_emit(chunk, OP_HALT);
    return fn;
}

static void report(const char *label, long got, long want)
{
    if (got == want) {
        printf("[ok]   %-28s = %ld\n", label, got);
        return;
    }
    printf("[FAIL] %-28s = %ld (want %ld)\n", label, got, want);
    failures++;
}

static void report_error(const char *label, const char *error, long want)
{
    printf("[FAIL] %-28s ! %s (want %ld)\n", label, error, want);
    failures++;
}

static void run_program(VM *vm, const char *label, Fun *entry, long want)
{
    Value result;
    vm->sp = vm->stack;
    vm->frame_count = 0;
    vm->error[0] = '\0';

    if (vm_run(vm, entry, &result) != RUN_OK) {
        report_error(label, vm->error, want);
        return;
    }
    if (!IS_INT(result)) {
        report_error(label, "result is not a number", want);
        return;
    }
    report(label, AS_INT(result), want);
}

static void test_interning(VM *vm)
{
    Str *first = vm_intern(vm, "counter");
    Str *second = vm_intern(vm, "counter");
    report("intern identity", first == second ? 1 : 0, 1);

    Str *prefix = vm_intern(vm, "count");
    report("intern prefix distinct", prefix != first ? 1 : 0, 1);
    report("intern prefix length", (long)prefix->len, 5);
}

static void test_table_tombstones(VM *vm)
{
    Table table;
    table_init(&table);
    Str *keys[KEY_COUNT];
    char buffer[16];

    for (int i = 0; i < KEY_COUNT; i++) {
        snprintf(buffer, sizeof(buffer), "key%d", i);
        keys[i] = vm_intern(vm, buffer);
        table_set(&table, keys[i], INT_VAL(i * 10));
    }

    for (int i = 0; i < KEY_COUNT; i += 2) {
        table_delete(&table, keys[i]);
    }

    long found = 0;
    long wrong = 0;
    for (int i = 1; i < KEY_COUNT; i += 2) {
        Value value;
        if (!table_get(&table, keys[i], &value)) {
            continue;
        }
        found++;
        if (AS_INT(value) != i * 10) {
            wrong++;
        }
    }
    report("table survivors found", found, KEY_COUNT / 2);
    report("table survivors correct", wrong, 0);

    long ghosts = 0;
    for (int i = 0; i < KEY_COUNT; i += 2) {
        Value value;
        if (table_get(&table, keys[i], &value)) {
            ghosts++;
        }
    }
    report("table deleted stay gone", ghosts, 0);

    table_free(&table);
}

int main(void)
{
    Arena arena;
    arena_init(&arena, 256);

    VM vm;
    if (!vm_init(&vm, &arena)) {
        fprintf(stderr, "cannot initialise the vm\n");
        return 2;
    }

    Fun *fib = build_fib(&arena, &vm);
    Fun *sum = build_sum(&arena, &vm);
    Fun *gcd = build_gcd(&arena, &vm);
    vm_define_global(&vm, "fib", FUN_VAL(fib));
    vm_define_global(&vm, "sum", FUN_VAL(sum));
    vm_define_global(&vm, "gcd", FUN_VAL(gcd));

    run_program(&vm, "fib(20)", build_call1(&arena, &vm, "fib", 20), 6765);
    run_program(&vm, "sum(1..100)", build_call1(&arena, &vm, "sum", 100), 5050);
    run_program(&vm, "gcd(1071, 462)", build_call2(&arena, &vm, "gcd", 1071, 462), 21);
    run_program(&vm, "globals g0..g11", build_globals(&arena, &vm), 506);
    run_program(&vm, "fib(24)", build_call1(&arena, &vm, "fib", 24), 46368);

    test_interning(&vm);
    test_table_tombstones(&vm);

    for (size_t i = 0; i < tracked_count; i++) {
        chunk_free(tracked[i]);
    }
    vm_free(&vm);
    arena_free(&arena);

    if (failures > 0) {
        printf("\n%d test(s) failed\n", failures);
        return 1;
    }
    printf("\nall tests passed\n");
    return 0;
}
