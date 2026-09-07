ENTRY(_rom_entry)

MEMORY
{
  rom   (rx)  : ORIGIN = 0x08000000, LENGTH = 32M
  ewram (rwx) : ORIGIN = 0x02000000, LENGTH = 256K
  iwram (rwx) : ORIGIN = 0x03000000, LENGTH = 32K
}

SECTIONS
{
  .text :
  {
    KEEP(*(.gba_header))
    *(.text.startup)
    *(.text*)
    *(.rodata*)
    *(.ARM.extab*)
    *(.ARM.exidx*)
    . = ALIGN(4);
  } > rom

  .data :
  {
    __data_start = .;
    *(.data*)
    . = ALIGN(4);
    __data_end = .;
  } > ewram AT> rom
  __data_load = LOADADDR(.data);

  .iwram :
  {
    __iwram_start = .;
    *(.iwram*)
    . = ALIGN(4);
    __iwram_end = .;
  } > iwram AT> rom
  __iwram_load = LOADADDR(.iwram);

  .bss (NOLOAD) :
  {
    __bss_start = .;
    *(.bss*)
    *(COMMON)
    . = ALIGN(4);
    __bss_end = .;
  } > ewram

  /DISCARD/ :
  {
    *(.comment*)
    *(.note*)
  }
}
