#ifndef MVM_VALUE_H
#define MVM_VALUE_H

#include <stddef.h>
#include <stdint.h>

typedef struct Str {
    size_t len;
    uint32_t hash;
    char *chars;
} Str;

typedef struct Fun Fun;

typedef enum {
    V_INT,
    V_STR,
    V_FUN,
} ValueType;

typedef struct {
    ValueType type;
    union {
        long number;
        Str *string;
        Fun *function;
    } as;
} Value;

#define INT_VAL(value) ((Value){ .type = V_INT, .as.number = (value) })
#define STR_VAL(value) ((Value){ .type = V_STR, .as.string = (value) })
#define FUN_VAL(value) ((Value){ .type = V_FUN, .as.function = (value) })

#define AS_INT(value) ((value).as.number)
#define AS_STR(value) ((value).as.string)
#define AS_FUN(value) ((value).as.function)

#define IS_INT(value) ((value).type == V_INT)
#define IS_STR(value) ((value).type == V_STR)
#define IS_FUN(value) ((value).type == V_FUN)

#endif
