#ifndef MVM_CHUNK_H
#define MVM_CHUNK_H

#include <stddef.h>
#include <stdint.h>

#include "value.h"

typedef enum {
    OP_CONST,
    OP_POP,
    OP_ADD,
    OP_SUB,
    OP_MUL,
    OP_DIV,
    OP_MOD,
    OP_LT,
    OP_GT,
    OP_EQ,
    OP_GET_LOCAL,
    OP_SET_LOCAL,
    OP_GET_GLOBAL,
    OP_SET_GLOBAL,
    OP_JUMP,
    OP_JUMP_IF_FALSE,
    OP_LOOP,
    OP_CALL,
    OP_RET,
    OP_HALT,
} OpCode;

typedef struct {
    uint8_t *code;
    size_t count;
    size_t capacity;
    Value *constants;
    size_t const_count;
    size_t const_capacity;
} Chunk;

struct Fun {
    Chunk *chunk;
    int arity;
    int nlocals;
    Str *name;
};

Chunk *chunk_new(void);
void chunk_free(Chunk *chunk);
void chunk_write(Chunk *chunk, uint8_t byte);
uint8_t chunk_constant(Chunk *chunk, Value value);
void chunk_emit(Chunk *chunk, uint8_t op);
void chunk_emit_arg(Chunk *chunk, uint8_t op, uint8_t arg);
size_t chunk_emit_jump(Chunk *chunk, uint8_t op);
void chunk_patch_jump(Chunk *chunk, size_t site);
void chunk_emit_loop(Chunk *chunk, size_t target);
size_t chunk_here(const Chunk *chunk);

#endif
