#include "recomp.h"

#include <direct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <windows.h>

static int failures;

static void fail_u32(const char *what, uint32_t got, uint32_t expected) {
    fprintf(stderr, "FAIL: %s: got 0x%08x, expected 0x%08x\n", what, got, expected);
    failures++;
}

static void check_u32(const char *what, uint32_t got, uint32_t expected) {
    if (got != expected) fail_u32(what, got, expected);
}

static void check_guest_bytes(const char *what, uint32_t addr, const uint8_t *expected,
                              uint32_t size) {
    for (uint32_t i = 0; i < size; i++) {
        uint32_t got = MEM_R8(addr + i);
        if (got != expected[i]) {
            char label[128];
            snprintf(label, sizeof(label), "%s byte %u", what, i);
            fail_u32(label, got, expected[i]);
        }
    }
}

static void guest_string(uint32_t addr, const char *text) {
    size_t n = strlen(text);
    for (size_t i = 0; i <= n; i++) MEM_W8(addr + (uint32_t)i, (uint8_t)text[i]);
}

static void guest_bytes(uint32_t addr, const void *data, uint32_t size) {
    const uint8_t *bytes = (const uint8_t *)data;
    for (uint32_t i = 0; i < size; i++) MEM_W8(addr + i, bytes[i]);
}

static void guest_read_string(uint32_t addr, char *out, size_t size) {
    size_t i = 0;
    for (; i + 1 < size && MEM_R8(addr + (uint32_t)i); i++)
        out[i] = (char)MEM_R8(addr + (uint32_t)i);
    out[i] = 0;
}

static uint32_t hle_call(CpuState *cpu, uint32_t nid, uint32_t a0, uint32_t a1,
                         uint32_t a2, uint32_t a3) {
    memset(cpu, 0, sizeof(*cpu));
    cpu->r[4] = a0;
    cpu->r[5] = a1;
    cpu->r[6] = a2;
    cpu->r[7] = a3;
    sr_syscall(cpu, nid);
    return cpu->r[2];
}

static uint32_t hle_call7(CpuState *cpu, uint32_t nid, uint32_t a0, uint32_t a1,
                          uint32_t a2, uint32_t a3, uint32_t a4, uint32_t a5,
                          uint32_t a6) {
    memset(cpu, 0, sizeof(*cpu));
    cpu->r[4] = a0;
    cpu->r[5] = a1;
    cpu->r[6] = a2;
    cpu->r[7] = a3;
    cpu->r[8] = a4;
    cpu->r[9] = a5;
    cpu->r[10] = a6;
    sr_syscall(cpu, nid);
    return cpu->r[2];
}

static uint32_t running_hle_call(CpuState *cpu, uint32_t nid, uint32_t a0, uint32_t a1,
                                 uint32_t a2, uint32_t a3) {
    cpu->r[4] = a0;
    cpu->r[5] = a1;
    cpu->r[6] = a2;
    cpu->r[7] = a3;
    sr_syscall(cpu, nid);
    return cpu->r[2];
}

static uint32_t write_file(CpuState *cpu, uint32_t path_addr, const char *path,
                           uint32_t data_addr, const char *data) {
    guest_string(path_addr, path);
    uint32_t fd = hle_call(cpu, 0x109f50bcu, path_addr, 0x0602u, 0777u, 0);
    if ((int32_t)fd < 0) return fd;
    uint32_t size = (uint32_t)strlen(data);
    guest_bytes(data_addr, data, size);
    uint32_t wrote = hle_call(cpu, 0x42ec03acu, fd, data_addr, size, 0);
    if (wrote != size) return wrote;
    return hle_call(cpu, 0x810c4bc3u, fd, 0, 0, 0);
}

