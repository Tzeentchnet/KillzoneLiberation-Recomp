#include "recomp.h"
#include "ge_shared.h"

#include <direct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <windows.h>

static int failures;
static uint32_t backend_dirty_addr;
static uint32_t backend_dirty_bytes;
static uint32_t backend_read_addr;
static uint32_t backend_read_bytes;
static uint32_t backend_write_addr;
static uint32_t backend_write_bytes;
static GeVtx backend_triangle[3];
static int backend_triangle_count;
static int backend_triangle_perspective;
static int backend_line_count;
static int backend_point_count;

static int file_contains(const char *path, const char *needle) {
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    char line[1024];
    int found = 0;
    while (fgets(line, sizeof(line), file)) {
        if (strstr(line, needle)) {
            found = 1;
            break;
        }
    }
    fclose(file);
    return found;
}

static void fail_u32(const char *what, uint32_t got, uint32_t expected) {
    fprintf(stderr, "FAIL: %s: got 0x%08x, expected 0x%08x\n", what, got, expected);
    failures++;
}

static void check_u32(const char *what, uint32_t got, uint32_t expected) {
    if (got != expected) fail_u32(what, got, expected);
}

static void check_float(const char *what, float got, float expected) {
    if (got < expected - 0.000001f || got > expected + 0.000001f) {
        fprintf(stderr, "FAIL: %s: got %.9g, expected %.9g\n", what, got, expected);
        failures++;
    }
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

static void test_backend_dirty(uint32_t addr, uint32_t bytes) {
    backend_dirty_addr = addr;
    backend_dirty_bytes = bytes;
}

static void test_backend_read(uint32_t addr, uint32_t bytes) {
    backend_read_addr = addr;
    backend_read_bytes = bytes;
}

static void test_backend_write(uint32_t addr, uint32_t bytes) {
    backend_write_addr = addr;
    backend_write_bytes = bytes;
}

static int test_backend_triangle(const GeVtx *a, const GeVtx *b,
                                 const GeVtx *c, int perspective) {
    backend_triangle[0] = *a;
    backend_triangle[1] = *b;
    backend_triangle[2] = *c;
    backend_triangle_count++;
    backend_triangle_perspective = perspective;
    return 1;
}

static int test_backend_line(
    const GeVtx *a, const GeVtx *b, int perspective) {
    (void)a;
    (void)b;
    (void)perspective;
    backend_line_count++;
    return 1;
}

static int test_backend_point(const GeVtx *a, int perspective) {
    (void)a;
    (void)perspective;
    backend_point_count++;
    return 1;
}

static void test_ge_state_dump(void) {
    char path[128];
    snprintf(
        path, sizeof(path), "kzl_ge_state_test_%lu.txt",
        (unsigned long)GetCurrentProcessId());
    ge_debug_set_list(7, 0x08123400u);
    ge_execute_op(0x9c001234u, 0x08123420u);
    ge_execute_op(0x04030000u, 0x08123440u);
    if (!ge_debug_dump(path)) {
        fprintf(stderr, "FAIL: GE state dump could not be written\n");
        failures++;
        return;
    }
    if (!file_contains(path, "KZL_GE_STATE_V1") ||
        !file_contains(path, "list_id=7") ||
        !file_contains(path, "draw_pc=0x08123440") ||
        !file_contains(path, "framebuffer=0x00001234") ||
        !file_contains(path, "[raw-state]")) {
        fprintf(stderr, "FAIL: GE state dump is missing required context\n");
        failures++;
    }
    remove(path);
}

static void test_ge_fragment_state(void) {
    check_u32(
        "color test masked equal",
        (uint32_t)ge_color_test_pass(
            2, 0x00332211u, 0x00ffff00u, 0x99, 0x22, 0x33),
        1);
    check_u32(
        "color test masked not equal",
        (uint32_t)ge_color_test_pass(
            3, 0x00332211u, 0x00ffffffu, 0x99, 0x22, 0x33),
        1);
    check_u32(
        "stencil reference less",
        (uint32_t)ge_stencil_test_pass(
            4u | (0x20u << 8) | (0xf0u << 16), 0x3fu),
        1);
    check_u32(
        "stencil masked equal",
        (uint32_t)ge_stencil_test_pass(
            2u | (0x2fu << 8) | (0xf0u << 16), 0x20u),
        1);
    check_u32(
        "stencil 8888 increment",
        ge_stencil_apply(4, 3, 0x7f, 0), 0x80);
    check_u32(
        "stencil 8888 increment saturation",
        ge_stencil_apply(4, 3, 0xff, 0), 0xff);
    check_u32(
        "stencil 8888 invert",
        ge_stencil_apply(3, 3, 0x33, 0), 0xcc);
    check_u32(
        "stencil 4444 increment",
        ge_stencil_apply(4, 2, 0xe0, 0), 0xf0);
    check_u32(
        "stencil 5551 decrement",
        ge_stencil_apply(5, 1, 0xff, 0), 0);
    check_u32(
        "stencil replacement",
        ge_stencil_apply(2, 3, 0x55, 0xa7), 0xa7);
    GeRgb blended = ge_blend_rgb(
        2u | (3u << 4), 0, 0,
        0x803296c8u, 0x55145064u);
    check_u32("source-alpha blend red", (uint32_t)blended.r, 150);
    check_u32("source-alpha blend green", (uint32_t)blended.g, 115);
    check_u32("source-alpha blend blue", (uint32_t)blended.b, 35);
    blended = ge_blend_rgb(
        3u << 8, 0, 0, 0xff30c080u, 0xffa05040u);
    check_u32("minimum blend red", (uint32_t)blended.r, 64);
    check_u32("minimum blend green", (uint32_t)blended.g, 80);
    check_u32("minimum blend blue", (uint32_t)blended.b, 48);
    blended = ge_blend_rgb(
        5u << 8, 0, 0, 0xff30c080u, 0xffa05040u);
    check_u32("absolute-difference red", (uint32_t)blended.r, 64);
    check_u32("absolute-difference green", (uint32_t)blended.g, 112);
    check_u32("absolute-difference blue", (uint32_t)blended.b, 112);
    blended = ge_blend_rgb(
        7u | (10u << 4), 0, 0, 0xc8000064u, 0);
    check_u32("signed doubled-alpha blend", (uint32_t)blended.r, (uint32_t)-57);
    check_u32(
        "logic xor",
        ge_logic_apply(6, 0xaa0f3355u, 0x77f00ff0u),
        0xaaff3ca5u);
    check_u32(
        "logic nor",
        ge_logic_apply(8, 0xaa0f3355u, 0x77f00ff0u),
        0xaa00c00au);
    check_u32(
        "logic noop",
        ge_logic_apply(5, 0xaa0f3355u, 0x77f00ff0u),
        0xaaf00ff0u);
    check_u32(
        "logic set",
        ge_logic_apply(15, 0xaa0f3355u, 0x77f00ff0u),
        0xaaffffffu);

    ge_execute_op(0x27000001u, 0);
    ge_execute_op(0xd8000003u, 0);
    ge_execute_op(0xd9001122u, 0);
    ge_execute_op(0xda00f0f0u, 0);
    ge_execute_op(0x24000001u, 0);
    ge_execute_op(0xdcaa5506u, 0);
    ge_execute_op(0xdd030201u, 0);
    ge_execute_op(0x28000001u, 0);
    ge_execute_op(0xe6000006u, 0);
    GeState *state = ge_state_ptr();
    check_u32(
        "color test enable", (uint32_t)state->color_test_enable, 1);
    check_u32("color test function", state->color_test, 3);
    check_u32("color test reference", state->color_ref, 0x001122u);
    check_u32("color test mask", state->color_test_mask, 0x00f0f0u);
    check_u32(
        "stencil test enable", (uint32_t)state->stencil_test_enable, 1);
    check_u32("stencil test state", state->stencil_test, 0xaa5506u);
    check_u32("stencil operation state", state->stencil_op, 0x030201u);
    check_u32(
        "logic operation enable", (uint32_t)state->logic_op_enable, 1);
    check_u32("logic operation state", state->logic_op, 6);
    ge_execute_op(0x27000000u, 0);
    ge_execute_op(0x24000000u, 0);
    ge_execute_op(0x28000000u, 0);
}

static void draw_test_sprite(
    uint32_t vertex_addr, uint32_t color, uint16_t depth) {
    for (uint32_t i = 0; i < 2; i++) {
        uint32_t address = vertex_addr + i * 12u;
        MEM_W32(address, color);
        MEM_W16(address + 4, (uint16_t)(i * 2u));
        MEM_W16(address + 6, (uint16_t)(i * 2u));
        MEM_W16(address + 8, depth);
        MEM_W16(address + 10, 0);
    }
    ge_execute_op(0x10080000u, 0);
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x12000000u | (7u << 2) | (2u << 7) | (1u << 23), 0);
    ge_execute_op(0x04060002u, 0);
}

