CC ?= gcc
CFLAGS ?= -std=c11 -O1 -g -Wall -Wextra
LDFLAGS ?=

SRC = arena.c table.c chunk.c vm.c main.c
OBJ = $(SRC:.c=.o)
BIN = mvm

all: $(BIN)

$(BIN): $(OBJ)
	$(CC) $(CFLAGS) -o $@ $(OBJ) $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

run: $(BIN)
	./$(BIN)

asan:
	$(CC) $(CFLAGS) -fsanitize=address,undefined -o $(BIN)-asan $(SRC)
	./$(BIN)-asan

clean:
	rm -f $(OBJ) $(BIN) $(BIN)-asan

.PHONY: all run asan clean
