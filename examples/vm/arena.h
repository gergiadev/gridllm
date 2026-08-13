#ifndef MVM_ARENA_H
#define MVM_ARENA_H

#include <stddef.h>

typedef struct Block {
    struct Block *next;
    size_t used;
    size_t capacity;
    unsigned char *data;
} Block;

typedef struct {
    Block *head;
    size_t block_size;
    size_t allocated;
    size_t wasted;
} Arena;

void arena_init(Arena *arena, size_t block_size);
void *arena_alloc(Arena *arena, size_t size, size_t align);
void arena_free(Arena *arena);

#endif