static void test_ge_fragment_writes(void) {
    const uint32_t framebuffer = 0x04018000u;
    const uint32_t vertex_addr = 0x08818000u;
    GeState *state = ge_state_ptr();
    GeState saved = *state;
    memset(state, 0, sizeof(*state));
    state->fbp = framebuffer & 0x001fffffu;
    state->fbw = 4;
    state->fbfmt = 3;
    state->scis_x2 = 3;
    state->scis_y2 = 3;
    state->minz = 0;
    state->maxz = 65535;

    MEM_W32(framebuffer, 0x55000000u);
    draw_test_sprite(vertex_addr, 0xaa030201u, 50);
    check_u32(
        "normal draw preserves stencil alpha",
        MEM_R32(framebuffer), 0x55030201u);

    state->stencil_test_enable = 1;
    state->stencil_test = 1u | (0x44u << 8) | (0xffu << 16);
    state->stencil_op = 2u << 16;
    draw_test_sprite(vertex_addr, 0xaa060504u, 50);
    check_u32(
        "stencil depth-pass replace",
        MEM_R32(framebuffer), 0x44060504u);

    state->ztest_enable = 1;
    state->ztest = 4;
    state->stencil_op = 3u << 8;
    ge_zbuf_ptr()[0] = 10;
    MEM_W32(framebuffer, 0x33090807u);
    draw_test_sprite(vertex_addr, 0xaa0c0b0au, 50);
    check_u32(
        "stencil depth-fail invert",
        MEM_R32(framebuffer), 0xcc090807u);
    check_u32("depth fail preserves depth", ge_zbuf_ptr()[0], 10);

    state->ztest_enable = 0;
    state->stencil_test = 0;
    state->stencil_op = 1;
    MEM_W32(framebuffer, 0x77090807u);
    draw_test_sprite(vertex_addr, 0xaa0c0b0au, 50);
    check_u32(
        "stencil test-fail zero",
        MEM_R32(framebuffer), 0x00090807u);

    state->color_test_enable = 1;
    state->color_test = 0;
    MEM_W32(framebuffer, 0x88090807u);
    draw_test_sprite(vertex_addr, 0xaa0c0b0au, 50);
    check_u32(
        "color test precedes stencil",
        MEM_R32(framebuffer), 0x88090807u);

    state->color_test_enable = 0;
    state->stencil_test = 1u | (0x3cu << 8) | (0xf0u << 16);
    state->stencil_op = 2u << 16;
    state->mask_alpha = 0x0f;
    MEM_W32(framebuffer, 0xa5000000u);
    draw_test_sprite(vertex_addr, 0xaa060504u, 50);
    check_u32(
        "partial stencil write mask",
        MEM_R32(framebuffer), 0x35060504u);
    state->mask_alpha = 0;
    MEM_W32(framebuffer, 0xa5000000u);
    draw_test_sprite(vertex_addr, 0xaa060504u, 50);
    check_u32(
        "stencil replacement uses unmasked reference",
        MEM_R32(framebuffer), 0x3c060504u);

    memset(state, 0, sizeof(*state));
    state->fbp = framebuffer & 0x001fffffu;
    state->fbw = 4;
    state->fbfmt = 3;
    state->scis_x2 = 3;
    state->scis_y2 = 3;
    state->minz = 0;
    state->maxz = 65535;
    state->blend_enable = 1;
    state->blend_mode = 2u | (3u << 4);
    MEM_W32(framebuffer, 0x55145064u);
    draw_test_sprite(vertex_addr, 0x803296c8u, 50);
    check_u32(
        "exact source-alpha raster blend",
        MEM_R32(framebuffer), 0x55237396u);

    state->blend_enable = 0;
    state->logic_op_enable = 1;
    state->logic_op = 6;
    state->dither_enable = 1;
    state->dith[0][0] = 1;
    MEM_W32(framebuffer, 0x55f0f0f0u);
    draw_test_sprite(vertex_addr, 0x800f0f0fu, 50);
    check_u32(
        "logic follows dither and preserves stencil",
        MEM_R32(framebuffer), 0x55e0e0e0u);

    memset(state, 0, sizeof(*state));
    state->fbp = framebuffer & 0x001fffffu;
    state->fbw = 4;
    state->fbfmt = 3;
    state->scis_x2 = 3;
    state->scis_y2 = 3;
    state->clear = 1;
    state->clear_mode = 0x300;
    state->dither_enable = 1;
    state->dith[0][0] = 7;
    MEM_W32(framebuffer, 0);
    draw_test_sprite(vertex_addr, 0x80030201u, 50);
    check_u32(
        "clear applies dither before packing",
        MEM_R32(framebuffer), 0x800a0908u);

    *state = saved;
}

static void test_ge_backend_interface(void) {
    GeBackend backend;
    memset(&backend, 0, sizeof(backend));
    backend.name = "test";
    backend.vram_dirty = test_backend_dirty;
    backend.vram_read = test_backend_read;
    backend.vram_write = test_backend_write;

    if (ge_backend_get() != NULL) {
        fprintf(stderr, "FAIL: GE backend was registered before the interface test\n");
        failures++;
    }

    ge_set_backend(&backend);
    if (ge_backend_get() != &backend) {
        fprintf(stderr, "FAIL: GE backend registration did not round-trip\n");
        failures++;
    }
    sr_gpu_vram_dirty(0x04012340u, 0x800u);
    check_u32("GE backend dirty address", backend_dirty_addr, 0x04012340u);
    check_u32("GE backend dirty size", backend_dirty_bytes, 0x800u);

    MEM_W32(0x04012340u, 0x78563412u);
    sr_gpu_vram_watch_reads(1);
    check_u32("GE watched VRAM value",
              MEM_R32(0x04012340u), 0x78563412u);
    sr_gpu_vram_watch_reads(0);
    check_u32("GE backend read address", backend_read_addr, 0x04012340u);
    check_u32("GE backend read size", backend_read_bytes, 4);

    sr_gpu_vram_watch_writes(1);
    MEM_W16(0x04012344u, 0x55aau);
    sr_gpu_vram_watch_writes(0);
    check_u32("GE watched VRAM store",
              MEM_R16(0x04012344u), 0x55aau);
    check_u32("GE backend pre-write address",
              backend_write_addr, 0x04012344u);
    check_u32("GE backend pre-write size", backend_write_bytes, 2);
    check_u32("GE backend watched dirty address",
              backend_dirty_addr, 0x04012344u);
    check_u32("GE backend watched dirty size", backend_dirty_bytes, 2);

    backend_dirty_addr = 0;
    backend_dirty_bytes = 0;
    ge_execute_op(0xb2001000u, 0);
    ge_execute_op(0xb3040008u, 0);
    ge_execute_op(0xb4002000u, 0);
    ge_execute_op(0xb5040008u, 0);
    ge_execute_op(0xeb000401u, 0);
    ge_execute_op(0xec000402u, 0);
    ge_execute_op(0xee000402u, 0);
    ge_execute_op(0xea000000u, 0);
    check_u32("GE block-transfer dirty address",
              backend_dirty_addr, 0x04002014u);
    check_u32("GE block-transfer dirty size", backend_dirty_bytes, 22);

    ge_set_backend(NULL);
    check_u32("GE cleared VRAM read watch",
              (uint32_t)g_sr_gpu_vram_read_watch, 0);
    check_u32("GE cleared VRAM write watch",
              (uint32_t)g_sr_gpu_vram_write_watch, 0);
    if (ge_backend_get() != NULL) {
        fprintf(stderr, "FAIL: GE software fallback did not clear the backend\n");
        failures++;
    }
}

static uint32_t align_u32(uint32_t value, uint32_t alignment) {
    return (value + alignment - 1) & ~(alignment - 1);
}

static void guest_float(uint32_t addr, float value) {
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    MEM_W32(addr, bits);
}

static uint32_t float24_data(float value) {
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return bits >> 8;
}

static uint32_t write_test_vertex(uint32_t addr, int tc_format, int color_format,
                                  int position_format, int vertex_index) {
    uint32_t tc_size = 1u << (tc_format - 1);
    uint32_t color_size = color_format == 7 ? 4u : 2u;
    uint32_t position_size = 1u << (position_format - 1);
    uint32_t max_alignment = tc_size;
    if (color_size > max_alignment) max_alignment = color_size;
    if (position_size > max_alignment) max_alignment = position_size;

    uint32_t offset = 0;
    offset = align_u32(offset, tc_size);
    uint32_t tc_offset = offset;
    offset += tc_size * 2;
    offset = align_u32(offset, color_size);
    uint32_t color_offset = offset;
    offset += color_size;
    offset = align_u32(offset, position_size);
    uint32_t position_offset = offset;
    offset += position_size * 3;
    uint32_t stride = align_u32(offset, max_alignment);

    uint32_t u = 10u + (uint32_t)vertex_index;
    uint32_t v = 20u + (uint32_t)vertex_index;
    if (tc_format == 1) {
        MEM_W8(addr + tc_offset, (uint8_t)u);
        MEM_W8(addr + tc_offset + 1, (uint8_t)v);
    } else if (tc_format == 2) {
        MEM_W16(addr + tc_offset, (uint16_t)u);
        MEM_W16(addr + tc_offset + 2, (uint16_t)v);
    } else {
        guest_float(addr + tc_offset, (float)u);
        guest_float(addr + tc_offset + 4, (float)v);
    }

    if (color_format == 4) MEM_W16(addr + color_offset, 0x001fu);
    else if (color_format == 5) MEM_W16(addr + color_offset, 0x801fu);
    else if (color_format == 6) MEM_W16(addr + color_offset, 0xf00fu);
    else MEM_W32(addr + color_offset, 0xff0000ffu);

    int x = 30 + vertex_index;
    int y = 40 + vertex_index;
    int z = 50 + vertex_index;
    if (position_format == 1) {
        MEM_W8(addr + position_offset, (uint8_t)x);
        MEM_W8(addr + position_offset + 1, (uint8_t)y);
        MEM_W8(addr + position_offset + 2, (uint8_t)z);
    } else if (position_format == 2) {
        MEM_W16(addr + position_offset, (uint16_t)x);
        MEM_W16(addr + position_offset + 2, (uint16_t)y);
        MEM_W16(addr + position_offset + 4, (uint16_t)z);
    } else {
        guest_float(addr + position_offset, (float)x);
        guest_float(addr + position_offset + 4, (float)y);
        guest_float(addr + position_offset + 8, (float)z);
    }
    return stride;
}

