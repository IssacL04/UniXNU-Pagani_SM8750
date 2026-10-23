// SPDX-License-Identifier: BSD-2-Clause-Patent
// Compile with -fsanitize=address,undefined; uses the actual renderer and map builder.
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#define BOOT_PROGRESS_TEST 1
#ifndef T0SZ_BOOT
#define T0SZ_BOOT 26
#endif
typedef struct boot_args {
    uint16_t Revision, Version;
    uint64_t virtBase, physBase, memSize, topOfKernelData;
    struct { uint64_t v_baseAddr, v_display, v_rowBytes, v_width, v_height, v_depth; } Video;
} boot_args;
typedef void *thread_call_t;
enum { NSEC_PER_SEC = 1000000000, THREAD_CALL_PRIORITY_KERNEL = 1, THREAD_CALL_OPTIONS_ONCE = 1 };
struct { uint32_t timebase_frequency_hz; } gPEClockFrequencyInfo;
volatile uint32_t armdt_platform_configured, armcpu_registered, armcpu_gic_ready, armcpu_gic_boot[8];
volatile uint64_t armcpu_timer_interrupts;
void early_boot_progress_vectors_done(void) {}
static uintptr_t ml_io_map_wcomb(uintptr_t base, uint64_t size) { (void)size; return base; }
static void clock_interval_to_deadline(unsigned n, unsigned scale, uint64_t *deadline) { *deadline = (uint64_t)n * scale; }
static unsigned scheduled;
static void thread_call_enter_delayed(thread_call_t call, uint64_t deadline) { (void)call; assert(deadline == NSEC_PER_SEC); scheduled++; }
static void thread_call_enter(thread_call_t call) { assert(call); }
static thread_call_t thread_call_allocate_with_options(void (*fn)(void *, void *), void *arg, int priority, int options)
{ (void)fn; (void)arg; (void)priority; (void)options; return (void *)1; }
#define BOOT_LOGO_WIDTH 4
#define BOOT_LOGO_HEIGHT 4
#define BOOT_LOGO_X 2
#define BOOT_LOGO_Y -1
static const unsigned char boot_logo[] = {0,64,128,255,255,128,64,0,0,64,128,255,255,128,64,0};
#include "../BootProgress.c"
volatile int native_owner_cache_stage;
volatile uint64_t native_ufs_block_reads, native_ufs_block_failures;
unsigned vm_page_free_count;
uint32_t memorystatus_available_pages;

static void panic_for_test(const char *format, ...)
{
    va_list args;
    va_start(args, format);
    boot_progress_panic(format, &args, 0xfffffff007123456, 9, 0x140);
    va_end(args);
}