static void test_threadman(CpuState *cpu) {
    const uint32_t name_addr = 0x08810000u;
    const uint32_t status_addr = 0x08811000u;
    const uint32_t ids_addr = 0x08812000u;
    const uint32_t count_addr = 0x08812100u;
    guest_string(name_addr, "hle-smoke");
    check_u32("set SDK version", hle_call(cpu, 0x7591c7dbu, 0x06060110u, 0, 0, 0), 0);

    memset(cpu, 0, sizeof(*cpu));
    cpu->r[4] = name_addr;
    cpu->r[5] = 0x08804000u;
    cpu->r[6] = 32;
    cpu->r[7] = 0x400;
    cpu->r[8] = 0x80000000u;
    sr_syscall(cpu, 0x446d8de6u);
    uint32_t uid = cpu->r[2];
    if ((int32_t)uid < 0) {
        fail_u32("create thread", uid, 0);
        return;
    }

    MEM_W32(status_addr, 108);
    check_u32("refer thread status",
              hle_call(cpu, 0x17c1684eu, uid, status_addr, 0, 0), 0);
    check_u32("thread status native size", MEM_R32(status_addr), 108);
    check_u32("thread status attr", MEM_R32(status_addr + 0x24), 0x80000000u);
    check_u32("thread status dormant", MEM_R32(status_addr + 0x28), 16);
    check_u32("thread status entry", MEM_R32(status_addr + 0x2c), 0x08804000u);
    check_u32("thread status stack size", MEM_R32(status_addr + 0x34), 0x400);
    check_u32("thread initial priority", MEM_R32(status_addr + 0x3c), 32);
    check_u32("thread current priority", MEM_R32(status_addr + 0x40), 32);
    char name[32];
    guest_read_string(status_addr + 4, name, sizeof(name));
    if (strcmp(name, "hle-smoke") != 0) {
        fprintf(stderr, "FAIL: thread status name: got \"%s\"\n", name);
        failures++;
    }

    check_u32("never-started exit status",
              hle_call(cpu, 0x3b183e26u, uid, 0, 0, 0), 0x800201a4u);
    MEM_W32(count_addr, 0xccccccccu);
    check_u32("thread ID list count",
              hle_call(cpu, 0x94416130u, 1, ids_addr, 8, count_addr), 1);
    check_u32("thread ID list total", MEM_R32(count_addr), 1);
    check_u32("thread ID list value", MEM_R32(ids_addr), uid);
    check_u32("dormant thread list count",
              hle_call(cpu, 0x94416130u, 67, ids_addr, 8, count_addr), 1);
    check_u32("invalid thread list type",
              hle_call(cpu, 0x94416130u, 63, ids_addr, 8, count_addr), 0x800201bbu);

    check_u32("delete thread", hle_call(cpu, 0x9fa03cd3u, uid, 0, 0, 0), 0);
    check_u32("thread list after delete",
              hle_call(cpu, 0x94416130u, 1, ids_addr, 8, count_addr), 0);
    check_u32("deleted thread exit status",
              hle_call(cpu, 0x3b183e26u, uid, 0, 0, 0), 0x80020198u);
}

static void test_time(CpuState *cpu) {
    const uint32_t clock_addr = 0x08813000u;
    const uint32_t seconds_addr = 0x08813010u;
    const uint32_t usec_addr = 0x08813014u;
    uint64_t clock = 1234567;
    MEM_W32(clock_addr, (uint32_t)clock);
    MEM_W32(clock_addr + 4, (uint32_t)(clock >> 32));
    check_u32("SysClock2USec return",
              hle_call(cpu, 0xba6b92e2u, clock_addr, seconds_addr, usec_addr, 0), 0);
    check_u32("SysClock2USec seconds", MEM_R32(seconds_addr), 1);
    check_u32("SysClock2USec remainder", MEM_R32(usec_addr), 234567);
}

