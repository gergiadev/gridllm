#ifndef MVM_TABLE_H
#define MVM_TABLE_H

#include <stdbool.h>

#include "arena.h"
#include "value.h"

typedef struct {
    Str *key;
    Value value;
    bool tombstone;
} Entry;

typedef struct {
    size_t count;
    size_t capacity;
    Entry *entries;
} Table;

void table_init(Table *table);
void table_free(Table *table);
bool table_set(Table *table, Str *key, Value value);
bool table_get(Table *table, Str *key, Value *out);
bool table_delete(Table *table, Str *key);
Str *table_find_string(Table *table, const char *chars, size_t len, uint32_t hash);

uint32_t str_hash(const char *chars, size_t len);
Str *str_intern(Arena *arena, Table *strings, const char *chars, size_t len);

#endif
