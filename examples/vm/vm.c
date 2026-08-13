#include "vm.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void runtime_error(VM *vm, const char *format, ...);

static bool stack_reserve(VM *vm, size_t extra)
{
    size_t used = (size_t)(vm->sp - vm->stack);
    if (used + extra <= vm->stack_capacity) {
        return true;
    }

    size_t capacity = vm->stack_capacity;
    while (used + extra > capacity) {
        capacity *= 2;
    }

    size_t offsets[FRAMES_MAX];
    for (int i = 0; i < vm->frame_count; i++) {
        offsets[i] = (size_t)(vm->frames[i].slots - vm->stack);
    }

    Value *stack = realloc(vm->stack, capacity * sizeof(Value));
    if (stack == NULL) {
        return false;
    }

    for (int i = 0; i < vm->frame_count; i++) {
        vm->frames[i].slots = stack + offsets[i];
    }
    vm->sp = stack + used;
    vm->stack = stack;
    vm->stack_capacity = capacity;
    return true;
}

static bool push(VM *vm, Value value)
{
    if (!stack_reserve(vm, 1)) {
        runtime_error(vm, "stack exhausted");
        return false;
    }
    *vm->sp++ = value;
    return true;
}

static Value pop(VM *vm)
{
    return *(--vm->sp);
}

static Value peek(VM *vm, int distance)
{
    return vm->sp[-1 - distance];
}

static void runtime_error(VM *vm, const char *format, ...)
{
    va_list args;
    va_start(args, format);
    vsnprintf(vm->error, sizeof(vm->error), format, args);
    va_end(args);
}

bool vm_init(VM *vm, Arena *arena)
{
    vm->stack = malloc(STACK_MIN * sizeof(Value));
    if (vm->stack == NULL) {
        return false;
    }
    vm->stack_capacity = STACK_MIN;
    vm->sp = vm->stack;
    vm->frame_count = 0;
    vm->arena = arena;
    vm->error[0] = '\0';
    table_init(&vm->globals);
    table_init(&vm->strings);
    return true;
}

void vm_free(VM *vm)
{
    free(vm->stack);
    vm->stack = NULL;
    vm->sp = NULL;
    vm->stack_capacity = 0;
    table_free(&vm->globals);
    table_free(&vm->strings);
}

Str *vm_intern(VM *vm, const char *chars)
{
    return str_intern(vm->arena, &vm->strings, chars, strlen(chars));
}

bool vm_define_global(VM *vm, const char *name, Value value)
{
    Str *key = vm_intern(vm, name);
    if (key == NULL) {
        return false;
    }
    table_set(&vm->globals, key, value);
    return true;
}

static bool call_fun(VM *vm, Fun *fn, int argc)
{
    if (argc != fn->arity) {
        runtime_error(vm, "%s expects %d arguments, got %d", fn->name->chars, fn->arity, argc);
        return false;
    }
    if (vm->frame_count == FRAMES_MAX) {
        runtime_error(vm, "call depth exceeded calling %s", fn->name->chars);
        return false;
    }

    int extra = fn->nlocals - fn->arity;
    if (!stack_reserve(vm, (size_t)extra)) {
        runtime_error(vm, "stack exhausted calling %s", fn->name->chars);
        return false;
    }
    for (int i = 0; i < extra; i++) {
        *vm->sp++ = INT_VAL(0);
    }

    Frame *frame = &vm->frames[vm->frame_count++];
    frame->fn = fn;
    frame->ip = fn->chunk->code;
    frame->slots = vm->sp - argc - 1;
    return true;
}

static bool check_numbers(VM *vm, const char *op)
{
    if (!IS_INT(peek(vm, 0)) || !IS_INT(peek(vm, 1))) {
        runtime_error(vm, "operands of %s must be numbers", op);
        return false;
    }
    return true;
}