static void test_io(CpuState *cpu, const char *root) {
    const uint32_t path_addr = 0x08814000u;
    const uint32_t data_addr = 0x08815000u;
    const uint32_t dirent_addr = 0x08816000u;
    const uint32_t stat_addr = 0x08817000u;
    const char *path_a = "ms0:/PSP/TEST/A_FILE.DAT";
    const char *path_b = "ms0:/PSP/TEST/B.DAT";
    const char *dir_path = "ms0:/PSP/TEST";

    check_u32("write A", write_file(cpu, path_addr, path_a, data_addr, "alpha"), 0);
    check_u32("write B", write_file(cpu, path_addr, path_b, data_addr, "bravo!"), 0);

    guest_string(path_addr, path_a);
    check_u32("host getstat", hle_call(cpu, 0xace946e8u, path_addr, stat_addr, 0, 0), 0);
    check_u32("host getstat attr", MEM_R32(stat_addr + 4), 0x20);
    check_u32("host getstat size", MEM_R32(stat_addr + 8), 5);

    guest_string(path_addr, dir_path);
    check_u32("rmdir nonempty",
              hle_call(cpu, 0x1117c65fu, path_addr, 0, 0, 0), 0x8001005au);
    uint32_t dir = hle_call(cpu, 0xb29ddf9cu, path_addr, 0, 0, 0);
    if ((int32_t)dir < 0) {
        fail_u32("dopen host directory", dir, 0);
        return;
    }

    int saw_a = 0, saw_b = 0, entries = 0;
    for (;;) {
        uint32_t result = hle_call(cpu, 0xe3eb004cu, dir, dirent_addr, 0, 0);
        if (result == 0) break;
        if (result != 1) {
            fail_u32("dread host directory", result, 1);
            break;
        }
        char name[256];
        guest_read_string(dirent_addr + 0x58, name, sizeof(name));
        uint32_t attr = MEM_R32(dirent_addr + 4);
        if (!strcmp(name, "A_FILE.DAT")) {
            saw_a = 1;
            check_u32("A dirent size", MEM_R32(dirent_addr + 8), 5);
        } else if (!strcmp(name, "B.DAT")) {
            saw_b = 1;
            check_u32("B dirent size", MEM_R32(dirent_addr + 8), 6);
        }
        check_u32("file dirent attr", attr, 0x20);
        entries++;
    }
    check_u32("host directory entry count", (uint32_t)entries, 2);
    check_u32("host directory contains A", (uint32_t)saw_a, 1);
    check_u32("host directory contains B", (uint32_t)saw_b, 1);
    check_u32("dclose host directory", hle_call(cpu, 0xeb092469u, dir, 0, 0, 0), 0);
    check_u32("dread closed directory",
              hle_call(cpu, 0xe3eb004cu, dir, dirent_addr, 0, 0), 0x80010009u);

    guest_string(path_addr, path_a);
    check_u32("remove A", hle_call(cpu, 0xf27a9c51u, path_addr, 0, 0, 0), 0);
    guest_string(path_addr, path_b);
    check_u32("remove B", hle_call(cpu, 0xf27a9c51u, path_addr, 0, 0, 0), 0);
    guest_string(path_addr, dir_path);
    check_u32("rmdir empty", hle_call(cpu, 0x1117c65fu, path_addr, 0, 0, 0), 0);

    char path[512];
    snprintf(path, sizeof(path), "%s\\ms0\\PSP", root);
    _rmdir(path);
    snprintf(path, sizeof(path), "%s\\ms0", root);
    _rmdir(path);
    _rmdir(root);
}

static void test_default_vfs_root(CpuState *cpu, const char *local_app_data) {
    const uint32_t path_addr = 0x08818000u;
    const uint32_t data_addr = 0x08818100u;
    const uint32_t read_addr = 0x08818200u;
    const uint32_t stat_addr = 0x08818300u;
    static const uint8_t expected[] = "chapter5";

    check_u32("write Chapter 5 through cache alias",
              write_file(cpu, path_addr, "cache:CHAPTER5.BIN", data_addr, (const char *)expected), 0);

    guest_string(path_addr, "fatms0:/CHAPTER5.BIN");
    check_u32("stat Chapter 5 through fatms alias",
              hle_call(cpu, 0xace946e8u, path_addr, stat_addr, 0, 0), 0);
    check_u32("Chapter 5 size", MEM_R32(stat_addr + 8), sizeof(expected) - 1);

    guest_string(path_addr, "ms0:/CHAPTER5.BIN");
    uint32_t fd = hle_call(cpu, 0x109f50bcu, path_addr, 1, 0, 0);
    if ((int32_t)fd < 0) {
        fail_u32("open Chapter 5 through ms0", fd, 0);
    } else {
        check_u32("read Chapter 5 through ms0",
                  hle_call(cpu, 0x6a638d83u, fd, read_addr, sizeof(expected) - 1, 0),
                  sizeof(expected) - 1);
        check_guest_bytes("Chapter 5 contents", read_addr, expected, sizeof(expected) - 1);
        check_u32("close Chapter 5", hle_call(cpu, 0x810c4bc3u, fd, 0, 0, 0), 0);
    }

    char path[512];
    struct _stat64 info;
    snprintf(path, sizeof(path), "%s\\KZLRecomp\\ms0\\CHAPTER5.BIN", local_app_data);
    if (_stat64(path, &info) != 0) {
        fprintf(stderr, "FAIL: default VFS path does not exist: %s\n", path);
        failures++;
    } else {
        check_u32("default VFS physical size", (uint32_t)info.st_size, sizeof(expected) - 1);
    }

    guest_string(path_addr, "cache:/CHAPTER5.BIN");
    check_u32("remove Chapter 5 through cache alias",
              hle_call(cpu, 0xf27a9c51u, path_addr, 0, 0, 0), 0);
    snprintf(path, sizeof(path), "%s\\KZLRecomp\\ms0", local_app_data);
    _rmdir(path);
    snprintf(path, sizeof(path), "%s\\KZLRecomp", local_app_data);
    _rmdir(path);
    _rmdir(local_app_data);
}

