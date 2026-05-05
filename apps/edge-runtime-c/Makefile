BIN          := edge-runtime-c
SRC_DIR      := src
BUILD_DIR    := build
SRCS         := $(wildcard $(SRC_DIR)/*.c)
OBJS_DEBUG   := $(SRCS:$(SRC_DIR)/%.c=$(BUILD_DIR)/debug/%.o)
OBJS_RELEASE := $(SRCS:$(SRC_DIR)/%.c=$(BUILD_DIR)/release/%.o)

PKGS         := libmosquitto libcurl openssl json-c libmicrohttpd
PKG_CFLAGS   := $(shell pkg-config --cflags $(PKGS))
PKG_LIBS     := $(shell pkg-config --libs   $(PKGS))

WARN         := -Wall -Wextra -Wno-unused-parameter
COMMON       := $(WARN) -pthread $(PKG_CFLAGS) -D_GNU_SOURCE
CFLAGS_DEBUG := -O0 -g $(COMMON)
CFLAGS_REL   := -O2 -DNDEBUG $(COMMON)
LDLIBS       := $(PKG_LIBS) -lz -pthread

.PHONY: all debug release clean strip-release

all: release

debug: $(BUILD_DIR)/debug/$(BIN)

release: $(BUILD_DIR)/release/$(BIN) strip-release

$(BUILD_DIR)/debug/%.o: $(SRC_DIR)/%.c
	@mkdir -p $(@D)
	$(CC) $(CFLAGS_DEBUG) -c $< -o $@

$(BUILD_DIR)/release/%.o: $(SRC_DIR)/%.c
	@mkdir -p $(@D)
	$(CC) $(CFLAGS_REL) -c $< -o $@

$(BUILD_DIR)/debug/$(BIN): $(OBJS_DEBUG)
	$(CC) $(CFLAGS_DEBUG) $^ -o $@ $(LDLIBS)

$(BUILD_DIR)/release/$(BIN): $(OBJS_RELEASE)
	$(CC) $(CFLAGS_REL) $^ -o $@ $(LDLIBS)

strip-release: $(BUILD_DIR)/release/$(BIN)
	strip --strip-unneeded $(BUILD_DIR)/release/$(BIN) || true

clean:
	rm -rf $(BUILD_DIR)