RunResult vm_run(VM *vm, Fun *entry, Value *out)
{
    if (!push(vm, FUN_VAL(entry))) {
        return RUN_ERROR;
    }
    if (!call_fun(vm, entry, 0)) {
        return RUN_ERROR;
    }

    Frame *frame = &vm->frames[vm->frame_count - 1];

#define READ_BYTE() (*frame->ip++)
#define READ_SHORT() (frame->ip += 2, (uint16_t)((frame->ip[-2] << 8) | frame->ip[-1]))
#define READ_CONST() (frame->fn->chunk->constants[READ_BYTE()])
#define BINARY(op, name)                                    \
    do {                                                    \
        if (!check_numbers(vm, name)) return RUN_ERROR;     \
        Value b = pop(vm);                                  \
        Value a = pop(vm);                                  \
        if (!push(vm, INT_VAL(AS_INT(a) op AS_INT(b)))) {   \
            return RUN_ERROR;                               \
        }                                                   \
    } while (0)

    for (;;) {
        uint8_t instruction = READ_BYTE();
        switch (instruction) {
        case OP_CONST: {
            Value constant = READ_CONST();
            if (!push(vm, constant)) {
                return RUN_ERROR;
            }
            break;
        }
        case OP_POP:
            pop(vm);
            break;
        case OP_ADD:
            BINARY(+, "+");
            break;
        case OP_SUB:
            BINARY(-, "-");
            break;
        case OP_MUL:
            BINARY(*, "*");
            break;
        case OP_DIV: {
            if (!check_numbers(vm, "/")) {
                return RUN_ERROR;
            }
            if (AS_INT(peek(vm, 0)) == 0) {
                runtime_error(vm, "division by zero");
                return RUN_ERROR;
            }
            BINARY(/, "/");
            break;
        }
        case OP_MOD: {
            if (!check_numbers(vm, "%")) {
                return RUN_ERROR;
            }
            if (AS_INT(peek(vm, 0)) == 0) {
                runtime_error(vm, "modulo by zero");
                return RUN_ERROR;
            }
            Value divisor = pop(vm);
            Value dividend = pop(vm);
            if (!push(vm, INT_VAL(AS_INT(divisor) % AS_INT(dividend)))) {
                return RUN_ERROR;
            }
            break;
        }
        case OP_LT:
            BINARY(<, "<");
            break;
        case OP_GT:
            BINARY(>, ">");
            break;
        case OP_EQ:
            BINARY(==, "==");
            break;
        case OP_GET_LOCAL: {
            uint8_t slot = READ_BYTE();
            if (!push(vm, frame->slots[slot])) {
                return RUN_ERROR;
            }
            break;
        }
        case OP_SET_LOCAL: {
            uint8_t slot = READ_BYTE();
            frame->slots[slot] = pop(vm);
            break;
        }
        case OP_GET_GLOBAL: {
            Str *name = AS_STR(READ_CONST());
            Value value;
            if (!table_get(&vm->globals, name, &value)) {
                runtime_error(vm, "undefined global '%s'", name->chars);
                return RUN_ERROR;
            }
            if (!push(vm, value)) {
                return RUN_ERROR;
            }
            break;
        }
        case OP_SET_GLOBAL: {
            Str *name = AS_STR(READ_CONST());
            table_set(&vm->globals, name, pop(vm));
            break;
        }
        case OP_JUMP: {
            uint16_t offset = READ_SHORT();
            frame->ip += offset;
            break;
        }
        case OP_JUMP_IF_FALSE: {
            uint16_t offset = READ_SHORT();
            Value condition = pop(vm);
            if (AS_INT(condition) == 0) {
                frame->ip += offset;
            }
            break;
        }
        case OP_LOOP: {
            uint16_t offset = READ_SHORT();
            frame->ip -= offset;
            break;
        }
        case OP_CALL: {
            uint8_t argc = READ_BYTE();
            Value callee = peek(vm, argc);
            if (!IS_FUN(callee)) {
                runtime_error(vm, "can only call functions");
                return RUN_ERROR;
            }
            if (!call_fun(vm, AS_FUN(callee), argc)) {
                return RUN_ERROR;
            }
            frame = &vm->frames[vm->frame_count - 1];
            break;
        }
        case OP_RET: {
            Value result = pop(vm);
            vm->frame_count--;
            if (vm->frame_count == 0) {
                *out = result;
                return RUN_OK;
            }
            vm->sp = frame->slots;
            if (!push(vm, result)) {
                return RUN_ERROR;
            }
            frame = &vm->frames[vm->frame_count - 1];
            break;
        }
        case OP_HALT: {
            *out = pop(vm);
            return RUN_OK;
        }
        default:
            runtime_error(vm, "unknown opcode %d", instruction);
            return RUN_ERROR;
        }
    }

#undef READ_BYTE
#undef READ_SHORT
#undef READ_CONST
#undef BINARY
}