static uint32_t mpeg_callback_packets;
static uint32_t mpeg_callback_end_packet;
static uint64_t mpeg_callback_duration;

static void guest_mpeg_scr(uint32_t addr, uint64_t value) {
    MEM_W8(addr + 0, 0);
    MEM_W8(addr + 1, 0);
    MEM_W8(addr + 2, 1);
    MEM_W8(addr + 3, 0xba);
    MEM_W8(addr + 4, (uint8_t)(0x44 | ((value >> 27) & 0x38) | ((value >> 28) & 0x03)));
    MEM_W8(addr + 5, (uint8_t)(value >> 20));
    MEM_W8(addr + 6, (uint8_t)(0x04 | ((value >> 12) & 0xf8) | ((value >> 13) & 0x03)));
    MEM_W8(addr + 7, (uint8_t)(value >> 5));
    MEM_W8(addr + 8, (uint8_t)(0x04 | ((value << 3) & 0xf8)));
}

static void mpeg_fill_callback(CpuState *cpu) {
    for (uint32_t i = 0; i < cpu->r[5]; i++) {
        uint32_t packet = mpeg_callback_packets + i + 1;
        uint64_t scr = mpeg_callback_duration * packet / mpeg_callback_end_packet;
        guest_mpeg_scr(cpu->r[4] + i * 2048, scr);
    }
    mpeg_callback_packets += cpu->r[5];
    cpu->r[2] = cpu->r[5];
}

static void guest_be32(uint32_t addr, uint32_t value) {
    MEM_W8(addr + 0, (uint8_t)(value >> 24));
    MEM_W8(addr + 1, (uint8_t)(value >> 16));
    MEM_W8(addr + 2, (uint8_t)(value >> 8));
    MEM_W8(addr + 3, (uint8_t)value);
}

static void guest_mpeg_timestamp(uint32_t addr, uint64_t value) {
    MEM_W8(addr + 0, 0);
    MEM_W8(addr + 1, (uint8_t)(value >> 32));
    MEM_W8(addr + 2, (uint8_t)(value >> 24));
    MEM_W8(addr + 3, (uint8_t)(value >> 16));
    MEM_W8(addr + 4, (uint8_t)(value >> 8));
    MEM_W8(addr + 5, (uint8_t)value);
}

