#!/usr/bin/env python3
"""Generate a minimal two-instruction MIPS homebrew ELF for toolchain baselines."""

import argparse
import os
import struct


BASE = 0x08804000


def build_elf():
    text = struct.pack("<II", 0x03E00008, 0x00000000)  # jr ra; nop
    module_info = bytearray(52)
    module_info[4:12] = b"homebrew"
    strings = b"\0.text\0.rodata.sceModuleInfo\0.shstrtab\0"
    text_offset = 0x100
    module_offset = 0x110
    strings_offset = module_offset + len(module_info)
    section_offset = (strings_offset + len(strings) + 3) & ~3

    ident = b"\x7fELF\x01\x01\x01" + b"\0" * 9
    header = ident + struct.pack(
        "<HHIIIIIHHHHHH",
        0xFFA0, 8, 1, 0, 52, section_offset, 0,
        52, 32, 1, 40, 4, 3,
    )
    program = struct.pack(
        "<IIIIIIII",
        1, text_offset, 0, 0,
        module_offset + len(module_info) - text_offset,
        module_offset + len(module_info) - text_offset,
        5, 0x1000,
    )
    sections = bytearray(40)
    sections.extend(
        struct.pack(
            "<IIIIIIIIII",
            1, 1, 6, 0, text_offset, len(text), 0, 0, 4, 0,
        )
    )
    sections.extend(
        struct.pack(
            "<IIIIIIIIII",
            7, 1, 2, 0x10, module_offset, len(module_info), 0, 0, 4, 0,
        )
    )
    sections.extend(
        struct.pack(
            "<IIIIIIIIII",
            29, 3, 0, 0, strings_offset, len(strings), 0, 0, 1, 0,
        )
    )
    output = bytearray(section_offset + len(sections))
    output[:len(header)] = header
    output[52:52 + len(program)] = program
    output[text_offset:text_offset + len(text)] = text
    output[module_offset:module_offset + len(module_info)] = module_info
    output[strings_offset:strings_offset + len(strings)] = strings
    output[section_offset:] = sections
    return bytes(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    args = parser.parse_args(argv)
    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "wb") as stream:
        stream.write(build_elf())
    print(
        f"wrote {output}: {os.path.getsize(output)} bytes, "
        f"relocatable entry 0x00000000 (load 0x{BASE:08x})"
    )


if __name__ == "__main__":
    main()