static void test_ge_decoded_vertex_boundary(void) {
    static const struct {
        int tc_format;
        int color_format;
        int position_format;
        int index_format;
    } cases[] = {
        {1, 4, 1, 0},
        {2, 5, 2, 1},
        {3, 6, 3, 2},
        {3, 7, 3, 3},
    };
    GeBackend backend;
    memset(&backend, 0, sizeof(backend));
    backend.name = "decoded-vertex-test";
    backend.tri = test_backend_triangle;
    ge_set_backend(&backend);

    for (uint32_t case_index = 0;
         case_index < sizeof(cases) / sizeof(cases[0]); case_index++) {
        const uint32_t vertex_addr = 0x08820000u + case_index * 0x100u;
        const uint32_t index_addr = 0x08821000u + case_index * 0x10u;
        uint32_t stride = 0;
        for (int vertex_index = 0; vertex_index < 3; vertex_index++) {
            uint32_t wrote = write_test_vertex(
                vertex_addr + (uint32_t)vertex_index * stride,
                cases[case_index].tc_format,
                cases[case_index].color_format,
                cases[case_index].position_format,
                vertex_index);
            if (!stride) stride = wrote;
        }

        if (cases[case_index].index_format == 1) {
            MEM_W8(index_addr, 2);
            MEM_W8(index_addr + 1, 0);
            MEM_W8(index_addr + 2, 1);
        } else if (cases[case_index].index_format == 2) {
            MEM_W16(index_addr, 2);
            MEM_W16(index_addr + 2, 0);
            MEM_W16(index_addr + 4, 1);
        } else if (cases[case_index].index_format == 3) {
            MEM_W32(index_addr, 2);
            MEM_W32(index_addr + 4, 0);
            MEM_W32(index_addr + 8, 1);
        }

        uint32_t vtype =
            (uint32_t)cases[case_index].tc_format |
            ((uint32_t)cases[case_index].color_format << 2) |
            ((uint32_t)cases[case_index].position_format << 7) |
            ((uint32_t)cases[case_index].index_format << 11) |
            (1u << 23);
        backend_triangle_count = 0;
        ge_execute_op(0x10080000u, 0);
        ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
        ge_execute_op(0x02000000u | (index_addr & 0x00ffffffu), 0);
        ge_execute_op(0x12000000u | vtype, 0);
        ge_execute_op(0x04030003u, 0);

        check_u32("decoded triangle callback count", backend_triangle_count, 1);
        check_u32("decoded through-mode perspective", backend_triangle_perspective, 0);
        int first_vertex = cases[case_index].index_format ? 2 : 0;
        check_float("decoded position x", backend_triangle[0].x,
                    (float)(30 + first_vertex));
        check_float("decoded position y", backend_triangle[0].y,
                    (float)(40 + first_vertex));
        check_float("decoded position z", backend_triangle[0].z,
                    (float)(50 + first_vertex));
        check_float("decoded texture u", backend_triangle[0].u,
                    (float)(10 + first_vertex));
        check_float("decoded texture v", backend_triangle[0].v,
                    (float)(20 + first_vertex));
        check_u32("decoded color red", (uint32_t)backend_triangle[0].r, 255);
        check_u32("decoded color green", (uint32_t)backend_triangle[0].g, 0);
        check_u32("decoded color blue", (uint32_t)backend_triangle[0].b, 0);
        check_u32("decoded color alpha", (uint32_t)backend_triangle[0].a, 255);
    }
    ge_set_backend(NULL);
}

static void write_morph_target(
    uint32_t address, int vertex, int target) {
    float offset = target ? 20.0f : 0.0f;
    guest_float(address, (float)(vertex * 2) + offset);
    guest_float(address + 4, (float)(vertex * 3 + 10) + offset);
    uint32_t color = target
        ? 0x806400c8u
        : 0xffc86400u;
    MEM_W32(address + 8, color);
    guest_float(address + 12, (float)(vertex * 4 + 10) + offset);
    guest_float(address + 16, (float)(vertex * 5 + 20) + offset);
    guest_float(address + 20, (float)(vertex * 6 + 30) + offset);
}

static void test_ge_morph_vertices(void) {
    const uint32_t vertex_addr = 0x08822000u;
    const uint32_t one_size = 24;
    const uint32_t logical_stride = one_size * 2;
    GeState *state = ge_state_ptr();
    GeState saved = *state;
    memset(state, 0, sizeof(*state));

    for (int vertex = 0; vertex < 3; vertex++) {
        uint32_t address =
            vertex_addr + (uint32_t)vertex * logical_stride;
        write_morph_target(address, vertex, 0);
        write_morph_target(address + one_size, vertex, 1);
    }

    GeBackend backend;
    memset(&backend, 0, sizeof(backend));
    backend.name = "morph-test";
    backend.tri = test_backend_triangle;
    ge_set_backend(&backend);
    backend_triangle_count = 0;

    ge_execute_op(0x10080000u, 0);
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(
        0x12000000u | 3u | (7u << 2) | (3u << 7) |
        (1u << 18) | (1u << 23),
        0);
    ge_execute_op(0x2c000000u | float24_data(0.25f), 0);
    ge_execute_op(0x2d000000u | float24_data(0.75f), 0);
    ge_execute_op(0x04030003u, 0);

    check_u32("morph triangle callback count", backend_triangle_count, 1);
    check_float("morph position x", backend_triangle[0].x, 25.0f);
    check_float("morph position y", backend_triangle[0].y, 35.0f);
    check_float("morph position z", backend_triangle[0].z, 45.0f);
    check_float("morph texture u", backend_triangle[0].u, 15.0f);
    check_float("morph texture v", backend_triangle[0].v, 25.0f);
    check_u32("morph color red", (uint32_t)backend_triangle[0].r, 150);
    check_u32("morph color green", (uint32_t)backend_triangle[0].g, 25);
    check_u32("morph color blue", (uint32_t)backend_triangle[0].b, 125);
    check_u32("morph color alpha", (uint32_t)backend_triangle[0].a, 159);
    check_u32(
        "morph logical vertex stride", state->vaddr,
        vertex_addr + 3u * logical_stride);
    check_float("morph weight command 0", state->morph_weight[0], 0.25f);
    check_float("morph weight command 1", state->morph_weight[1], 0.75f);

    ge_set_backend(NULL);
    *state = saved;
}

static void set_identity_transform(GeState *state) {
    memset(state->world, 0, sizeof(state->world));
    memset(state->view, 0, sizeof(state->view));
    memset(state->proj, 0, sizeof(state->proj));
    state->world[0] = state->world[4] = state->world[8] = 1.0f;
    state->view[0] = state->view[4] = state->view[8] = 1.0f;
    state->proj[0] = state->proj[5] = state->proj[10] =
        state->proj[15] = 1.0f;
    state->viewport_raw[0] = float24_data(1.0f);
    state->viewport_raw[1] = float24_data(1.0f);
    state->viewport_raw[2] = float24_data(0.0f);
    state->viewport_raw[3] = float24_data(100.0f);
    state->viewport_raw[4] = float24_data(100.0f);
    state->viewport_raw[5] = float24_data(100.0f);
    state->scis_x2 = 511;
    state->scis_y2 = 271;
    state->maxz = 65535;
    state->tex_scale_u = 1.0f;
    state->tex_scale_v = 1.0f;
}

static void write_morph_skin_vertex(
    uint32_t address, float x, float y) {
    guest_float(address, 1.0f);
    guest_float(address + 4, 0.0f);
    guest_float(address + 8, x);
    guest_float(address + 12, y);
    guest_float(address + 16, 0.0f);
    guest_float(address + 20, 0.0f);
    guest_float(address + 24, 1.0f);
    guest_float(address + 28, x + 4.0f);
    guest_float(address + 32, y);
    guest_float(address + 36, 0.0f);
}

static void write_skin_normal_vertex(
    uint32_t address, float x, float y) {
    guest_float(address, 0.25f);
    guest_float(address + 4, 0.75f);
    guest_float(address + 8, 1.0f);
    guest_float(address + 12, 0.0f);
    guest_float(address + 16, 0.0f);
    guest_float(address + 20, x);
    guest_float(address + 24, y);
    guest_float(address + 28, 0.0f);
}

static void test_ge_skinning_normal(void) {
    const uint32_t vertex_addr = 0x08822000u;
    GeState *state = ge_state_ptr();
    GeState saved = *state;
    memset(state, 0, sizeof(*state));
    set_identity_transform(state);
    state->bone[0] = state->bone[4] = state->bone[8] = 1.0f;
    state->bone[12 + 1] = 1.0f;
    state->bone[12 + 3] = -1.0f;
    state->bone[12 + 8] = 1.0f;
    state->tex_map_mode = 2;
    state->tex_w = state->tex_h = 1;
    state->tex_shade_ls = 1u << 8;
    state->light_pos[0][0] = 1.0f;
    state->light_pos[1][1] = 1.0f;
    write_skin_normal_vertex(vertex_addr, 0.0f, 0.0f);
    write_skin_normal_vertex(vertex_addr + 32u, 1.0f, 0.0f);
    write_skin_normal_vertex(vertex_addr + 64u, 0.0f, 1.0f);

    GeBackend backend;
    memset(&backend, 0, sizeof(backend));
    backend.name = "skin-normal-test";
    backend.tri = test_backend_triangle;
    ge_set_backend(&backend);
    backend_triangle_count = 0;
    ge_execute_op(0x10080000u, 0);
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(
        0x12000000u | (3u << 5) | (3u << 7) |
        (3u << 9) | (1u << 14),
        0);
    ge_execute_op(0x04030003u, 0);

    check_u32("skin normal triangle count", backend_triangle_count, 1);
    check_float(
        "skin normal environment u", backend_triangle[0].u,
        0.658113883f);
    check_float(
        "skin normal environment v", backend_triangle[0].v,
        0.974341631f);
    check_u32(
        "skin normal vertex advance", state->vaddr,
        vertex_addr + 3u * 32u);

    ge_set_backend(NULL);
    *state = saved;
}