static void test_mpeg_eof(CpuState *cpu) {
    const uint32_t mpeg_addr = 0x0881c000u;
    const uint32_t ring_addr = 0x0881c100u;
    const uint32_t header_addr = 0x0881c200u;
    const uint32_t offset_addr = 0x0881c300u;
    const uint32_t au_addr = 0x0881c400u;
    const uint32_t attr_addr = 0x0881c420u;
    const uint32_t buffer_addr = 0x0881c430u;
    const uint32_t init_addr = 0x0881c434u;
    const uint32_t callback_addr = 0x0881d000u;
    const uint32_t context_addr = 0x08830000u;
    const uint32_t ring_data_addr = 0x08850000u;
    const uint32_t packet_count = 10;
    const uint32_t ring_packets = 4;
    const uint64_t first_timestamp = 90000;
    const uint64_t last_timestamp = first_timestamp + 3 * 3003;
    const uint32_t end_packet = 3;

    for (uint32_t i = 0; i < 0x800; i++) MEM_W8(header_addr + i, 0);
    MEM_W32(header_addr, 0x464d5350u);
    MEM_W32(header_addr + 4, 0x35313030u);
    guest_be32(header_addr + 8, 2048);
    guest_be32(header_addr + 12, packet_count * 2048);
    guest_mpeg_timestamp(header_addr + 0x54, first_timestamp);
    guest_mpeg_timestamp(header_addr + 0x5a, last_timestamp);
    MEM_W32(buffer_addr, 0);
    sr_register(callback_addr, mpeg_fill_callback);
    mpeg_callback_packets = 0;
    mpeg_callback_end_packet = end_packet;
    mpeg_callback_duration = last_timestamp - first_timestamp;

    check_u32("mpeg init", hle_call(cpu, 0x682a619bu, 0, 0, 0, 0), 0);
    check_u32("mpeg query memory", hle_call(cpu, 0xc132e22fu, 0, 0, 0, 0), 0x10000);
    check_u32("mpeg ring construct",
              hle_call7(cpu, 0x37295ed8u, ring_addr, ring_packets, ring_data_addr,
                        ring_packets * (104 + 2048), callback_addr, 0, 0), 0);
    check_u32("mpeg create",
              hle_call7(cpu, 0xd8c5f121u, mpeg_addr, context_addr, 0x10000,
                        ring_addr, 512, 0, 0), 0);
    check_u32("mpeg stream offset",
              hle_call(cpu, 0x21ff80e4u, mpeg_addr, header_addr, offset_addr, 0), 0);
    check_u32("mpeg stream offset value", MEM_R32(offset_addr), 2048);
    uint32_t es_buffer = hle_call(cpu, 0xa780cf7eu, mpeg_addr, 0, 0, 0);
    check_u32("mpeg AVC ES buffer", es_buffer, 1);
    check_u32("mpeg init AVC AU",
              hle_call(cpu, 0x167afd9eu, mpeg_addr, es_buffer, au_addr, 0), 0);
    uint32_t video_stream = hle_call(cpu, 0x42560f23u, mpeg_addr, 0, 0, 0);
    check_u32("mpeg video stream", video_stream, 1);

    check_u32("mpeg initial available",
              hle_call(cpu, 0xb5f6dc87u, ring_addr, 0, 0, 0), ring_packets);
    check_u32("mpeg initial fill",
              hle_call(cpu, 0xb240a59eu, ring_addr, end_packet, ring_packets, 0), end_packet);

    for (uint32_t frame = 0; frame < 3; frame++) {
        check_u32("mpeg get AVC AU",
                  hle_call(cpu, 0xfe246728u, mpeg_addr, video_stream, au_addr, attr_addr), 0);
        check_u32("mpeg AVC decode",
                  hle_call7(cpu, 0x0e3c2e9du, mpeg_addr, au_addr, 512,
                            buffer_addr, init_addr, 0, 0), 0);
    }

    check_u32("mpeg decoder tail drains ring",
              hle_call(cpu, 0xb5f6dc87u, ring_addr, 0, 0, 0), ring_packets);
    check_u32("mpeg callback packet total", mpeg_callback_packets, end_packet);
    check_u32("mpeg video end",
              hle_call(cpu, 0xfe246728u, mpeg_addr, video_stream, au_addr, attr_addr), 0x80618001u);
    check_u32("mpeg end drains ring",
              hle_call(cpu, 0xb5f6dc87u, ring_addr, 0, 0, 0), ring_packets);
    check_u32("mpeg unregister stream",
              hle_call(cpu, 0x591a4aa2u, mpeg_addr, video_stream, 0, 0), 0);
    check_u32("mpeg free AVC ES buffer",
              hle_call(cpu, 0xceb870b1u, mpeg_addr, es_buffer, 0, 0), 0);
    check_u32("mpeg delete", hle_call(cpu, 0x606a4649u, mpeg_addr, 0, 0, 0), 0);
    check_u32("mpeg finish", hle_call(cpu, 0x874624d6u, 0, 0, 0, 0), 0);
}

static void test_iso_directory(CpuState *cpu) {
    if (!getenv("PSP_ISO")) return;
    const uint32_t path_addr = 0x08818000u;
    const uint32_t dirent_addr = 0x08819000u;
    guest_string(path_addr, "disc0:/PSP_GAME");
    uint32_t dir = hle_call(cpu, 0xb29ddf9cu, path_addr, 0, 0, 0);
    if ((int32_t)dir < 0) {
        fail_u32("dopen ISO directory", dir, 0);
        return;
    }
    check_u32("dread ISO directory", hle_call(cpu, 0xe3eb004cu, dir, dirent_addr, 0, 0), 1);
    check_u32("dclose ISO directory", hle_call(cpu, 0xeb092469u, dir, 0, 0, 0), 0);
}

