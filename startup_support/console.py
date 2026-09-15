# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys

from colorama import Fore, Style


_ASCII_FALLBACKS = {
    chr(0x2014): "-",
    chr(0x2013): "-",
    chr(0x2192): "->",
    chr(0x2190): "<-",
    chr(0x2018): "'",
    chr(0x2019): "'",
    chr(0x201C): '"',
    chr(0x201D): '"',
    chr(0x2026): "...",
    chr(0x2713): "OK",
    chr(0x2717): "X",
    chr(0x2022): "*",
}


def _safe(text: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        for glyph, fallback in _ASCII_FALLBACKS.items():
            text = text.replace(glyph, fallback)
        text = text.encode(encoding, errors="replace").decode(encoding)
    return text


def print_header(text: str) -> None:
    text = _safe(text)
    separator = "=" * 70
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{separator}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}  {text}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}{separator}{Style.RESET_ALL}\n")


def print_success(text: str) -> None:
    print(f"{Fore.GREEN}[OK]{Style.RESET_ALL} {_safe(text)}")


def print_error(text: str) -> None:
    print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {_safe(text)}")


def print_info(text: str) -> None:
    print(f"{Fore.BLUE}[INFO]{Style.RESET_ALL} {_safe(text)}")


def print_warning(text: str) -> None:
    print(f"{Fore.YELLOW}[!]{Style.RESET_ALL} {_safe(text)}")