static void test_ge_morph_skinning(void) {
    const uint32_t vertex_addr = 0x08823000u;
    const uint32_t logical_stride = 40;
    GeState *state = ge_state_ptr();
    GeState saved = *state;
    memset(state, 0, sizeof(*state));
    set_identity_transform(state);
    for (int bone = 0; bone < 2; bone++) {
        float *matrix = &state->bone[bone * 12];
        matrix[0] = matrix[4] = matrix[8] = 1.0f;
    }
    state->bone[9] = 10.0f;
    state->bone[12] = 2.0f;
    state->bone[12 + 10] = 20.0f;
    state->morph_weight[0] = 0.25f;
    state->morph_weight[1] = 0.75f;
    write_morph_skin_vertex(vertex_addr, 0.0f, 0.0f);
    write_morph_skin_vertex(
        vertex_addr + logical_stride, 1.0f, 0.0f);
    write_morph_skin_vertex(
        vertex_addr + logical_stride * 2u, 0.0f, 1.0f);

    GeBackend backend;
    memset(&backend, 0, sizeof(backend));
    backend.name = "morph-skin-test";
    backend.tri = test_backend_triangle;
    ge_set_backend(&backend);
    backend_triangle_count = 0;
    ge_execute_op(0x10080000u, 0);
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(
        0x12000000u | (3u << 7) | (3u << 9) |
        (1u << 14) | (1u << 18),
        0);
    ge_execute_op(0x04030003u, 0);

    check_u32("morph skin triangle count", backend_triangle_count, 1);
    check_u32("morph skin perspective", backend_triangle_perspective, 1);
    check_float("morph skin position x", backend_triangle[0].x, 107.75f);
    check_float("morph skin position y", backend_triangle[0].y, 115.0f);
    check_float("morph skin depth", backend_triangle[0].z, 100.0f);
    check_u32(
        "morph skin logical stride", state->vaddr,
        vertex_addr + logical_stride * 3u);

    ge_set_backend(NULL);
    *state = saved;
}

static void write_patch_control_grid(
    uint32_t address, int width, int height) {
    for (int v = 0; v < height; v++) {
        for (int u = 0; u < width; u++) {
            uint32_t point =
                address + (uint32_t)(v * width + u) * 12u;
            guest_float(point, 20.0f + (float)u * 10.0f);
            guest_float(point + 4, 30.0f + (float)v * 10.0f);
            guest_float(point + 8, 100.0f);
        }
    }
}

static void write_patch_attribute_grid(uint32_t address) {
    for (int v = 0; v < 4; v++) {
        for (int u = 0; u < 4; u++) {
            uint32_t point =
                address + (uint32_t)(v * 4 + u) * 24u;
            guest_float(point, 100.0f + (float)u * 30.0f);
            guest_float(point + 4, 200.0f + (float)v * 20.0f);
            MEM_W32(
                point + 8,
                (uint32_t)(u * 60) |
                ((uint32_t)(v * 50) << 8) |
                (20u << 16) | (255u << 24));
            guest_float(point + 12, 20.0f + (float)u * 10.0f);
            guest_float(point + 16, 30.0f + (float)v * 10.0f);
            guest_float(point + 20, 100.0f);
        }
    }
}

static void test_ge_patch_tessellation(void) {
    const uint32_t vertex_addr = 0x08824000u;
    const uint32_t index_addr = 0x08825000u;
    const uint32_t large_vertex_addr = 0x08826000u;
    const uint32_t attribute_vertex_addr = 0x08828000u;
    GeState *state = ge_state_ptr();
    GeState saved = *state;
    memset(state, 0, sizeof(*state));
    state->patch_division = 2u | (2u << 8);
    state->patch_primitive = 0;
    state->scis_x2 = 511;
    state->scis_y2 = 271;
    state->maxz = 65535;
    write_patch_control_grid(vertex_addr, 4, 4);

    GeBackend backend;
    memset(&backend, 0, sizeof(backend));
    backend.name = "patch-test";
    backend.tri = test_backend_triangle;
    backend.line = test_backend_line;
    backend.point = test_backend_point;
    ge_set_backend(&backend);
    ge_execute_op(0x10080000u, 0);
    ge_execute_op(
        0x12000000u | (3u << 7) | (1u << 23), 0);

    backend_triangle_count = 0;
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x05000404u, 0);
    check_u32("Bezier triangle count", backend_triangle_count, 8);
    check_float("Bezier final triangle ax", backend_triangle[0].x, 50.0f);
    check_float("Bezier final triangle ay", backend_triangle[0].y, 45.0f);
    check_float("Bezier final triangle bx", backend_triangle[1].x, 35.0f);
    check_float("Bezier final triangle by", backend_triangle[1].y, 60.0f);
    check_float("Bezier final triangle cx", backend_triangle[2].x, 50.0f);
    check_float("Bezier final triangle cy", backend_triangle[2].y, 60.0f);
    check_u32(
        "Bezier vertex advance", state->vaddr,
        vertex_addr + 16u * 12u);

    backend_triangle_count = 0;
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(
        0x06000000u | 4u | (4u << 8) | (3u << 16) | (3u << 18),
        0);
    check_u32("spline triangle count", backend_triangle_count, 8);
    check_float("spline final triangle ax", backend_triangle[0].x, 50.0f);
    check_float("spline final triangle ay", backend_triangle[0].y, 45.0f);
    check_float("spline final triangle bx", backend_triangle[1].x, 35.0f);
    check_float("spline final triangle by", backend_triangle[1].y, 60.0f);
    check_float("spline final triangle cx", backend_triangle[2].x, 50.0f);
    check_float("spline final triangle cy", backend_triangle[2].y, 60.0f);

    backend_line_count = 0;
    ge_execute_op(0x37000001u, 0);
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x05000404u, 0);
    check_u32("Bezier line count", backend_line_count, 12);
    backend_point_count = 0;
    ge_execute_op(0x37000002u, 0);
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x05000404u, 0);
    check_u32("Bezier point count", backend_point_count, 24);
    check_u32("patch primitive command", state->patch_primitive, 2);

    backend_triangle_count = 0;
    ge_execute_op(0x36000303u, 0);
    ge_execute_op(0x37000000u, 0);
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x05000404u, 0);
    check_u32("exact Bezier triangle count", backend_triangle_count, 18);
    check_float(
        "exact Bezier quantized v", backend_triangle[0].v,
        171.0f / 256.0f);
    check_float(
        "exact Bezier quantized u", backend_triangle[1].u,
        171.0f / 256.0f);
    check_float(
        "exact Bezier position y", backend_triangle[0].y,
        50.0390625f);
    check_float(
        "exact Bezier position x", backend_triangle[1].x,
        40.0390625f);

    write_patch_attribute_grid(attribute_vertex_addr);
    backend_triangle_count = 0;
    ge_execute_op(0x36000202u, 0);
    ge_execute_op(
        0x12000000u | 3u | (7u << 2) |
        (3u << 7) | (1u << 23),
        0);
    ge_execute_op(
        0x01000000u | (attribute_vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x05000404u, 0);
    check_u32("attribute Bezier triangle count", backend_triangle_count, 8);
    check_float("attribute Bezier final au", backend_triangle[0].u, 190.0f);
    check_float("attribute Bezier final av", backend_triangle[0].v, 230.0f);
    check_float("attribute Bezier final bu", backend_triangle[1].u, 145.0f);
    check_float("attribute Bezier final bv", backend_triangle[1].v, 260.0f);
    check_u32(
        "attribute Bezier final ar", (uint32_t)backend_triangle[0].r, 180);
    check_u32(
        "attribute Bezier final ag", (uint32_t)backend_triangle[0].g, 75);
    check_u32(
        "attribute Bezier final ab", (uint32_t)backend_triangle[0].b, 20);
    check_u32(
        "attribute Bezier final aa", (uint32_t)backend_triangle[0].a, 255);
    check_u32(
        "attribute Bezier final br", (uint32_t)backend_triangle[1].r, 90);
    check_u32(
        "attribute Bezier final bg", (uint32_t)backend_triangle[1].g, 150);
    check_u32(
        "attribute Bezier vertex advance", state->vaddr,
        attribute_vertex_addr + 16u * 24u);

    for (int i = 0; i < 16; i++)
        MEM_W8(index_addr + (uint32_t)i, 15 - i);
    backend_triangle_count = 0;
    ge_execute_op(0x36000202u, 0);
    ge_execute_op(
        0x12000000u | (3u << 7) | (1u << 11) | (1u << 23), 0);
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x02000000u | (index_addr & 0x00ffffffu), 0);
    ge_execute_op(0x05000404u, 0);
    check_u32("indexed Bezier triangle count", backend_triangle_count, 8);
    check_float("indexed Bezier final ax", backend_triangle[0].x, 20.0f);
    check_float("indexed Bezier final ay", backend_triangle[0].y, 45.0f);
    check_u32("indexed Bezier vertex pointer", state->vaddr, vertex_addr);
    check_u32(
        "indexed Bezier index advance", state->iaddr, index_addr + 16u);

    ge_execute_op(
        0x12000000u | (3u << 7) | (1u << 23), 0);
    backend_triangle_count = 0;
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x05000403u, 0);
    check_u32("invalid Bezier triangle count", backend_triangle_count, 0);
    check_u32(
        "invalid Bezier vertex advance", state->vaddr,
        vertex_addr + 12u * 12u);
    ge_execute_op(0x01000000u | (vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x06000403u, 0);
    check_u32("invalid spline triangle count", backend_triangle_count, 0);
    check_u32(
        "invalid spline vertex advance", state->vaddr,
        vertex_addr + 12u * 12u);

    write_patch_control_grid(large_vertex_addr, 10, 10);
    backend_triangle_count = 0;
    ge_execute_op(0x36007f7fu, 0);
    ge_execute_op(
        0x01000000u | (large_vertex_addr & 0x00ffffffu), 0);
    ge_execute_op(0x05000a0au, 0);
    check_u32(
        "capped Bezier triangle count", backend_triangle_count, 127008);
    check_u32(
        "large Bezier vertex advance", state->vaddr,
        large_vertex_addr + 100u * 12u);

    ge_set_backend(NULL);
    *state = saved;
}