int main(void)
{
    enum { W = 126, H = 840, PITCH = 132, GUARD = 32 };
    uint32_t *allocation = malloc((PITCH * H + 2 * GUARD) * sizeof(uint32_t));
    assert(allocation);
    for (unsigned i = 0; i < PITCH * H + 2 * GUARD; i++) allocation[i] = 0x12345678;
    boot_args args = { .virtBase = 0xfffffff007004000ULL, .physBase = 0xc0004000,
                      .memSize = 0x10000000, .Video = { (uintptr_t)(allocation + GUARD), 1, PITCH * 4, W, H, 32 } };
    early_boot_progress_init(&args);
    assert(boot_progress_active() && logo_visible);
    unsigned logo_at = GUARD + ((H - BOOT_LOGO_HEIGHT) / 2 + BOOT_LOGO_Y) * PITCH +
                       (W - BOOT_LOGO_WIDTH) / 2 + BOOT_LOGO_X;
    assert(allocation[logo_at] == 0xff000000 && allocation[logo_at + 1] == 0xff404040 &&
           allocation[logo_at + 2] == 0xff808080 && allocation[logo_at + 3] == 0xffffffff);
    for (unsigned i = 0; i < 5000; i++) boot_progress_putc((i % 41) ? 'X' : '\n');
    assert(allocation[logo_at + 3] == 0xffffffff);
    boot_progress_stage("wrap, CR\rLF\n and invalid bytes \1\377");
    for (unsigned i = 0; i < GUARD; i++) {
        assert(allocation[i] == 0x12345678);
        assert(allocation[GUARD + PITCH * H + i] == 0x12345678);
    }
    for (unsigned y = 0; y < H; y++)
        for (unsigned x = W; x < PITCH; x++) assert(allocation[GUARD + y * PITCH + x] == 0x12345678);
    assert(!geometry(UINTPTR_MAX - 3, W, H, PITCH * 4, 32));
    assert(!geometry(4, W, H, W * 4 - 4, 32));
    assert(!geometry(4, W, H, PITCH * 4, 16));
    assert(!geometry(4, W, 100000, PITCH * 4, 32));
    assert(!geometry(5, W, H, PITCH * 4, 32));
    args.Video.v_width += 1ULL << 32;
    early_boot_progress_init(&args);
    assert(!boot_progress_active() && framebuffer_pa == 0);
    args.Video.v_width = W;
    early_boot_progress_init(&args);

    uint64_t *tables = aligned_alloc(4096, 4 * 4096);
    assert(tables);
    memset(tables, 0, 4 * 4096);
    framebuffer_pa = 0x3ffff000;
    assert(early_boot_progress_map(tables, (uintptr_t)(tables + 512), (uintptr_t)(tables + 1536)));
    assert(tables[0] == ((uintptr_t)(tables + 512) | 3));
    assert(tables[1] == ((uintptr_t)(tables + 1024) | 3));
    assert(tables[512 + 511] == (0x3fe00000ULL | (1ULL << 54) | (1ULL << 53) | 0x605));
    assert(tables[1024] == (0x40000000ULL | (1ULL << 54) | (1ULL << 53) | 0x605));
    for (unsigned i = 1536; i < 2048; i++) assert(tables[i] == 0);
    // A repeated map uses the existing tables without consuming another page.
    assert(early_boot_progress_map(tables, (uintptr_t)(tables + 1536), (uintptr_t)(tables + 1536)));
    tables[1024] ^= 4;
    assert(!early_boot_progress_map(tables, (uintptr_t)(tables + 1536), (uintptr_t)(tables + 1536)));
    memset(tables, 0, 4 * 4096);
    assert(!early_boot_progress_map(tables, (uintptr_t)(tables + 512), (uintptr_t)(tables + 512)));
    assert(tables[0] == 0);
    framebuffer_pa = (1ULL << (64 - T0SZ_BOOT)) - 4096;
    assert(!early_boot_progress_map(tables, (uintptr_t)(tables + 512), (uintptr_t)(tables + 1536)));
    framebuffer_pa = 1ULL << (64 - T0SZ_BOOT);
    assert(!early_boot_progress_map(tables, (uintptr_t)(tables + 512), (uintptr_t)(tables + 1536)));
    assert(tables[0] == 0);
    armcpu_timer_interrupts = 7;
    boot_progress_start(); poll(NULL, NULL);
    assert(poll_count == 1 && armcpu_timer_interrupts == 7);
    boot_progress_root("root device wait begin", "IOMedia Content=Apple_HFS", 60);
    assert(root_sequence == 1 && root_value == 60);
    assert(!strcmp(root_stage, "root device wait begin"));
    assert(!strcmp(root_detail, "IOMedia Content=Apple_HFS"));
    native_owner_cache_stage = 3;
    vm_page_free_count = 1234; memorystatus_available_pages = 2345;
    native_ufs_block_reads = 5678; native_ufs_block_failures = 9;
    uint32_t root_line[LINE * PITCH];
    memcpy(root_line, (void *)(framebuffer + 3 * LINE * stride * 4), sizeof(root_line));
    unsigned saved_row = row, saved_column = column;
    poll(NULL, NULL);
    assert(!strcmp(storage_status, "free=1234 avail=2345 UFS=5678 err=9"));
    assert(!memcmp(root_line, (void *)(framebuffer + 3 * LINE * stride * 4), sizeof(root_line)));
    assert(row == saved_row && column == saved_column && native_ufs_block_reads == 5678);
    boot_progress_kernel_exception(0x96000010, 0xfffffff007345678, 0x12345000);
    assert(fault_valid && fault_esr == 0x96000010 && fault_far == 0x12345000);
    panic_for_test("Failed to mount %s: %u %llx %%", "root device", 60U, 0x123456789abcdef0ULL);
    assert(panic_state == 1 && busy);
    assert(!strcmp(boot_progress_panic_text, "Failed to mount root device: 60 123456789abcdef0 %"));
    assert(allocation[GUARD] == 0xffff4040);
    assert(allocation[GUARD + W / 3] == 0xff40ff40);
    assert(allocation[GUARD + 2 * W / 3] == 0xff4080ff);
    unsigned before_scheduled = scheduled, before_stages = stage_count;
    boot_progress_putc('X'); boot_progress_stage("must not overwrite panic");
    boot_progress_root("must not replace root state", NULL, 1); poll(NULL, NULL);
    assert(scheduled == before_scheduled && stage_count == before_stages && root_sequence == 1);
    assert(poll_count == 2 && armcpu_timer_interrupts == 7);
    uintptr_t before_framebuffer = framebuffer;
    boot_progress_bind(4, W, H, PITCH * 4, 32);
    assert(framebuffer == before_framebuffer);
    panic_for_test("nested failure %d", 123);
    assert(!strcmp(boot_progress_panic_text, "Failed to mount root device: 60 123456789abcdef0 %"));
    boot_progress_kernel_exception(0x96000004, 0xabcd, 0xdead);
    assert(fault_esr == 0x96000010); // The first fault remains available.
    early_boot_progress_init(&args);
    char long_message[3000];
    memset(long_message, 'P', sizeof(long_message) - 1); long_message[sizeof(long_message) - 1] = 0;
    for (unsigned i = 0; i < HISTORY + 3; i++) boot_progress_stage("history wraps within its fixed storage");
    panic_for_test("%s", long_message);
    assert(strlen(boot_progress_panic_text) == sizeof(boot_progress_panic_text) - 1 && panic_clipped);
    assert(allocation[GUARD] == 0xffff4040); // Long text never wraps over the panic banner.
    for (unsigned i = 0; i < GUARD; i++) {
        assert(allocation[i] == 0x12345678);
        assert(allocation[GUARD + PITCH * H + i] == 0x12345678);
    }
    for (unsigned y = 0; y < H; y++)
        for (unsigned x = W; x < PITCH; x++) assert(allocation[GUARD + y * PITCH + x] == 0x12345678);
    early_boot_progress_init(&args);
    boot_progress_process_stage(42, "launchd", "load_machfile");
    assert(strstr(stages[(stage_count - 1) % HISTORY], "pid=42 launchd load_machfile"));
    boot_progress_exit(43, "backboardd", 1, 2, 3);
    assert(strstr(stages[(stage_count - 1) % HISTORY], "exit pid=43 backboardd"));
    boot_progress_display_status("GOP display started", 1);
    for (unsigned i = 0; i < HISTORY + 1; i++) boot_progress_process_stage(44, "launchd", "exec");
    assert(strstr(exit_stage, "exit pid=43 backboardd"));
    assert(!strcmp(display_stage, "GOP display started") && display_value == 1);
    for (unsigned i = 0; i < 29; i++) poll(NULL, NULL);
    assert(logo_visible && allocation[logo_at + 3] == 0xffffffff);
    poll(NULL, NULL);
    assert(!logo_visible && !display_owned && !panic_state && poll_count == 30);
    assert(!strcmp(display_status, "DISPLAY GOP display started 1"));
    early_boot_progress_init(&args);
    assert(logo_visible && poll_count == 0);
    assert(boot_progress_display_handoff());
    boot_progress_display_failed();
    assert(!display_owned);
    for (unsigned i = 0; i < 30; i++) poll(NULL, NULL);
    assert(!logo_visible);
    early_boot_progress_init(&args);
    busy = 1;
    assert(!boot_progress_display_handoff());
    busy = 0;
    assert(boot_progress_display_handoff());
    uint32_t *snapshot = malloc(PITCH * H * sizeof(uint32_t));
    assert(snapshot);
    memcpy(snapshot, allocation + GUARD, PITCH * H * sizeof(uint32_t));
    boot_progress_stage("must preserve system frame");
    boot_progress_root("frame ownership", "preserve pixels", 1);
    for (unsigned i = 0; i < 31; i++) poll(NULL, NULL);
    assert(!memcmp(snapshot, allocation + GUARD, PITCH * H * sizeof(uint32_t)));
    free(snapshot);
    panic_for_test("panic after system display handoff");
    boot_progress_display_failed();
    assert(allocation[GUARD] == 0xffff4040 && !boot_progress_display_handoff());
    early_boot_progress_suspend();
    assert(!boot_progress_active());
    free(tables); free(allocation);
    puts("PASS: framebuffer/map bounds, root state, panic formatting, truncation, first-fault retention and frozen observer");
    return 0;
}