static void async_test_entry(CpuState *cpu) {
    const uint32_t path_addr = 0x0881a000u;
    const uint32_t result_addr = 0x0881a200u;
    const uint32_t data_addr = 0x0881a300u;
    const uint32_t ids_addr = 0x0881a400u;
    const uint32_t count_addr = 0x0881a500u;
    const uint32_t status_addr = 0x0881a600u;
    guest_string(path_addr, "ms0:/PSP/ASYNC.DAT");

    check_u32("set default async priority",
              running_hle_call(cpu, 0xb293727fu, 0xffffffffu, 0x10u, 0, 0), 0);
    uint32_t fd = running_hle_call(cpu, 0x89aa9906u, path_addr, 1, 0, 0);
    if ((int32_t)fd < 0) {
        fail_u32("async open", fd, 0);
        cpu->r[2] = 0;
        return;
    }

    check_u32("open poll pending",
              running_hle_call(cpu, 0x3251ea56u, fd, result_addr, 0, 0), 1);
    check_u32("open overlap busy",
              running_hle_call(cpu, 0xa0b5a7c2u, fd, data_addr, 5, 0), 0x80020329u);
    check_u32("open wait",
              running_hle_call(cpu, 0xe23eec33u, fd, result_addr, 0, 0), 0);
    check_u32("open async result", MEM_R32(result_addr), fd);
    check_u32("open async result high", MEM_R32(result_addr + 4), 0);
    check_u32("open result consumed",
              running_hle_call(cpu, 0xe23eec33u, fd, result_addr, 0, 0), 0x8002032au);

    uint32_t listed = running_hle_call(cpu, 0x94416130u, 1, ids_addr, 8, count_addr);
    check_u32("async helper thread count", listed, 2);
    check_u32("async helper total", MEM_R32(count_addr), 2);
    int found_helper = 0;
    for (uint32_t i = 0; i < listed; i++) {
        uint32_t uid = MEM_R32(ids_addr + i * 4);
        if (uid == sched_current_uid()) continue;
        MEM_W32(status_addr, 108);
        check_u32("refer async helper",
                  running_hle_call(cpu, 0x17c1684eu, uid, status_addr, 0, 0), 0);
        char name[32];
        guest_read_string(status_addr + 4, name, sizeof(name));
        if (!strcmp(name, "SceIoAsync")) found_helper = 1;
        check_u32("async helper waiting", MEM_R32(status_addr + 0x28), 4);
    }
    check_u32("found async helper", (uint32_t)found_helper, 1);

    cpu->r[8] = 0;
    check_u32("async seek start",
              running_hle_call(cpu, 0x71b19e77u, fd, 0, 0, 0), 0);
    check_u32("seek poll pending",
              running_hle_call(cpu, 0x3251ea56u, fd, result_addr, 0, 0), 1);
    check_u32("seek wait",
              running_hle_call(cpu, 0xe23eec33u, fd, result_addr, 0, 0), 0);
    check_u32("seek async result", MEM_R32(result_addr), 0);
    check_u32("seek async result high", MEM_R32(result_addr + 4), 0);

    for (uint32_t i = 0; i < 5; i++) MEM_W8(data_addr + i, 0xcc);
    check_u32("async read start",
              running_hle_call(cpu, 0xa0b5a7c2u, fd, data_addr, 5, 0), 0);
    check_u32("read poll pending",
              running_hle_call(cpu, 0x3251ea56u, fd, result_addr, 0, 0), 1);
    check_u32("read overlap busy",
              running_hle_call(cpu, 0xa0b5a7c2u, fd, data_addr, 5, 0), 0x80020329u);
    check_u32("read wait",
              running_hle_call(cpu, 0xe23eec33u, fd, result_addr, 0, 0), 0);
    check_u32("read async result", MEM_R32(result_addr), 5);
    check_u32("read async result high", MEM_R32(result_addr + 4), 0);
    char data[6];
    for (uint32_t i = 0; i < 5; i++) data[i] = (char)MEM_R8(data_addr + i);
    data[5] = 0;
    if (strcmp(data, "async") != 0) {
        fprintf(stderr, "FAIL: async read data: got \"%s\"\n", data);
        failures++;
    }

    check_u32("async close start",
              running_hle_call(cpu, 0xff5940b6u, fd, 0, 0, 0), 0);
    check_u32("close poll pending",
              running_hle_call(cpu, 0x3251ea56u, fd, result_addr, 0, 0), 1);
    check_u32("close wait",
              running_hle_call(cpu, 0xe23eec33u, fd, result_addr, 0, 0), 0);
    check_u32("close async result", MEM_R32(result_addr), 0);
    check_u32("poll closed descriptor",
              running_hle_call(cpu, 0x3251ea56u, fd, result_addr, 0, 0), 0x80020323u);
    check_u32("thread count after async close",
              running_hle_call(cpu, 0x94416130u, 1, ids_addr, 8, count_addr), 1);

    guest_string(path_addr, "ms0:/PSP/NO_SUCH.DAT");
    uint32_t failed_fd = running_hle_call(cpu, 0x89aa9906u, path_addr, 1, 0, 0);
    if ((int32_t)failed_fd < 0) {
        fail_u32("failed async open descriptor", failed_fd, 3);
    } else {
        check_u32("failed open poll pending",
                  running_hle_call(cpu, 0x3251ea56u, failed_fd, result_addr, 0, 0), 1);
        check_u32("failed open wait",
                  running_hle_call(cpu, 0xe23eec33u, failed_fd, result_addr, 0, 0), 0);
        check_u32("failed open result", MEM_R32(result_addr), 0x80010002u);
        check_u32("failed open result high", MEM_R32(result_addr + 4), 0xffffffffu);
        check_u32("failed open descriptor released",
                  running_hle_call(cpu, 0x3251ea56u, failed_fd, result_addr, 0, 0), 0x80020323u);
    }
    cpu->r[2] = 0;
}

