#ifndef MVM_VM_H
#define MVM_VM_H

#include <stdbool.h>

#include "arena.h"
#include "chunk.h"
#include "table.h"
#include "value.h"

#define FRAMES_MAX 64
#define STACK_MIN 16

typedef struct {
    Fun *fn;
    uint8_t *ip;
    Value *slots;
} Frame;

typedef struct {
    Value *stack;
    size_t stack_capacity;
    Value *sp;
    Frame frames[FRAMES_MAX];
    int frame_count;
    Table globals;
    Table strings;
    Arena *arena;
    char error[160];
} VM;

typedef enum {
    RUN_OK,
    RUN_ERROR,
} RunResult;

bool vm_init(VM *vm, Arena *arena);
void vm_free(VM *vm);
Str *vm_intern(VM *vm, const char *chars);
bool vm_define_global(VM *vm, const char *name, Value value);
RunResult vm_run(VM *vm, Fun *entry, Value *out);

#endif
