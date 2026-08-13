#include "table.h"

#include <stdlib.h>
#include <string.h>

#define TABLE_MIN 8
#define TABLE_MAX_LOAD_NUM 3
#define TABLE_MAX_LOAD_DEN 4

uint32_t str_hash(const char *chars, size_t len)
{
    uint32_t hash = 2166136261u;
    for (size_t i = 0; i < len; i++) {
        hash ^= (unsigned char)chars[i];
        hash *= 16777619u;
    }
    return hash;
}

void table_init(Table *table)
{
    table->count = 0;
    table->capacity = 0;
    table->entries = NULL;
}

void table_free(Table *table)
{
    free(table->entries);
    table_init(table);
}

static Entry *find_entry(Entry *entries, size_t capacity, Str *key)
{
    size_t index = key->hash & (capacity - 1);
    Entry *tombstone = NULL;

    for (;;) {
        Entry *entry = &entries[index];
        if (entry->key == NULL) {
            if (!entry->tombstone) {
                return tombstone != NULL ? tombstone : entry;
            }
            if (tombstone == NULL) {
                tombstone = entry;
            }
        } else if (entry->key == key) {
            return entry;
        }
        index = (index + 1) & (capacity - 1);
    }
}

static bool adjust_capacity(Table *table, size_t capacity)
{
    Entry *entries = malloc(sizeof(Entry) * capacity);
    if (entries == NULL) {
        return false;
    }
    for (size_t i = 0; i < capacity; i++) {
        entries[i].key = NULL;
        entries[i].value = INT_VAL(0);
        entries[i].tombstone = false;
    }

    size_t count = 0;
    for (size_t i = 0; i < table->capacity; i++) {
        Entry *entry = &table->entries[i];
        if (entry->key == NULL) {
            continue;
        }
        entries[i].key = entry->key;
        entries[i].value = entry->value;
        count++;
    }

    free(table->entries);
    table->entries = entries;
    table->capacity = capacity;
    table->count = count;
    return true;
}

bool table_set(Table *table, Str *key, Value value)
{
    if ((table->count + 1) * TABLE_MAX_LOAD_DEN > table->capacity * TABLE_MAX_LOAD_NUM) {
        size_t capacity = table->capacity < TABLE_MIN ? TABLE_MIN : table->capacity * 2;
        if (!adjust_capacity(table, capacity)) {
            return false;
        }
    }

    Entry *entry = find_entry(table->entries, table->capacity, key);
    bool is_new = entry->key == NULL;
    if (is_new && !entry->tombstone) {
        table->count++;
    }

    entry->key = key;
    entry->value = value;
    entry->tombstone = false;
    return is_new;
}

bool table_get(Table *table, Str *key, Value *out)
{
    if (table->count == 0) {
        return false;
    }

    Entry *entry = find_entry(table->entries, table->capacity, key);
    if (entry->key == NULL) {
        return false;
    }

    *out = entry->value;
    return true;
}

bool table_delete(Table *table, Str *key)
{
    if (table->count == 0) {
        return false;
    }

    Entry *entry = find_entry(table->entries, table->capacity, key);
    if (entry->key == NULL) {
        return false;
    }

    entry->key = NULL;
    entry->value = INT_VAL(0);
    entry->tombstone = false;
    table->count--;
    return true;
}

Str *table_find_string(Table *table, const char *chars, size_t len, uint32_t hash)
{
    if (table->count == 0) {
        return NULL;
    }

    size_t index = hash & (table->capacity - 1);
    for (;;) {
        Entry *entry = &table->entries[index];
        if (entry->key == NULL) {
            if (!entry->tombstone) {
                return NULL;
            }
        } else if (entry->key->hash == hash && entry->key->len == len &&
                   memcmp(entry->key->chars, chars, len) == 0) {
            return entry->key;
        }
        index = (index + 1) & (table->capacity - 1);
    }
}

Str *str_intern(Arena *arena, Table *strings, const char *chars, size_t len)
{
    uint32_t hash = str_hash(chars, len);
    Str *found = table_find_string(strings, chars, len, hash);
    if (found != NULL) {
        return found;
    }

    Str *string = arena_alloc(arena, sizeof(Str), sizeof(void *));
    if (string == NULL) {
        return NULL;
    }
    string->chars = arena_alloc(arena, len, 1);
    if (string->chars == NULL) {
        return NULL;
    }
    memcpy(string->chars, chars, len);
    string->chars[len] = '\0';
    string->len = len;
    string->hash = hash;

    table_set(strings, string, INT_VAL(0));
    return string;
}