static void test_async_io(CpuState *cpu, const char *root) {
    const uint32_t path_addr = 0x0881a000u;
    const uint32_t data_addr = 0x0881a100u;
    uint32_t result = write_file(cpu, path_addr, "ms0:/PSP/ASYNC.DAT", data_addr, "async");
    check_u32("create async test file", result, 0);
    if (result != 0) return;

    const uint32_t entry = 0x08804000u;
    sr_register(entry, async_test_entry);
    memset(cpu, 0, sizeof(*cpu));
    cpu->r[29] = 0x09ff0000u;
    sched_init(cpu);
    sched_run(entry, 0, 0);

    guest_string(path_addr, "ms0:/PSP/ASYNC.DAT");
    check_u32("remove async test file",
              hle_call(cpu, 0xf27a9c51u, path_addr, 0, 0, 0), 0);
    char path[512];
    snprintf(path, sizeof(path), "%s\\ms0\\PSP", root);
    _rmdir(path);
    snprintf(path, sizeof(path), "%s\\ms0", root);
    _rmdir(path);
    _rmdir(root);
}

static void test_offline_network(CpuState *cpu) {
    const uint32_t data_addr = 0x0881b000u;
    const uint32_t text_addr = 0x0881b100u;
    static const uint8_t expected_mac[6] = { 0x00, 0x13, 0x37, 0xac, 0xc5, 0x10 };
    static const uint8_t expected_psid[16] = {
        0x00, 0x13, 0x37, 0xac, 0xc5, 0x10, 0x93, 0xb0,
        0xcc, 0x6e, 0xd1, 0x32, 0x27, 0x85, 0x0f, 0x9d
    };

    check_u32("WLAN switch off",
              hle_call(cpu, 0xd7763699u, 0, 0, 0, 0), 0);
    check_u32("WLAN device off",
              hle_call(cpu, 0x93440b11u, 0, 0, 0, 0), 0);
    check_u32("get WLAN MAC",
              hle_call(cpu, 0x0c622081u, data_addr, 0, 0, 0), 0);
    check_guest_bytes("WLAN MAC", data_addr, expected_mac, sizeof(expected_mac));
    check_u32("get OpenPSID",
              hle_call(cpu, 0xc69bebceu, data_addr, 0, 0, 0), 0);
    check_guest_bytes("OpenPSID", data_addr, expected_psid, sizeof(expected_psid));

    check_u32("network init",
              hle_call(cpu, 0x39af39a6u, 0, 0, 0, 0), 0);
    check_u32("inet init",
              hle_call(cpu, 0x17943399u, 0, 0, 0, 0), 0);
    check_u32("offline inet socket",
              hle_call(cpu, 0x8b7b220fu, 2, 1, 0, 0), UINT32_MAX);
    check_u32("offline inet errno",
              hle_call(cpu, 0xfbabe411u, 0, 0, 0, 0), 115);

    guest_string(text_addr, "127.0.0.1");
    check_u32("inet_addr",
              hle_call(cpu, 0xb75d5b0au, text_addr, 0, 0, 0), 0x0100007fu);
    MEM_W32(data_addr, 0);
    check_u32("inet_aton",
              hle_call(cpu, 0x1bdf5d13u, text_addr, data_addr, 0, 0), 1);
    check_u32("inet_aton output", MEM_R32(data_addr), 0x0100007fu);

    check_u32("resolver init",
              hle_call(cpu, 0xf3370e61u, 0, 0, 0, 0), 0);
    check_u32("resolver create",
              hle_call(cpu, 0x244172afu, data_addr, data_addr + 16, 256, 0), 0);
    check_u32("resolver id", MEM_R32(data_addr), 1);
    check_u32("resolver offline",
              hle_call(cpu, 0x224c5f44u, 1, text_addr, data_addr, 1), 0x80410402u);

    check_u32("apctl init",
              hle_call(cpu, 0xe2f91f9bu, 0, 0, 0, 0), 0);
    check_u32("apctl WLAN off",
              hle_call(cpu, 0x2befdf23u, 0, data_addr, 0, 0), 0x80410a06u);
    check_u32("adhocctl init",
              hle_call(cpu, 0xe26f226eu, 0, 0, 0, 0), 0);
    check_u32("adhocctl WLAN off",
              hle_call(cpu, 0x0ad043edu, text_addr, 0, 0, 0), 0x80410b03u);
    check_u32("adhocctl disconnected",
              hle_call(cpu, 0xded9d28eu, data_addr, 0, 0, 0), 0x80410b09u);
    check_u32("adhoc socket disconnected",
              hle_call(cpu, 0x6f92741bu, data_addr, 0, 0, 0), 0x8041070bu);
    check_u32("local MAC unavailable",
              hle_call(cpu, 0x0bf0a3aeu, data_addr, 0, 0, 0), 0x80410180u);

    static const uint32_t imported_nids[] = {
        0x224c5f44u, 0x244172afu, 0x6138194au, 0x94523e09u, 0xf3370e61u,
        0x05038fc7u, 0x162e6fd5u, 0x17943399u, 0x1a33f9aeu, 0x1bdf5d13u,
        0x2fe71fe7u, 0x410b34aau, 0x4a114c7cu, 0x4cfe4e56u, 0x5be8d595u,
        0x774e36f4u, 0x7aa671bcu, 0x8b7b220fu, 0x8d7284eau, 0xa9ed66b9u,
        0xb75d5b0au, 0xc91142e4u, 0xcda85c99u, 0xd10a1a7au, 0xdb094e1bu,
        0xfaabb1ddu, 0xfbabe411u, 0x24fe91a1u, 0x2befdf23u, 0x5963991bu,
        0x8abadd51u, 0xb3edd0ecu, 0xe2f91f9bu, 0x191cdeffu, 0x957ecbe2u,
        0x87797bddu, 0xab1abe07u, 0xd1c8945eu, 0xe4d21302u, 0xf9d8eb63u,
        0xc69bebceu, 0x0c622081u, 0xd7763699u, 0x2a2a1e07u, 0x7945ecdau,
        0x20b317a0u, 0x34401d65u, 0x6402490bu, 0x9d689e13u, 0xe26f226eu,
        0x0ad043edu, 0xded9d28eu, 0xa62c6f57u, 0xe1d621d7u, 0x157e6225u,
        0x4da4c788u, 0x6f92741bu, 0x7f27bb5eu, 0x877f6d66u, 0x8bea2b3eu,
        0x9ac2eeacu, 0x9df81198u, 0xabed3790u, 0xb9685118u, 0xc7c1fc57u,
        0xdfe53e03u, 0xe08bdac1u, 0xfc6fc07bu, 0x281928a9u, 0x39af39a6u,
        0x0bf0a3aeu,
    };
    for (size_t i = 0; i < sizeof(imported_nids) / sizeof(imported_nids[0]); i++)
        (void)hle_call(cpu, imported_nids[i], 0, 0, 0, 0);
}

int main(void) {
    char root[128], local_app_data[128];
    snprintf(root, sizeof(root), "kzl_hle_test_fs_%lu", (unsigned long)GetCurrentProcessId());
    snprintf(local_app_data, sizeof(local_app_data), "kzl_hle_test_localappdata_%lu",
             (unsigned long)GetCurrentProcessId());
    _putenv_s("LOCALAPPDATA", local_app_data);
    _putenv_s("SR_FSDIR", "");

    sr_mem_init();
    CpuState cpu;
    test_default_vfs_root(&cpu, local_app_data);
    _putenv_s("SR_FSDIR", root);
    test_threadman(&cpu);
    test_time(&cpu);
    test_io(&cpu, root);
    test_iso_directory(&cpu);
    test_mpeg_eof(&cpu);
    test_async_io(&cpu, root);
    test_offline_network(&cpu);

    if (failures) {
        fprintf(stderr, "HLE smoke tests: %d failure(s)\n", failures);
        return 1;
    }
    printf("HLE smoke tests passed\n");
    return 0;
}
