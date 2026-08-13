#include "arena.h"

#include <stdlib.h>
#include <string.h>

#define DEFAULT_BLOCK 4096

static size_t align_up(size_t value, size_t align)
{
    return (value + align - 1) & ~(align - 1);
}

static Block *block_new(size_t capacity)
{
    Block *block = malloc(sizeof(Block));
    if (block == NULL) {
        return NULL;
    }
    block->data = malloc(capacity);
    if (block->data == NULL) {
        free(block);
        return NULL;
    }
    block->next = NULL;
    block->used = 0;
    block->capacity = capacity;
    return block;
}

void arena_init(Arena *arena, size_t block_size)
{
    arena->head = NULL;
    arena->block_size = block_size == 0 ? DEFAULT_BLOCK : block_size;
    arena->allocated = 0;
    arena->wasted = 0;
}

void *arena_alloc(Arena *arena, size_t size, size_t align)
{
    if (size == 0) {
        return NULL;
    }

    Block *block = arena->head;
    if (block != NULL) {
        size_t offset = align_up(block->used, align);
        if (offset + size <= block->capacity) {
            arena->wasted += offset - block->used;
            block->used = offset + size;
            arena->allocated += size;
            return block->data + offset;
        }
    }

    size_t capacity = arena->block_size;
    size_t needed = align_up(size, align);
    if (needed > capacity) {
        capacity = needed;
    }

    Block *fresh = block_new(capacity);
    if (fresh == NULL) {
        return NULL;
    }
    arena->head = fresh;

    fresh->used = size;
    arena->allocated += size;
    return fresh->data;
}

void arena_free(Arena *arena)
{
    Block *block = arena->head;
    while (block != NULL) {
        Block *next = block->next;
        free(block->data);
        free(block);
        block = next;
    }
    arena->head = NULL;
    arena->allocated = 0;
    arena->wasted = 0;
}