static void set_texture_level(GeState *state, int level, uint32_t address,
                              uint32_t stride, int width, int height) {
    state->tex_addr_levels[level] = address;
    state->tex_bufw_levels[level] = stride;
    state->tex_width_levels[level] = width;
    state->tex_height_levels[level] = height;
    if (level == 0) {
        state->tex_addr = address;
        state->tex_bufw = stride;
        state->tex_w = width;
        state->tex_h = height;
    }
}

static void set_clut8888(GeState *state, uint32_t index, uint32_t color) {
    memcpy(&state->clutram[(index * 4) & 2047], &color, sizeof(color));
}

static void test_ge_texture_decode(void) {
    const uint32_t texture_addr = 0x08822000u;
    GeState *state = ge_state_ptr();
    uint32_t pixels[16 * 8];

    memset(state, 0, sizeof(*state));
    set_texture_level(state, 0, texture_addr, 4, 4, 1);
    state->tex_fmt = 0;
    MEM_W16(texture_addr + 0, 0x001fu);
    MEM_W16(texture_addr + 2, 0x07e0u);
    MEM_W16(texture_addr + 4, 0xf800u);
    MEM_W16(texture_addr + 6, 0xffffu);
    ge_decode_tex_rgba(pixels);
    check_u32("texture 565 red", pixels[0], 0xff0000ffu);
    check_u32("texture 565 green", pixels[1], 0xff00ff00u);
    check_u32("texture 565 blue", pixels[2], 0xffff0000u);
    check_u32("texture 565 white", pixels[3], 0xffffffffu);

    state->tex_fmt = 1;
    MEM_W16(texture_addr, 0xfc00u);
    ge_decode_tex_rgba(pixels);
    check_u32("texture 5551 blue alpha", pixels[0], 0xffff0000u);

    state->tex_fmt = 2;
    MEM_W16(texture_addr, 0x4321u);
    ge_decode_tex_rgba(pixels);
    check_u32("texture 4444 channels", pixels[0], 0x44332211u);

    state->tex_fmt = 3;
    MEM_W32(texture_addr, 0x44332211u);
    ge_decode_tex_rgba(pixels);
    check_u32("texture 8888 channels", pixels[0], 0x44332211u);

    memset(state->clutram, 0, sizeof(state->clutram));
    state->clut_fmt = 3u | (0xffu << 8);
    set_clut8888(state, 1, 0x11223344u);
    set_clut8888(state, 2, 0x55667788u);
    state->tex_fmt = 4;
    set_texture_level(state, 0, texture_addr, 2, 2, 1);
    MEM_W8(texture_addr, 0x21u);
    ge_decode_tex_rgba(pixels);
    check_u32("texture CLUT4 low nibble", pixels[0], 0x11223344u);
    check_u32("texture CLUT4 high nibble", pixels[1], 0x55667788u);

    set_clut8888(state, 3, 0x89abcdefu);
    state->tex_fmt = 5;
    set_texture_level(state, 0, texture_addr, 1, 1, 1);
    MEM_W8(texture_addr, 3);
    ge_decode_tex_rgba(pixels);
    check_u32("texture CLUT8", pixels[0], 0x89abcdefu);

    set_clut8888(state, 4, 0x10203040u);
    state->tex_fmt = 6;
    state->clut_fmt = 3u | (8u << 2) | (0xffu << 8);
    MEM_W16(texture_addr, 0x0400u);
    ge_decode_tex_rgba(pixels);
    check_u32("texture CLUT16 shifted index", pixels[0], 0x10203040u);

    set_clut8888(state, 5, 0x50607080u);
    state->tex_fmt = 7;
    state->clut_fmt = 3u | (16u << 2) | (0xffu << 8);
    MEM_W32(texture_addr, 0x00050000u);
    ge_decode_tex_rgba(pixels);
    check_u32("texture CLUT32 shifted index", pixels[0], 0x50607080u);

    memset(SR_HOST(texture_addr), 0, 256);
    state->tex_fmt = 3;
    state->tex_swizzle = 1;
    set_texture_level(state, 0, texture_addr, 16, 16, 8);
    MEM_W32(texture_addr + 128, 0xa1b2c3d4u);
    ge_decode_tex_rgba(pixels);
    check_u32("texture swizzle second horizontal block", pixels[4], 0xa1b2c3d4u);

    memset(SR_HOST(texture_addr), 0, 32);
    state->tex_swizzle = 0;
    state->tex_fmt = 8;
    set_texture_level(state, 0, texture_addr, 4, 4, 4);
    MEM_W8(texture_addr + 0, 0xe4u);
    MEM_W16(texture_addr + 4, 0xf800u);
    MEM_W16(texture_addr + 6, 0x001fu);
    ge_decode_tex_rgba(pixels);
    check_u32("texture DXT1 endpoint one", pixels[0], 0xff0000f8u);
    check_u32("texture DXT1 endpoint two", pixels[1], 0xfff80000u);
    check_u32("texture DXT1 interpolation one", pixels[2], 0xff5200a5u);
    check_u32("texture DXT1 interpolation two", pixels[3], 0xffa50052u);

    state->tex_fmt = 9;
    MEM_W16(texture_addr + 8, 0x000au);
    ge_decode_tex_rgba(pixels);
    check_u32("texture DXT3 alpha", pixels[0], 0xa00000f8u);

    state->tex_fmt = 10;
    MEM_W32(texture_addr + 8, 7u);
    MEM_W16(texture_addr + 12, 0);
    MEM_W8(texture_addr + 14, 10);
    MEM_W8(texture_addr + 15, 20);
    ge_decode_tex_rgba(pixels);
    check_u32("texture DXT5 explicit alpha", pixels[0], 0xff0000f8u);

    memset(state->clutram, 0, sizeof(state->clutram));
    state->tex_fmt = 4;
    state->tex_mode = 0x100u;
    state->clut_fmt = 3u | (0xffu << 8);
    set_texture_level(state, 1, texture_addr + 0x100, 1, 1, 1);
    set_clut8888(state, 1, 0x11111111u);
    set_clut8888(state, 17, 0x22222222u);
    MEM_W8(texture_addr + 0x100, 1);
    ge_decode_tex_rgba_level(pixels, 1);
    check_u32("texture per-level CLUT", pixels[0], 0x22222222u);

    memset(state, 0, sizeof(*state));
    ge_execute_op(0xa1812340u, 0);
    ge_execute_op(0xa9080008u, 0);
    ge_execute_op(0xb9000102u, 0);
    ge_execute_op(0xc2020001u, 0);
    check_u32("texture mip address register",
              state->tex_addr_levels[1], 0x08812340u);
    check_u32("texture mip stride register",
              state->tex_bufw_levels[1], 8);
    check_u32("texture mip width register",
              (uint32_t)state->tex_width_levels[1], 4);
    check_u32("texture mip height register",
              (uint32_t)state->tex_height_levels[1], 2);
    check_u32("texture max mip register", (uint32_t)state->tex_max_level, 2);
    check_u32("texture swizzle register", (uint32_t)state->tex_swizzle, 1);

    state->tex_fmt = 0;
    state->tex_swizzle = 0;
    set_texture_level(state, 0, texture_addr, 4, 4, 4);
    check_u32("texture linear byte size",
              (uint32_t)ge_texture_level_byte_size(state, 0), 64);
    state->tex_fmt = 5;
    state->tex_swizzle = 1;
    set_texture_level(state, 0, texture_addr, 16, 16, 1);
    check_u32("texture swizzled byte size",
              (uint32_t)ge_texture_level_byte_size(state, 0), 128);
    state->tex_fmt = 8;
    state->tex_swizzle = 0;
    set_texture_level(state, 0, texture_addr, 8, 8, 8);
    check_u32("texture DXT1 byte size",
              (uint32_t)ge_texture_level_byte_size(state, 0), 32);
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

static int guest_audio_nonzero(uint32_t addr, int frames) {
    for (int i = 0; i < frames * 2; i++)
        if ((int16_t)MEM_R16(addr + (uint32_t)i * 2) != 0) return 1;
    return 0;
}

static void clear_guest_audio(uint32_t addr, int frames) {
    for (int i = 0; i < frames * 2; i++)
        MEM_W16(addr + (uint32_t)i * 2, 0);
}

static void configure_sas_noise(CpuState *cpu, uint32_t core, uint32_t output) {
    check_u32("SAS init",
              hle_call7(cpu, 0x42778a9fu, core, 64, 32, 0, 44100, 0, 0), 0);
    check_u32("SAS noise voice",
              hle_call(cpu, 0xb7660a23u, core, 0, 63, 0), 0);
    check_u32("SAS volume and send",
              hle_call7(cpu, 0x440ca7d8u, core, 0, 0x1000, 0x1000,
                        0x1000, 0x1000, 0), 0);
    check_u32("SAS ADSR modes",
              hle_call7(cpu, 0x9ec3676au, core, 0, 15, 0, 5, 5, 1), 0);
    check_u32("SAS ADSR rates",
              hle_call7(cpu, 0x019b25ebu, core, 0, 15, 0x40000000u,
                        0x40000000u, 0x40000000u, 0x01000000u), 0);
    check_u32("SAS sustain level",
              hle_call(cpu, 0x5f9529f6u, core, 0, 0x40000000u, 0), 0);
    check_u32("SAS key on",
              hle_call(cpu, 0x76f01acau, core, 0, 0, 0), 0);
    clear_guest_audio(output, 64);
}

static void test_sas(CpuState *cpu) {
    const uint32_t core = 0x0881b000u;
    const uint32_t output = 0x0881c000u;

    check_u32("SAS invalid noise voice",
              hle_call(cpu, 0xb7660a23u, core, 0xffffffffu, 1, 0), 0x80420010u);
    check_u32("SAS invalid noise frequency",
              hle_call(cpu, 0xb7660a23u, core, 0, 64, 0), 0x80420011u);
    check_u32("SAS invalid ADSR rate",
              hle_call7(cpu, 0x019b25ebu, core, 0, 1, 0xffffffffu, 0, 0, 0),
              0x80420019u);
    check_u32("SAS ignored invalid ADSR rate",
              hle_call7(cpu, 0x019b25ebu, core, 0, 0, 0xffffffffu, 0, 0, 0), 0);
    check_u32("SAS invalid ADSR mode",
              hle_call7(cpu, 0x9ec3676au, core, 0, 1, 1, 1, 1, 1),
              0x80420013u);
    check_u32("SAS invalid simple ADSR",
              hle_call(cpu, 0xcbcd4f79u, core, 0, 0, 0x2000), 0x80420013u);
    check_u32("SAS invalid pitch",
              hle_call(cpu, 0xad84d37fu, core, 0, 0x4001, 0), 0x80420012u);
    check_u32("SAS invalid dry volume",
              hle_call7(cpu, 0x440ca7d8u, core, 0, 0x1001, 0, 0, 0, 0),
              0x80420018u);
    check_u32("SAS invalid effect volume",
              hle_call7(cpu, 0x440ca7d8u, core, 0, 0, 0, 0xffffefffu, 0, 0),
              0x80420018u);
    check_u32("SAS invalid reverb delay",
              hle_call(cpu, 0x267a6dd2u, core, 128, 0, 0), 0x80420022u);
    check_u32("SAS invalid reverb feedback",
              hle_call(cpu, 0x267a6dd2u, core, 0, 128, 0), 0x80420021u);
    check_u32("SAS invalid reverb type",
              hle_call(cpu, 0x33d4ab37u, core, 9, 0, 0), 0x80420020u);
    check_u32("SAS invalid reverb volume",
              hle_call(cpu, 0xd5a229c9u, core, 0x1001, 0, 0), 0x80420023u);

    check_u32("SAS set pause mask",
              hle_call(cpu, 0x787d04d5u, core, 0x80000003u, 1, 0), 0);
    check_u32("SAS get pause mask",
              hle_call(cpu, 0x2c8e6ab3u, core, 0, 0, 0), 0x80000003u);
    check_u32("SAS clear pause mask",
              hle_call(cpu, 0x787d04d5u, core, 0xffffffffu, 0, 0), 0);

    configure_sas_noise(cpu, core, output);
    check_u32("SAS duplicate key on",
              hle_call(cpu, 0x76f01acau, core, 0, 0, 0), 0x80420016u);
    check_u32("SAS noise mix",
              hle_call(cpu, 0xa3589d81u, core, output, 0, 0), 0);
    check_u32("SAS noise output", (uint32_t)guest_audio_nonzero(output, 64), 1);
    uint32_t height = hle_call(cpu, 0x74ae582au, core, 0, 0, 0);
    check_u32("SAS envelope attack", height, 0x40000000u);

    check_u32("SAS pause voice",
              hle_call(cpu, 0x787d04d5u, core, 1, 1, 0), 0);
    clear_guest_audio(output, 64);
    check_u32("SAS paused mix",
              hle_call(cpu, 0xa3589d81u, core, output, 0, 0), 0);
    check_u32("SAS paused output", (uint32_t)guest_audio_nonzero(output, 64), 0);
    check_u32("SAS paused envelope",
              hle_call(cpu, 0x74ae582au, core, 0, 0, 0), height);
    check_u32("SAS key off while paused",
              hle_call(cpu, 0xa0cf2fa4u, core, 0, 0, 0), 0x80420016u);
    check_u32("SAS resume voice",
              hle_call(cpu, 0x787d04d5u, core, 1, 0, 0), 0);
    check_u32("SAS key off",
              hle_call(cpu, 0xa0cf2fa4u, core, 0, 0, 0), 0);
    clear_guest_audio(output, 64);
    check_u32("SAS release mix",
              hle_call(cpu, 0xa3589d81u, core, output, 0, 0), 0);
    uint32_t released = hle_call(cpu, 0x74ae582au, core, 0, 0, 0);
    check_u32("SAS release envelope", released, 0);

    check_u32("SAS reinit for simple ADSR",
              hle_call7(cpu, 0x42778a9fu, core, 64, 32, 0, 44100, 0, 0), 0);
    check_u32("SAS simple ADSR",
              hle_call(cpu, 0xcbcd4f79u, core, 0, 0x000fu, 0x5fc0u), 0);
    check_u32("SAS simple noise",
              hle_call(cpu, 0xb7660a23u, core, 0, 63, 0), 0);
    check_u32("SAS wet-only volume",
              hle_call7(cpu, 0x440ca7d8u, core, 0, 0, 0, 0x1000, 0x1000, 0), 0);
    check_u32("SAS reverb off preset",
              hle_call(cpu, 0x33d4ab37u, core, 0xffffffffu, 0, 0), 0);
    check_u32("SAS reverb volume",
              hle_call(cpu, 0xd5a229c9u, core, 0x1000, 0x1000, 0), 0);
    check_u32("SAS wet-only route",
              hle_call(cpu, 0xf983b186u, core, 0, 1, 0), 0);
    check_u32("SAS simple key on",
              hle_call(cpu, 0x76f01acau, core, 0, 0, 0), 0);
    clear_guest_audio(output, 64);
    check_u32("SAS wet-only mix",
              hle_call(cpu, 0xa3589d81u, core, output, 0, 0), 0);
    check_u32("SAS wet output", (uint32_t)guest_audio_nonzero(output, 64), 1);

    check_u32("SAS room reverb preset",
              hle_call(cpu, 0x33d4ab37u, core, 0, 0, 0), 0);
    int room_tail = 0;
    for (int i = 0; i < 64; i++) {
        clear_guest_audio(output, 64);
        check_u32("SAS room mix",
                  hle_call(cpu, 0xa3589d81u, core, output, 0, 0), 0);
        room_tail |= guest_audio_nonzero(output, 64);
    }
    check_u32("SAS room reverb output", (uint32_t)room_tail, 1);
}

static void test_audio_input(CpuState *cpu) {
    const uint32_t params = 0x0881d000u;
    const uint32_t buffer = 0x0881d100u;

    for (uint32_t i = 0; i < 24; i++) MEM_W8(params + i, (uint8_t)(0xa0u + i));
    check_u32("audio input init",
              hle_call(cpu, 0xe926d3fbu, params, 0, 0, 0), 0);

    MEM_W16(buffer - 2, 0x1234);
    for (uint32_t i = 0; i < 64; i++) MEM_W16(buffer + i * 2, 0x7f7f);
    MEM_W16(buffer + 128, 0x5678);
    check_u32("audio input samples",
              hle_call(cpu, 0x6d4bec68u, 64, 11025, buffer, 0), 64);
    for (uint32_t i = 0; i < 64; i++) {
        if (MEM_R16(buffer + i * 2) != 0) {
            fail_u32("audio input silence", MEM_R16(buffer + i * 2), 0);
            break;
        }
    }
    check_u32("audio input prefix guard", MEM_R16(buffer - 2), 0x1234);
    check_u32("audio input suffix guard", MEM_R16(buffer + 128), 0x5678);
    check_u32("audio input wait",
              hle_call(cpu, 0x87b2e651u, 0, 0, 0, 0), 0);
    check_u32("audio input second wait",
              hle_call(cpu, 0x87b2e651u, 0, 0, 0, 0), 0);

    MEM_W16(buffer, 0x4321);
    check_u32("audio input empty",
              hle_call(cpu, 0x6d4bec68u, 0, 44100, buffer, 0), 0);
    check_u32("audio input empty buffer", MEM_R16(buffer), 0x4321);
    check_u32("audio input invalid rate",
              hle_call(cpu, 0x6d4bec68u, 64, 8000, buffer, 0), 0xffffffffu);
    check_u32("audio input invalid size",
              hle_call(cpu, 0x6d4bec68u, 65536, 11025, buffer, 0), 0xffffffffu);
    check_u32("audio input null buffer",
              hle_call(cpu, 0x6d4bec68u, 64, 11025, 0, 0), 0xffffffffu);
    check_u32("audio input crossing memory",
              hle_call(cpu, 0x6d4bec68u, 64, 11025, 0x0bffffc0u, 0),
              0xffffffffu);
}

static void test_audio_output2(CpuState *cpu) {
    const uint32_t buffer = 0x0881e000u;

    check_u32("audio output2 release unreserved",
              hle_call(cpu, 0x43196845u, 0, 0, 0, 0), 0x80260008u);
    check_u32("audio output2 short reserve",
              hle_call(cpu, 0x01562ba3u, 16, 0, 0, 0), 0x80000104u);
    check_u32("audio output2 long reserve",
              hle_call(cpu, 0x01562ba3u, 4112, 0, 0, 0), 0x80000104u);
    check_u32("audio output2 reserve",
              hle_call(cpu, 0x01562ba3u, 64, 0, 0, 0), 0);
    check_u32("audio output2 duplicate reserve",
              hle_call(cpu, 0x01562ba3u, 64, 0, 0, 0), 0x80268002u);
    check_u32("audio output2 invalid volume",
              hle_call(cpu, 0x2d53f36eu, 0x100000, buffer, 0, 0), 0x8026000bu);

    clear_guest_audio(buffer, 96);
    check_u32("audio output2 samples",
              hle_call(cpu, 0x2d53f36eu, 0x8000, buffer, 0, 0), 64);
    check_u32("audio output2 change length",
              hle_call(cpu, 0x63f2889cu, 96, 0, 0, 0), 0);
    check_u32("audio output2 changed samples",
              hle_call(cpu, 0x2d53f36eu, 0x8000, buffer, 0, 0), 96);
    check_u32("audio output2 release",
              hle_call(cpu, 0x43196845u, 0, 0, 0, 0), 0);
    check_u32("audio output2 output unreserved",
              hle_call(cpu, 0x2d53f36eu, 0x8000, buffer, 0, 0), 0x80260008u);
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

static void test_utility_system_params(CpuState *cpu) {
    const uint32_t out_addr = 0x08812200u;
    check_u32("system language",
              hle_call(cpu, 0xa5da2406u, 8, out_addr, 0, 0), 0);
    check_u32("system language value", MEM_R32(out_addr), 1);

    for (uint32_t i = 0; i < 16; i++) MEM_W8(out_addr + i, 0xcc);
    check_u32("system nickname",
              hle_call(cpu, 0x34b78343u, 1, out_addr, 16, 0), 0);
    static const uint8_t nickname[16] = {
        's', 'h', 'a', 'd', 'o', 'w', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    };
    check_guest_bytes("system nickname value", out_addr, nickname, sizeof(nickname));
    check_u32("system nickname buffer too short",
              hle_call(cpu, 0x34b78343u, 1, out_addr, 6, 0), 0x80110102u);
    check_u32("invalid string system parameter",
              hle_call(cpu, 0x34b78343u, 2, out_addr, 16, 0), 0x80110103u);
}

static void test_atrac_reset_buffer_info(CpuState *cpu) {
    const uint32_t data_addr = 0x08812300u;
    const uint32_t info_addr = 0x08812400u;
    const uint32_t error_addr = 0x08812440u;
    const uint32_t loop_addr = 0x08812450u;
    const uint32_t status_addr = 0x08812454u;
    const uint32_t end_sample = 8192u;
    const uint32_t fmt_offset = 12u;
    const uint32_t fact_offset = 72u;
    const uint32_t smpl_offset = 88u;
    const uint32_t data_offset = 156u;
    const uint32_t file_size = 188u;

    for (uint32_t i = 0; i < file_size; i++) MEM_W8(data_addr + i, 0);
    MEM_W32(data_addr + 0, 0x46464952u);
    MEM_W32(data_addr + 4, file_size - 8u);
    MEM_W32(data_addr + 8, 0x45564157u);
    MEM_W32(data_addr + fmt_offset, 0x20746d66u);
    MEM_W32(data_addr + fmt_offset + 4, 52);
    MEM_W16(data_addr + fmt_offset + 8, 0xfffeu);
    MEM_W16(data_addr + fmt_offset + 10, 2);
    MEM_W32(data_addr + fmt_offset + 12, 44100);
    MEM_W32(data_addr + fmt_offset + 16, 44100);
    MEM_W16(data_addr + fmt_offset + 20, 8);
    MEM_W32(data_addr + fact_offset, 0x74636166u);
    MEM_W32(data_addr + fact_offset + 4, 8);
    MEM_W32(data_addr + fact_offset + 8, end_sample);
    MEM_W32(data_addr + fact_offset + 12, 0);
    MEM_W32(data_addr + smpl_offset, 0x6c706d73u);
    MEM_W32(data_addr + smpl_offset + 4, 60);
    MEM_W32(data_addr + smpl_offset + 8 + 28, 1);
    MEM_W32(data_addr + smpl_offset + 8 + 44, 0);
    MEM_W32(data_addr + smpl_offset + 8 + 48, end_sample - 1u);
    MEM_W32(data_addr + data_offset, 0x61746164u);
    MEM_W32(data_addr + data_offset + 4, 24);

    uint32_t atrac_id =
        hle_call(cpu, 0x7a20e7afu, data_addr, file_size, 0, 0);
    check_u32("ATRAC allocated ID", atrac_id, 0);

    for (uint32_t i = 0; i < 32; i++) MEM_W8(info_addr + i, 0xcc);
    check_u32("ATRAC reset buffer info",
              hle_call(cpu, 0x2dd3e298u, atrac_id, 4096, info_addr, 0), 0);
    check_u32("ATRAC reset first write pointer", MEM_R32(info_addr + 0), data_addr);
    check_u32("ATRAC reset first writable bytes", MEM_R32(info_addr + 4), 0);
    check_u32("ATRAC reset first minimum bytes", MEM_R32(info_addr + 8), 0);
    check_u32("ATRAC reset first file position", MEM_R32(info_addr + 12), 0);
    check_u32("ATRAC reset second write pointer", MEM_R32(info_addr + 16), data_addr);
    check_u32("ATRAC reset second writable bytes", MEM_R32(info_addr + 20), 0);
    check_u32("ATRAC reset second minimum bytes", MEM_R32(info_addr + 24), 0);
    check_u32("ATRAC reset second file position", MEM_R32(info_addr + 28), 0);
    check_u32("ATRAC reset sample past end",
              hle_call(cpu, 0x2dd3e298u, atrac_id, end_sample + 1, info_addr, 0),
              0x80630015u);
    check_u32("ATRAC reset invalid output",
              hle_call(cpu, 0x2dd3e298u, atrac_id, 0, 0, 0), 0x800200d3u);
    check_u32("ATRAC reset invalid ID",
              hle_call(cpu, 0x2dd3e298u, 7, 0, info_addr, 0), 0x80630002u);

    MEM_W32(error_addr, 0xccccccccu);
    check_u32("ATRAC internal error",
              hle_call(cpu, 0xe88f759bu, atrac_id, error_addr, 0, 0), 0);
    check_u32("ATRAC internal codec status", MEM_R32(error_addr), 0);
    check_u32("ATRAC internal error ignored output",
              hle_call(cpu, 0xe88f759bu, atrac_id, 0x0bffffffu, 0, 0), 0);
    MEM_W32(error_addr, 0xccccccccu);
    check_u32("ATRAC internal error invalid ID",
              hle_call(cpu, 0xe88f759bu, 7, error_addr, 0, 0), 0x80630002u);
    check_u32("ATRAC invalid ID leaves status", MEM_R32(error_addr), 0xccccccccu);

    check_u32("ATRAC set one loop",
              hle_call(cpu, 0x868120b5u, atrac_id, 1, 0, 0), 0);
    check_u32("ATRAC loop status",
              hle_call(cpu, 0xfaa4f89bu, atrac_id, loop_addr, status_addr, 0), 0);
    check_u32("ATRAC finite loop retained", MEM_R32(loop_addr), 1);
    check_u32("ATRAC loop metadata present", MEM_R32(status_addr), 1);
    check_u32("ATRAC set infinite loop",
              hle_call(cpu, 0x868120b5u, atrac_id, 0xffffffffu, 0, 0), 0);
    check_u32("ATRAC infinite loop status",
              hle_call(cpu, 0xfaa4f89bu, atrac_id, loop_addr, status_addr, 0), 0);
    check_u32("ATRAC infinite loop retained", MEM_R32(loop_addr), 0xffffffffu);

    check_u32("ATRAC release ID",
              hle_call(cpu, 0x61eb33f5u, atrac_id, 0, 0, 0), 0);

    MEM_W32(data_addr + 4, data_offset + 8u + 1024u - 8u);
    MEM_W32(data_addr + data_offset + 4, 1024);
    atrac_id = hle_call(cpu, 0x7a20e7afu, data_addr, file_size, 0, 0);
    check_u32("ATRAC streamed ID", atrac_id, 0);
    check_u32("ATRAC streamed remain",
              hle_call(cpu, 0x9ae849a7u, atrac_id, info_addr, 0, 0), 0);
    check_u32("ATRAC streamed initial frames", MEM_R32(info_addr), 3);
    check_u32("ATRAC stream data info",
              hle_call(cpu, 0x5d268707u, atrac_id, info_addr,
                       info_addr + 4, info_addr + 8), 0);
    check_u32("ATRAC stream write pointer", MEM_R32(info_addr), data_addr);
    check_u32("ATRAC stream writable bytes", MEM_R32(info_addr + 4), 164);
    check_u32("ATRAC stream read offset", MEM_R32(info_addr + 8), file_size);
    check_u32("ATRAC add stream data",
              hle_call(cpu, 0x7db31251u, atrac_id, 32, 0, 0), 0);
    check_u32("ATRAC add without query",
              hle_call(cpu, 0x7db31251u, atrac_id, 1, 0, 0), 0x80630018u);
    check_u32("ATRAC streamed remain after add",
              hle_call(cpu, 0x9ae849a7u, atrac_id, info_addr, 0, 0), 0);
    check_u32("ATRAC streamed added frames", MEM_R32(info_addr), 7);
    check_u32("ATRAC streamed reset info",
              hle_call(cpu, 0x2dd3e298u, atrac_id, 4096, info_addr, 0), 0);
    check_u32("ATRAC streamed reset pointer", MEM_R32(info_addr), data_addr);
    check_u32("ATRAC streamed reset bytes", MEM_R32(info_addr + 4), file_size);
    check_u32("ATRAC streamed reset minimum", MEM_R32(info_addr + 8), 8);
    check_u32("ATRAC streamed reset file offset", MEM_R32(info_addr + 12), 180);
    check_u32("ATRAC streamed reset position",
              hle_call(cpu, 0x644e5607u, atrac_id, 4096, file_size, 0), 0);
    check_u32("ATRAC release streamed ID",
              hle_call(cpu, 0x61eb33f5u, atrac_id, 0, 0, 0), 0);
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

    const uint64_t fixed_tick = 62135596923456789ull;
    _putenv_s("SR_RTC_FIXED_TICK", "62135596923456789");
    check_u32(
        "RTC fixed tick",
        hle_call(cpu, 0x3f7ad767u, clock_addr, 0, 0, 0),
        0);
    _putenv_s("SR_RTC_FIXED_TICK", "");
    check_u32("RTC fixed tick low", MEM_R32(clock_addr), (uint32_t)fixed_tick);
    check_u32(
        "RTC fixed tick high",
        MEM_R32(clock_addr + 4),
        (uint32_t)(fixed_tick >> 32));
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
    const uint32_t mode_addr = 0x0881c440u;
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
    static const SrDispatchEntry mpeg_dispatch[] = {
        {0x0881d000u, mpeg_fill_callback},
    };
    sr_set_dispatch_table(mpeg_dispatch, 1);
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
    MEM_W32(mode_addr, 0);
    MEM_W32(mode_addr + 4, 0);
    check_u32("mpeg AVC decode mode 5650",
              hle_call(cpu, 0xa11c7026u, mpeg_addr, mode_addr, 0, 0), 0);
    MEM_W32(mode_addr + 4, 3);
    check_u32("mpeg AVC decode mode 8888",
              hle_call(cpu, 0xa11c7026u, mpeg_addr, mode_addr, 0, 0), 0);
    MEM_W32(mode_addr + 4, 4);
    check_u32("mpeg AVC unknown decode mode",
              hle_call(cpu, 0xa11c7026u, mpeg_addr, mode_addr, 0, 0), 0);
    check_u32("mpeg AVC decode mode null",
              hle_call(cpu, 0xa11c7026u, mpeg_addr, 0, 0, 0), 0xffffffffu);
    check_u32("mpeg AVC decode mode bad handle",
              hle_call(cpu, 0xa11c7026u, 0, mode_addr, 0, 0), 0xffffffffu);
    MEM_W32(mode_addr + 4, 3);
    check_u32("mpeg AVC restore decode mode",
              hle_call(cpu, 0xa11c7026u, mpeg_addr, mode_addr, 0, 0), 0);
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

static int wait_end_worker_started;
static int turbo_delay_worker_finished;

static void wait_end_worker(CpuState *cpu) {
    wait_end_worker_started = 1;
    running_hle_call(cpu, 0x809ce29bu, 0x1234u, 0, 0, 0);
    fprintf(stderr, "FAIL: exit-delete worker resumed\n");
    failures++;
}

static void turbo_delay_worker(CpuState *cpu) {
    running_hle_call(cpu, 0xceadeb47u, 100000, 0, 0, 0);
    turbo_delay_worker_finished = 1;
    running_hle_call(cpu, 0x809ce29bu, 0, 0, 0, 0);
    fprintf(stderr, "FAIL: turbo delay worker resumed\n");
    failures++;
}

static void async_test_entry(CpuState *cpu) {
    const uint32_t path_addr = 0x0881a000u;
    const uint32_t result_addr = 0x0881a200u;
    const uint32_t data_addr = 0x0881a300u;
    const uint32_t ids_addr = 0x0881a400u;
    const uint32_t count_addr = 0x0881a500u;
    const uint32_t status_addr = 0x0881a600u;
    const uint32_t wait_end_entry = 0x08804010u;
    const uint32_t turbo_delay_entry = 0x08804020u;

    guest_string(path_addr, "turbo-delay-worker");
    cpu->r[8] = 0;
    uint32_t turbo_delay_uid =
        running_hle_call(cpu, 0x446d8de6u, path_addr, turbo_delay_entry, 16, 0x400);
    if ((int32_t)turbo_delay_uid < 0) {
        fail_u32("create turbo delay worker", turbo_delay_uid, 0);
    } else {
        check_u32("start turbo delay worker",
                  running_hle_call(cpu, 0xf475845du, turbo_delay_uid, 0, 0, 0), 0);
        for (int i = 0; i < 12 && !turbo_delay_worker_finished; i++)
            sr_yield(cpu);
        check_u32("turbo busy-thread advances delay",
                  (uint32_t)turbo_delay_worker_finished, 1);
    }

    guest_string(path_addr, "wait-end-worker");
    cpu->r[8] = 0;
    uint32_t wait_end_uid =
        running_hle_call(cpu, 0x446d8de6u, path_addr, wait_end_entry, 40, 0x400);
    if ((int32_t)wait_end_uid < 0) {
        fail_u32("create exit-delete worker", wait_end_uid, 0);
    } else {
        check_u32("start exit-delete worker",
                  running_hle_call(cpu, 0xf475845du, wait_end_uid, 0, 0, 0), 0);
        check_u32("wait for exit-delete worker",
                  running_hle_call(cpu, 0x278c0df5u, wait_end_uid, 0, 0, 0), 0);
        check_u32("exit-delete worker ran", (uint32_t)wait_end_worker_started, 1);
        MEM_W32(status_addr, 108);
        check_u32("exit-delete worker removed",
                  running_hle_call(cpu, 0x17c1684eu, wait_end_uid, status_addr, 0, 0),
                  0x80020198u);
    }

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

    static const SrDispatchEntry async_dispatch[] = {
        {0x08804000u, async_test_entry},
        {0x08804010u, wait_end_worker},
        {0x08804020u, turbo_delay_worker},
    };
    const uint32_t entry = 0x08804000u;
    sr_set_dispatch_table(async_dispatch, 3);
    memset(cpu, 0, sizeof(*cpu));
    cpu->r[29] = 0x09ff0000u;
    _putenv_s("SR_NOVBPACE", "1");
    sched_init(cpu);
    sched_run(entry, 0, 0, 1);

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

static void test_boot_seed_state(CpuState *cpu) {
    sr_set_next_uid(0x500);
    sr_set_boot_uid_gap(1);
    sr_boot_uid_delay_checkpoint();
    check_u32("bootloader UID gap next", sr_get_next_uid(), 0x501);
    check_u32("bootloader UID gap allocation", sr_alloc_uid(), 0x501);
    sr_boot_uid_delay_checkpoint();
    check_u32("bootloader UID gap once", sr_get_next_uid(), 0x502);

    sr_ge_set_next_list_id(41);
    check_u32("bootloader GE next list", sr_ge_get_next_list_id(), 41);
    const uint32_t list = 0x0881f000u;
    MEM_W32(list + 0, 0x0f000000u);
    MEM_W32(list + 4, 0x0c000000u);
    check_u32(
        "bootloader first GE list id",
        hle_call(cpu, 0xab49e76au, list, 0, 0, 0),
        0x35000029u);
    check_u32("bootloader following GE list", sr_ge_get_next_list_id(), 42);
}

static void test_hle_deadbeef_policy(CpuState *cpu) {
    memset(cpu, 0, sizeof(*cpu));
    cpu->r[4] = 0x03080010u;
    cpu->r[5] = 0x12345678u;
    sr_syscall(cpu, 0x7591c7dbu);
    check_u32("ordinary HLE deadbeef fill", cpu->r[5], 0xdeadbeefu);

    memset(cpu, 0, sizeof(*cpu));
    cpu->r[4] = 10000;
    cpu->r[5] = 0x12345678u;
    sr_syscall(cpu, 0xceadeb47u);
    check_u32("rescheduled HLE keeps a0", cpu->r[4], 10000);
    check_u32("rescheduled HLE keeps a1", cpu->r[5], 0x12345678u);
}

int main(void) {
    char root[128], local_app_data[128];
    snprintf(root, sizeof(root), "kzl_hle_test_fs_%lu", (unsigned long)GetCurrentProcessId());
    snprintf(local_app_data, sizeof(local_app_data), "kzl_hle_test_localappdata_%lu",
             (unsigned long)GetCurrentProcessId());
    _putenv_s("LOCALAPPDATA", local_app_data);
    _putenv_s("SR_FSDIR", "");
    _putenv_s("SR_NOAUDIO", "1");

    sr_mem_init();
    CpuState cpu;
    test_ge_state_dump();
    test_ge_backend_interface();
    test_ge_fragment_state();
    test_ge_fragment_writes();
    test_ge_decoded_vertex_boundary();
    test_ge_morph_vertices();
    test_ge_skinning_normal();
    test_ge_morph_skinning();
    test_ge_patch_tessellation();
    test_ge_texture_decode();
    test_default_vfs_root(&cpu, local_app_data);
    _putenv_s("SR_FSDIR", root);
    test_threadman(&cpu);
    test_utility_system_params(&cpu);
    test_atrac_reset_buffer_info(&cpu);
    test_sas(&cpu);
    test_audio_input(&cpu);
    test_audio_output2(&cpu);
    test_time(&cpu);
    test_io(&cpu, root);
    test_iso_directory(&cpu);
    test_mpeg_eof(&cpu);
    test_async_io(&cpu, root);
    test_offline_network(&cpu);
    test_boot_seed_state(&cpu);
    test_hle_deadbeef_policy(&cpu);

    if (failures) {
        fprintf(stderr, "HLE smoke tests: %d failure(s)\n", failures);
        return 1;
    }
    printf("HLE smoke tests passed\n");
    return 0;
}
