// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>
#ifndef BOOT_PROGRESS_TEST
#include <pexpert/pexpert.h>
#include <pexpert/arm64/boot.h>
#include <machine/machine_routines.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <kern/boot_progress.h>
#include <kern/early_boot_progress.h>
#include <arm64/proc_reg.h>
_Static_assert(ARM_PGBYTES == 4096 && (T0SZ_BOOT == 25 || T0SZ_BOOT == 26) && CACHE_ATTRINDX_WRITECOMB == 1,
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
enum { HISTORY = 8, STAGE_BYTES = 80 };
static char stages[HISTORY][STAGE_BYTES], root_stage[STAGE_BYTES], root_detail[192];
static unsigned stage_count, panic_state, panic_limit, panic_clipped;
static uint64_t root_sequence, root_value, root_tick, fault_esr, fault_pc, fault_far, fault_psr;
static int fault_valid;
char boot_progress_panic_text[2048];
extern int vsnprintf(char *, size_t, const char *, va_list);

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

static uint64_t counter(void)
{
    uint64_t value = 0;
#ifndef BOOT_PROGRESS_TEST
    __asm__ volatile("mrs %0, cntvct_el0" : "=r"(value));
#endif
    return value;
}

static void copy_line(char *to, size_t size, const char *from)
{
    size_t i = 0;
    if (from) for (; i + 1 < size && from[i]; i++)
        to[i] = from[i] >= 32 && from[i] <= 126 ? from[i] : ' ';
    to[i] = 0;
}

static void record_stage(const char *s)
{
    copy_line(stages[stage_count % HISTORY], STAGE_BYTES, s);
    stage_count++;
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
    if (panic_state && row >= panic_limit) { panic_clipped = 1; return; }
    if (c == '\t') c = ' ';
    if (c == '\r') { column = 0; return; }
    if (c == '\n' || (column + 1) * CELL > width) {
        column = 0;
        row++;
        if (panic_state && row >= panic_limit) { panic_clipped = 1; return; }
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
    if (panic_state) return;
    if (!geometry(base, w, h, pitch, depth)) return;
    framebuffer = base; width = w; height = h; stride = pitch / 4;
    if ((row + 1) * LINE > height) row = LOG_TOP;
    if ((column + 1) * CELL > width) column = 0;
}

int boot_progress_active(void) { return framebuffer != 0; }

void boot_progress_putc(char c)
{
    uint64_t flags = irq_save();
    if (!busy && !panic_state) { busy = 1; putc_raw(c); barrier(); busy = 0; }
    irq_restore(flags);
}

void boot_progress_stage(const char *s)
{
    uint64_t flags = irq_save();
    if (!busy && !panic_state) {
        busy = 1;
        record_stage(s);
        if (column) putc_raw('\n');
        text_raw("[XNU] "); text_raw(s); putc_raw('\n'); barrier();
        busy = 0;
    }
    irq_restore(flags);
}

void boot_progress_root(const char *stage, const char *detail, uint64_t value)
{
    uint64_t flags = irq_save();
    if (!panic_state && !busy) {
        busy = 1;
        copy_line(root_stage, sizeof(root_stage), stage);
        copy_line(root_detail, sizeof(root_detail), detail);
        root_value = value; root_tick = counter(); root_sequence++;
        record_stage(stage);
        char *entry = stages[(stage_count - 1) % HISTORY];
        unsigned n = 0;
        while (entry[n]) n++;
        if (root_detail[0] && n + 3 < STAGE_BYTES) {
            entry[n++] = ':'; entry[n++] = ' ';
            copy_line(entry + n, STAGE_BYTES - n, root_detail);
        }
        if (column) putc_raw('\n');
        text_raw("[ROOT] "); text_raw(root_stage); text_raw(" value=0x"); hex_raw(value); putc_raw('\n');
        if (root_detail[0]) { text_raw(root_detail); putc_raw('\n'); }
        unsigned saved_row = row, saved_column = column;
        row = 3; column = 0; clear_line(3 * LINE);
        text_raw("ROOT ");
        for (unsigned i = 0; root_stage[i] && column < width / CELL; i++) putc_raw(root_stage[i]);
        row = saved_row; column = saved_column;
        barrier(); busy = 0;
    }
    irq_restore(flags);
}

static void panic_halt(void)
{
    barrier();
#ifndef BOOT_PROGRESS_TEST
    for (;;) __asm__ volatile("wfe");
#endif
}

static void panic_open(const char *title)
{
    panic_state = 1; busy = 1; panic_clipped = 0;
    panic_limit = height / LINE - 2;
    for (unsigned y = 0; y + LINE <= height; y += LINE) clear_line(y);
    for (unsigned y = 0; y < 12; y++) {
        volatile uint32_t *pixels = (volatile uint32_t *)framebuffer + y * stride;
        for (unsigned x = 0; x < width; x++)
            pixels[x] = x < width / 3 ? 0xffff4040 : x < 2 * width / 3 ? 0xff40ff40 : 0xff4080ff;
    }
    row = 1; column = 0; text_raw(title); putc_raw('\n');
}

static void panic_footer(const char *status)
{
    unsigned clipped = panic_clipped;
    panic_limit = height / LINE;
    row = panic_limit - 2; column = 0; clear_line(row * LINE); clear_line((row + 1) * LINE);
    text_raw(clipped ? "SCREEN TEXT CLIPPED\n" : "\n");
    text_raw(status); barrier();
}

void boot_progress_panic(const char *format, va_list *args, unsigned long caller,
                         unsigned reason, uint64_t options)
{
    if (!framebuffer) return;
    uint64_t flags = irq_save();
    if (panic_state) {
        panic_footer("NESTED PANIC: first message preserved"); panic_halt(); return;
    }
    uint64_t sp = 0, fp = 0, mpidr = 0, sctlr = 0, tcr = 0, ttbr1 = 0;
#ifndef BOOT_PROGRESS_TEST
    __asm__ volatile("mov %0, sp" : "=r"(sp));
    __asm__ volatile("mov %0, x29" : "=r"(fp));
    __asm__ volatile("mrs %0, mpidr_el1" : "=r"(mpidr));
    __asm__ volatile("mrs %0, sctlr_el1" : "=r"(sctlr));
    __asm__ volatile("mrs %0, tcr_el1" : "=r"(tcr));
    __asm__ volatile("mrs %0, ttbr1_el1" : "=r"(ttbr1));
#endif
    panic_open("OnePlus 13T / XNU PANIC");
    text_raw("panic entry reached; values below are hexadecimal\n");
    value_raw("caller", caller); value_raw("MPIDR", mpidr);
    text_raw("last stage: "); text_raw(stage_count ? stages[(stage_count - 1) % HISTORY] : "none"); putc_raw('\n');
    text_raw("root: "); text_raw(root_sequence ? root_stage : "not entered"); putc_raw('\n');
    if (root_sequence) {
        value_raw("root seq", root_sequence); value_raw("root value", root_value);
        uint64_t hz = frequency();
        value_raw("root stage age (seconds)", hz ? (counter() - root_tick) / hz : 0);
    }
    unsigned message_row = row;
    text_raw("MESSAGE (formatting...)\n"); barrier();
    if (format && args) {
        va_list copy;
        va_copy(copy, *args);
        int n = vsnprintf(boot_progress_panic_text, sizeof(boot_progress_panic_text), format, copy);
        va_end(copy);
        if (n < 0) copy_line(boot_progress_panic_text, sizeof(boot_progress_panic_text), "<panic formatting failed>");
        if (n >= (int)sizeof(boot_progress_panic_text)) panic_clipped = 1;
    } else {
        copy_line(boot_progress_panic_text, sizeof(boot_progress_panic_text), format ? format : "<no panic format>");
    }
    for (unsigned r = message_row; r < row && r < panic_limit; r++) clear_line(r * LINE);
    row = message_row; column = 0; text_raw("MESSAGE\n");
    text_raw(boot_progress_panic_text); putc_raw('\n');
    text_raw("PANIC HANDLER STATE\n");
    text_raw("SP "); hex_raw(sp); text_raw(" FP "); hex_raw(fp); putc_raw('\n');
    text_raw("DAIF "); hex_raw(flags); text_raw(" reason "); hex_raw(reason); putc_raw('\n');
    value_raw("options", options); value_raw("SCTLR_EL1", sctlr);
    value_raw("TCR_EL1", tcr); value_raw("TTBR1_EL1", ttbr1);
    if (fault_valid) {
        text_raw("RECORDED KERNEL EXCEPTION\n");
        value_raw("ESR_EL1", fault_esr); value_raw("ELR_EL1", fault_pc);
        value_raw("FAR_EL1", fault_far); value_raw("SPSR_EL1", fault_psr);
    } else text_raw("No fatal exception recorded before this panic\n");
    text_raw("poll "); hex_raw(poll_count); text_raw(" timer "); hex_raw(armcpu_timer_interrupts); putc_raw('\n');
    text_raw("RECENT STAGES (oldest first)\n");
    unsigned count = stage_count < HISTORY ? stage_count : HISTORY;
    for (unsigned i = stage_count - count; i < stage_count; i++) {
        text_raw(stages[i % HISTORY]); putc_raw('\n');
    }
    panic_footer("HALTED: no software reboot"); panic_halt();
}

// No kernel services, stack protector, SIMD, or relocated pointers on this path.
void early_boot_progress_init(boot_args *args)
{
    early_boot_args_pa = (uintptr_t)args;
    early_boot_phys_base = args->physBase;
    early_boot_virt_base = args->virtBase;
    early_boot_stage = 1;
    panic_state = 0; stage_count = 0; root_sequence = 0; fault_valid = 0;
    boot_progress_panic_text[0] = 0;
    framebuffer = 0; column = 0; row = LOG_TOP; busy = 0;
    framebuffer_pa = 0;
    if (!geometry(args->Video.v_baseAddr, args->Video.v_width, args->Video.v_height,
                  args->Video.v_rowBytes, args->Video.v_depth)) return;
    boot_progress_bind(args->Video.v_baseAddr, (unsigned)args->Video.v_width, (unsigned)args->Video.v_height,
                       (unsigned)args->Video.v_rowBytes, (unsigned)args->Video.v_depth);
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
    // The kernel selects a full or half L1 table; never alias addresses beyond it.
    if (limit > (1ULL << (64 - T0SZ_BOOT)) || (free_page & 4095) || (end & 4095)) return 0;
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
    if (framebuffer) panic_open("OnePlus 13T / EARLY EXCEPTION");
    value_raw("last checkpoint", stage);
    value_raw("ESR_EL1", esr); value_raw("ELR_EL1", elr);
    value_raw("FAR_EL1", far); value_raw("SPSR_EL1", spsr);
    if (framebuffer) panic_footer("HALTED: no software reboot");
    panic_halt();
}

void boot_progress_kernel_exception(uint64_t esr, uint64_t elr, uint64_t far)
{
    uint64_t flags = irq_save();
    if (panic_state) {
        panic_limit = height / LINE;
        row = panic_limit - 2; column = 0; clear_line(row * LINE); clear_line((row + 1) * LINE);
        text_raw("NESTED EXCEPTION ESR "); hex_raw(esr); putc_raw('\n');
        text_raw("ELR "); hex_raw(elr); text_raw(" FAR "); hex_raw(far);
        panic_halt(); return;
    }
    fault_valid = 1; fault_esr = esr; fault_pc = elr; fault_far = far;
#ifndef BOOT_PROGRESS_TEST
    __asm__ volatile("mrs %0, spsr_el1" : "=r"(fault_psr));
#endif
    boot_progress_stage("kernel exception");
    value_raw("ESR_EL1", esr); value_raw("ELR_EL1", elr); value_raw("FAR_EL1", far);
    barrier(); irq_restore(flags);
}

static void poll(void *unused0, void *unused1)
{
    (void)unused0; (void)unused1;
    if (panic_state) return;
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
