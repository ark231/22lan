#!/usr/bin/env python3
import base64
import sys
import re


def encode(src: str) -> bytes:
    return base64.b32encode(src.encode("utf-8") + b"\0")


def main():
    print(encode(re.sub(r"(?<!\\)\\n", "\n", sys.argv[1])))


if __name__ == "__main__":
    main()
