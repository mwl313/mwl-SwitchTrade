    .syntax unified
    .cpu arm7tdmi
    .arm

    .section .gba_header, "ax", %progbits
    .global _rom_entry
_rom_entry:
    b _start
    .space 188

    .section .text.startup, "ax", %progbits
    .global _start
    .type _start, %function
_start:
    ldr sp, =0x03007f00

    ldr r0, =__data_load
    ldr r1, =__data_start
    ldr r2, =__data_end
1:
    cmp r1, r2
    ldrlo r3, [r0], #4
    strlo r3, [r1], #4
    blo 1b

    ldr r0, =__iwram_load
    ldr r1, =__iwram_start
    ldr r2, =__iwram_end
2:
    cmp r1, r2
    ldrlo r3, [r0], #4
    strlo r3, [r1], #4
    blo 2b

    mov r0, #0
    ldr r1, =__bss_start
    ldr r2, =__bss_end
3:
    cmp r1, r2
    strlo r0, [r1], #4
    blo 3b

    bl main
4:
    b 4b
    .size _start, . - _start
