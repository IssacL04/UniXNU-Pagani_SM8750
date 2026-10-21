// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <stdint.h>
#include <stddef.h>
#ifndef BOOT_PROGRESS_TEST
#include <pexpert/pexpert.h>
#include <pexpert/arm64/boot.h>
#include <machine/machine_routines.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <kern/boot_progress.h>
#include <kern/early_boot_progress.h>
#include <arm64/proc_reg.h>
_Static_assert(ARM_PGBYTES == 4096 && T0SZ_BOOT == 25 && CACHE_ATTRINDX_WRITECOMB == 1,
               "Early framebuffer map requires the native 4 KiB bootstrap ABI");
#endif
#include <DiagFont.h>

_Static_assert(offsetof(boot_args, Video) == 0x28, "DarwinBoot video ABI");
_Static_assert(offsetof(boot_args, physBase) == 0x10, "DarwinBoot memory ABI");

extern volatile uint32_t armdt_platform_configured, armcpu_registered, armcpu_gic_ready;
extern volatile uint64_t armcpu_timer_interrupts;
extern volatile uint32_t armcpu_gic_boot[8];
extern void early_boot_progress_vectors_done(void);

// These values are also read by the stackless fatal exception entry.
uint64_t early_boot_args_pa, early_boot_phys_base, early_boot_virt_base;
uint64_t early_boot_stage;
static const uint64_t font[] = GLYPH_FONT;
static uintptr_t framebuffer, framebuffer_pa;
static unsigned width, height, stride, column, row = 4;
static uint64_t poll_count;
static thread_call_t poll_call;
static int busy; // shortcut: single-core observer, add SMP synchronization before enabling more CPUs.
enum { SCALE = 3, CELL = 6 * SCALE, LINE = 14 * SCALE, LOG_TOP = 4 };

static void barrier(void)
{
#ifndef BOOT_PROGRESS_TEST
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}

static uint64_t irq_save(void)
{
    uint64_t flags = 0;
#ifndef BOOT_PROGRESS_TEST
    __asm__ volatile("mrs %0, daif; msr daifset, #15" : "=r"(flags) :: "memory");
#endif
    return flags;
}

static void irq_restore(uint64_t flags)
{
#ifndef BOOT_PROGRESS_TEST
    __asm__ volatile("msr daif, %0" :: "r"(flags) : "memory");
#else
    (void)flags;
#endif
}

static uint64_t frequency(void)
{
    uint64_t value = 19200000;
#ifndef BOOT_PROGRESS_TEST
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(value));
#endif
    return value;
}

static int geometry(uintptr_t base, uint64_t w, uint64_t h, uint64_t pitch, uint64_t depth)
{
    return base != 0 && (base & 3) == 0 && (depth & 255) == 32 &&
        w >= CELL && w <= 8192 && h >= (LOG_TOP + 1) * LINE && h <= 8192 &&
        pitch >= w * 4 && pitch <= 32768 && (pitch & 3) == 0 &&
        pitch * h <= 64 * 1024 * 1024 && base <= UINTPTR_MAX - pitch * h;
}

static void clear_line(unsigned y)
{
    if (!framebuffer || y + LINE > height) return;
    for (unsigned dy = 0; dy < LINE; dy++) {
        volatile uint32_t *pixels = (volatile uint32_t *)framebuffer + (y + dy) * stride;
        for (unsigned x = 0; x < width; x++) pixels[x] = 0xff000000;
    }
}

static void glyph(unsigned char c, unsigned x, unsigned y, uint32_t color)
{
    if (!framebuffer || x + CELL > width || y + LINE > height) return;
    if (c < 32 || c > 126) c = '?';
    uint64_t bits = font[c - 32];
    for (unsigned gy = 0; gy < 12; gy++) {
        unsigned scan = (unsigned)((gy < 6 ? bits >> 32 : bits & 0xffffffff) >> ((gy % 6) * 5));
        for (unsigned gx = 0; gx < 6; gx++) {
            uint32_t pixel = gx < 5 && ((scan >> gx) & 1) ? color : 0xff000000;
            for (unsigned dy = 0; dy < SCALE; dy++) {
                volatile uint32_t *line = (volatile uint32_t *)framebuffer + (y + gy * SCALE + dy) * stride + x + gx * SCALE;
                for (unsigned dx = 0; dx < SCALE; dx++) line[dx] = pixel;
            }
        }
    }
}

