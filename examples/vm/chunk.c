#include "chunk.h"

#include <stdlib.h>

#define CODE_MIN 16
#define CONST_MIN 8

Chunk *chunk_new(void)
{
    Chunk *chunk = malloc(sizeof(Chunk));
    if (chunk == NULL) {
        return NULL;
    }
    chunk->code = NULL;
    chunk->count = 0;
    chunk->capacity = 0;
    chunk->constants = NULL;
    chunk->const_count = 0;
    chunk->const_capacity = 0;
    return chunk;
}

void chunk_free(Chunk *chunk)
{
    if (chunk == NULL) {
        return;
    }
    free(chunk->code);
    free(chunk->constants);
    free(chunk);
}

void chunk_write(Chunk *chunk, uint8_t byte)
{
    if (chunk->count + 1 > chunk->capacity) {
        size_t capacity = chunk->capacity < CODE_MIN ? CODE_MIN : chunk->capacity * 2;
        chunk->code = realloc(chunk->code, capacity);
        chunk->capacity = capacity;
    }
    chunk->code[chunk->count++] = byte;
}

uint8_t chunk_constant(Chunk *chunk, Value value)
{
    if (chunk->const_count + 1 > chunk->const_capacity) {
        size_t capacity = chunk->const_capacity < CONST_MIN ? CONST_MIN : chunk->const_capacity * 2;
        chunk->constants = realloc(chunk->constants, capacity * sizeof(Value));
        chunk->const_capacity = capacity;
    }
    chunk->constants[chunk->const_count] = value;
    return (uint8_t)chunk->const_count++;
}

void chunk_emit(Chunk *chunk, uint8_t op)
{
    chunk_write(chunk, op);
}

void chunk_emit_arg(Chunk *chunk, uint8_t op, uint8_t arg)
{
    chunk_write(chunk, op);
    chunk_write(chunk, arg);
}

size_t chunk_emit_jump(Chunk *chunk, uint8_t op)
{
    chunk_write(chunk, op);
    chunk_write(chunk, 0xff);
    chunk_write(chunk, 0xff);
    return chunk->count - 2;
}

void chunk_patch_jump(Chunk *chunk, size_t site)
{
    size_t jump = chunk->count - site - 2;
    chunk->code[site] = (uint8_t)((jump >> 8) & 0xff);
    chunk->code[site + 1] = (uint8_t)(jump & 0xff);
}

void chunk_emit_loop(Chunk *chunk, size_t target)
{
    chunk_write(chunk, OP_LOOP);
    size_t offset = chunk->count + 2 - target;
    chunk_write(chunk, (uint8_t)((offset >> 8) & 0xff));
    chunk_write(chunk, (uint8_t)(offset & 0xff));
}

size_t chunk_here(const Chunk *chunk)
{
    return chunk->count;
}
