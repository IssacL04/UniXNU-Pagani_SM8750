// SPDX-License-Identifier: BSD-2-Clause-Patent
// Cold boot only. The 13T profile keeps cpus=1 until SMP is separately qualified.
.text
.p2align 2
.globl _early_boot_progress_entry
_early_boot_progress_entry:
    msr daifset, #15
    mov x20, x0
    adrp x9, _early_boot_args_pa@PAGE
    str x0, [x9, _early_boot_args_pa@PAGEOFF]
    adrp x9, _early_boot_progress_vectors@PAGE
    add x9, x9, _early_boot_progress_vectors@PAGEOFF
    msr vbar_el1, x9
    isb
    adrp x9, _early_boot_progress_stack@PAGE
    add x9, x9, _early_boot_progress_stack@PAGEOFF
    add x9, x9, #4096
    mov sp, x9
    bl _early_boot_progress_init
    mov x0, x20
    b _start_first_cpu

.p2align 11
.globl _early_boot_progress_vectors
_early_boot_progress_vectors:
.rept 16
    b Lfatal
    .space 124
.endr

Lfatal:
    msr daifset, #15
    mrs x1, esr_el1
    mrs x2, elr_el1
    mrs x3, far_el1
    mrs x4, spsr_el1
    adrp x9, _early_boot_args_pa@PAGE
    ldr x0, [x9, _early_boot_args_pa@PAGEOFF]
    adrp x9, _early_boot_stage@PAGE
    ldr x5, [x9, _early_boot_stage@PAGEOFF]
    mrs x10, sctlr_el1
    tbz x10, #0, Lphysical
    adr x9, Lfatal
    tbz x9, #63, Lphysical
    // Restore the bootstrap identity map before leaving the virtual address space.
    adrp x9, _early_boot_phys_base@PAGE
    ldr x11, [x9, _early_boot_phys_base@PAGEOFF]
    adrp x9, _early_boot_virt_base@PAGE
    ldr x12, [x9, _early_boot_virt_base@PAGEOFF]
    sub x11, x11, x12
    adrp x9, _bootstrap_pagetables@PAGE
    add x9, x9, _bootstrap_pagetables@PAGEOFF
    add x9, x9, x11
    msr ttbr0_el1, x9
    isb
    tlbi vmalle1
    dsb sy
    isb
    adr x9, Lphysical
    add x9, x9, x11
    br x9
Lphysical:
    mrs x10, sctlr_el1
    bic x10, x10, #1
    bic x10, x10, #4
    bic x10, x10, #0x1000
    dsb sy
    msr sctlr_el1, x10
    isb
    // Fatal path never resumes: writes bypass cached kernel state from here on.
    adrp x9, _early_boot_progress_vectors@PAGE
    add x9, x9, _early_boot_progress_vectors@PAGEOFF
    msr vbar_el1, x9
    adrp x9, _early_boot_progress_stack@PAGE
    add x9, x9, _early_boot_progress_stack@PAGEOFF
    add x9, x9, #4096
    mov sp, x9
    bl _early_boot_progress_fatal
1:  wfe
    b 1b

.globl _early_boot_progress_vectors_done
_early_boot_progress_vectors_done:
    adrp x9, _ExceptionVectorsBase@PAGE
    add x9, x9, _ExceptionVectorsBase@PAGEOFF
    msr vbar_el1, x9
    isb
    ret

.globl _early_boot_progress_stack
.zerofill __DATA,__bss,_early_boot_progress_stack,4096,12