static void putc_raw(char c)
{
    if (!framebuffer) return;
    if (c == '\r') { column = 0; return; }
    if (c == '\n' || (column + 1) * CELL > width) {
        column = 0;
        row++;
        if ((row + 1) * LINE > height) row = LOG_TOP;
        clear_line(row * LINE);
        if (c == '\n') return;
    }
    glyph((unsigned char)c, column++ * CELL, row * LINE, 0xffffffff);
}

static void text_raw(const char *s)
{
    while (*s) putc_raw(*s++);
}

static void hex_raw(uint64_t n)
{
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned digit = (unsigned)(n >> shift) & 15;
        putc_raw((char)(digit < 10 ? '0' + digit : 'a' + digit - 10));
    }
}

static void value_raw(const char *name, uint64_t n)
{
    text_raw(name); text_raw(" 0x"); hex_raw(n); putc_raw('\n');
}

void boot_progress_bind(uintptr_t base, unsigned w, unsigned h, unsigned pitch, unsigned depth)
{
    if (!geometry(base, w, h, pitch, depth)) return;
    framebuffer = base; width = w; height = h; stride = pitch / 4;
    if ((row + 1) * LINE > height) row = LOG_TOP;
    if ((column + 1) * CELL > width) column = 0;
}

int boot_progress_active(void) { return framebuffer != 0; }

void boot_progress_putc(char c)
{
    uint64_t flags = irq_save();
    if (!busy) { busy = 1; putc_raw(c); barrier(); busy = 0; }
    irq_restore(flags);
}

void boot_progress_stage(const char *s)
{
    uint64_t flags = irq_save();
    if (!busy) {
        busy = 1;
        if (column) putc_raw('\n');
        text_raw("[XNU] "); text_raw(s); putc_raw('\n'); barrier();
        busy = 0;
    }
    irq_restore(flags);
}

// No kernel services, stack protector, SIMD, or relocated pointers on this path.
void early_boot_progress_init(boot_args *args)
{
    early_boot_args_pa = (uintptr_t)args;
    early_boot_phys_base = args->physBase;
    early_boot_virt_base = args->virtBase;
    early_boot_stage = 1;
    framebuffer = 0; column = 0; row = LOG_TOP; busy = 0;
    boot_progress_bind(args->Video.v_baseAddr, args->Video.v_width, args->Video.v_height,
                       args->Video.v_rowBytes, args->Video.v_depth);
    framebuffer_pa = framebuffer;
    for (unsigned y = 0; y + LINE <= height; y += LINE) clear_line(y);
    unsigned saved = row;
    row = 0; text_raw("OnePlus 13T / source XNU"); row = saved; column = 0;
    boot_progress_stage("S1: XNU entry, MMU off");
    value_raw("args PA", (uintptr_t)args);
    value_raw("RAM PA", args->physBase);
    value_raw("RAM VA", args->virtBase);
    value_raw("RAM bytes", args->memSize);
    value_raw("CNTFRQ Hz", frequency());
    barrier();
}

// Called with MMU off. Extend the existing TTBR0 identity map only over GOP.
int early_boot_progress_map(uint64_t *l1, uintptr_t free_page, uintptr_t end)
{
    const uint64_t block = 1ULL << 21, table_mask = 0x0000fffffffff000ULL;
    if (!framebuffer) return 1;
    uint64_t first = framebuffer_pa & ~(block - 1);
    uint64_t limit = (framebuffer_pa + (uint64_t)stride * 4 * height + block - 1) & ~(block - 1);
    // T0SZ=25, 4 KiB pages. Reject an incompatible target instead of aliasing its L1.
    if (limit > (1ULL << 39) || (free_page & 4095) || (end & 4095)) return 0;
    for (uint64_t pa = first; pa < limit; pa += block) {
        uint64_t *slot = &l1[(pa >> 30) & 511];
        if (*slot == 0) {
            if (free_page > end || end - free_page < 4096) return 0;
            volatile uint64_t *page = (volatile uint64_t *)free_page;
            for (unsigned i = 0; i < 512; i++) page[i] = 0;
            *slot = free_page | 3;
            free_page += 4096;
        }
        if ((*slot & 3) != 3) return 0;
        uint64_t *l2 = (uint64_t *)(uintptr_t)(*slot & table_mask);
        // Attr1 = normal non-cacheable in XNU's MAIR, outer-shareable, AF, EL1 RW, XN.
        uint64_t mapping = pa | (1ULL << 54) | (1ULL << 53) | 0x605;
        if (l2[(pa >> 21) & 511] != 0 && l2[(pa >> 21) & 511] != mapping) return 0;
        l2[(pa >> 21) & 511] = mapping;
    }
    barrier();
    early_boot_stage = 2;
    boot_progress_stage("S2: bootstrap maps ready");
    return 1;
}

