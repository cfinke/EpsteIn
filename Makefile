CC      = gcc
CFLAGS  = -Wall -Wextra -O2 -std=c11
LDFLAGS = -lcurl

TARGET  = epstein
SRCS    = epstein.c cJSON.c

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRCS) cJSON.h
	$(CC) $(CFLAGS) -o $(TARGET) $(SRCS) $(LDFLAGS)

clean:
	rm -f $(TARGET)