void early_boot_progress_mmu_on(void) { early_boot_stage = 3; boot_progress_stage("S3: MMU enabled"); }
void early_boot_progress_arm_init(void) { early_boot_stage = 4; boot_progress_stage("S4: arm_init entered"); }
void early_boot_progress_suspend(void) { early_boot_stage = 0x50; barrier(); framebuffer = 0; }

void early_boot_progress_vm_ready(void)
{
    uintptr_t mapped = framebuffer_pa ? ml_io_map_wcomb(framebuffer_pa, (uint64_t)stride * 4 * height) : 0;
    if (mapped) framebuffer = mapped;
    early_boot_progress_vectors_done();
    early_boot_stage = 6;
    boot_progress_stage("S6: kernel VM and exception vectors ready");
}

void boot_progress_init(void)
{
    early_boot_stage = 5;
    boot_progress_stage("S5: PE_init_platform ready");
    value_raw("kernel timebase Hz", gPEClockFrequencyInfo.timebase_frequency_hz);
    barrier();
}

// The assembly fatal path re-enters with physical addresses and MMU/cache off.
void early_boot_progress_fatal(boot_args *args, uint64_t esr, uint64_t elr, uint64_t far, uint64_t spsr, uint64_t stage)
{
    early_boot_progress_init(args);
    boot_progress_stage("EARLY EXCEPTION - stopped");
    value_raw("last checkpoint", stage);
    value_raw("ESR_EL1", esr); value_raw("ELR_EL1", elr);
    value_raw("FAR_EL1", far); value_raw("SPSR_EL1", spsr);
    barrier();
    for (;;) {
#ifndef BOOT_PROGRESS_TEST
        __asm__ volatile("wfe");
#else
        break;
#endif
    }
}

void boot_progress_kernel_exception(uint64_t esr, uint64_t elr, uint64_t far)
{
    uint64_t flags = irq_save();
    boot_progress_stage("kernel exception");
    value_raw("ESR_EL1", esr); value_raw("ELR_EL1", elr); value_raw("FAR_EL1", far);
    barrier(); irq_restore(flags);
}

static void poll(void *unused0, void *unused1)
{
    (void)unused0; (void)unused1;
    uint64_t flags = irq_save();
    if (framebuffer && !busy) {
        busy = 1;
        unsigned saved_row = row, saved_column = column;
        row = 1; column = 0; clear_line(LINE);
        text_raw("poll "); hex_raw(++poll_count); text_raw(" timer "); hex_raw(armcpu_timer_interrupts);
        row = 2; column = 0; clear_line(2 * LINE);
        text_raw("DT/CPU/GIC "); putc_raw('0' + !!armdt_platform_configured);
        putc_raw('/'); putc_raw('0' + !!armcpu_registered); putc_raw('/'); putc_raw('0' + !!armcpu_gic_ready);
        text_raw(" PPI-enable "); hex_raw(armcpu_gic_boot[1]);
        row = saved_row; column = saved_column; barrier(); busy = 0;
    }
    irq_restore(flags);
    uint64_t deadline;
    clock_interval_to_deadline(1, NSEC_PER_SEC, &deadline);
    thread_call_enter_delayed(poll_call, deadline);
}

void boot_progress_start(void)
{
    poll_call = thread_call_allocate_with_options(poll, NULL, THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE);
    if (!poll_call) { boot_progress_stage("timer observer allocation failed"); return; }
    boot_progress_stage("timer observer scheduled; counters are hexadecimal");
    thread_call_enter(poll_call);
}

// Existing later-stage hooks stay observational; this profile has no userspace yet.
void boot_progress_irq(uint64_t pc, uint64_t psr, uint64_t sp) { (void)pc; (void)psr; (void)sp; }
void boot_progress_poll(void) {}
void boot_progress_user_breakpoint(void *state, unsigned esr) { (void)state; (void)esr; }
void boot_progress_user_abort(void *state, unsigned esr, uint64_t far) { (void)state; (void)esr; (void)far; }
void boot_progress_critical_exit(int pid, char *s, unsigned long n) { (void)pid; (void)s; (void)n; }
void boot_progress_process_stage(int pid, const char *name, const char *stage) { (void)pid; (void)name; boot_progress_stage(stage); }
void boot_progress_exit(int pid, const char *name, int status, unsigned ns, uint64_t code) { (void)pid; (void)name; (void)status; (void)ns; (void)code; }
