#!/usr/bin/env python3
import argparse
from lark.visitors import Transformer, Discard, v_args
from lark.lexer import Token
from lark.tree import Tree
from lark.lark import Lark
import base64
import sys
from pathlib import Path


class Label:
    def __init__(self, lid: int):
        self.name = f"lan22_l{lid:b}"
        self.lid = lid

    def __str__(self) -> str:
        return f"{self.name}:"


class ParseError(Exception):
    def __init__(self, message: str, linenum: int):
        super().__init__(message)
        self.linenum = linenum


GOTO = "__GOTO__"


class Function:
    def __init__(self, name="", rettype="void", fid=None):
        self.name: str = name
        self.steps: list[str] = []
        self.labels: list[Label] = []
        self.rettype = rettype
        self.fid = fid
        if fid is not None:
            self.add_fid(fid)

    def add_step(self, step: str):
        self.steps.append(step)

    def add_label(self, label: Label):
        self.labels.append(label)

    def add_fid(self, fid: int):
        self.name = f"lan22_f{fid:b}"
        self.fid = fid

    def __str__(self) -> str:
        result = ""
        result += f"{self.rettype} {self.name}(){{\n"
        # if self.fid is not None:
        #     result += "    std::unordered_map<std::uint64_t,void*> ltable;\n"
        #     for label in self.labels:
        #         result += f"    ltable[{label.lid}]=&&{label.name};\n"
        for step in self.steps:
            if step == GOTO:
                for label in self.labels:
                    result += f"    if(r0 == {label.lid}){{goto {label.name};}}\n"
            else:
                result += f"    {step}\n"
        result += "}"
        return result


class Stack:
    _value: int

    def __init__(self):
        self._value = 0

    def push1(self, value: int) -> None:
        self._value <<= 1
        self._value |= value

    def pop8(self) -> int:
        result = self._value & 0b1111_1111
        self._value >>= 8
        return result

    def pop64(self) -> int:
        result = self._value & 0xFFFF_FFFF_FFFF_FFFF
        self._value >>= 64
        return result


class NyulanGenerator(Transformer):
    initial_s1: list[int]
    compile_time_stack: Stack
    functions: list[Function]

    def __repr__(self):
        return f"""
NyulanGenerator{{
    initial_s1_size:{len(self.initial_s1)}
    initial_s1:{self.initial_s1}
}}
        """

    def __init__(self) -> None:
        super().__init__()
        self.initial_s1 = []
        self.compile_time_stack = Stack()
        self.functions = []

    def from_tree(self, tree: Tree) -> None:
        super().transform(tree)

    def number(self, node: list[Token]) -> int:
        assert len(node) == 1
        return int(node[0].value, 0)

    def BASE32(self, node: str):
        self.initial_s1 += base64.b32decode(node + "=" * (8 - len(node) % 8))
        return Discard

    def COMMENT(self, _: str):
        return Discard

    @v_args(meta=True)
    def line(self, meta, nodes: list):
        if len(nodes) != 0 and nodes[0].type == "INSTRUCTION":
            instruction = nodes[0]
            if instruction == "nand":
                self.functions[-1].add_step("r0 &= r1;")
                self.functions[-1].add_step("r0 = !r0;")
            elif instruction == "lshift":
                self.functions[-1].add_step("if(r1 & 0xff >= 0){")
                self.functions[-1].add_step("    r0 <<= (r1 & 0xff);")
                self.functions[-1].add_step("}else{")
                self.functions[-1].add_step("    r0 >>= -static_cast<std::int8_t>(r1 & 0xff);")
                self.functions[-1].add_step("}")
            elif instruction == "push8s0":
                self.functions[-1].add_step("s0.push(r0 & 0xff)")
            elif instruction == "pop8s0":
                self.functions[-1].add_step("r0 ^= (r0 & 0xff);")
                self.functions[-1].add_step("r0 |= s0.top();")
                self.functions[-1].add_step("s0.pop();")
            elif instruction == "push8s1":
                self.functions[-1].add_step("s1.push(r1 & 0xff)")
            elif instruction == "pop8s1":
                self.functions[-1].add_step("r1 ^= (r1 & 0xff);")
                self.functions[-1].add_step("r1 |= s1.top();")
                self.functions[-1].add_step("s1.pop();")
            elif instruction == "push8s2":
                self.functions[-1].add_step("s2.push(r2 & 0xff)")
            elif instruction == "pop8s2":
                self.functions[-1].add_step("r2 ^= (r2 & 0xff);")
                self.functions[-1].add_step("r2 |= s2.top();")
                self.functions[-1].add_step("s2.pop();")
            elif instruction == "call":
                self.functions[-1].add_step("ftable[r0]();")
            elif instruction == "ret":
                self.functions[-1].add_step("return;")
            elif instruction == "print":
                self.functions[-1].add_step("std::cout.put(r0 & 0xff);")
            elif instruction == "read":
                self.functions[-1].add_step("r0 |= std::cin.get();")
            elif instruction == "exit":
                self.functions[-1].add_step("std::exit(r0);")
            elif instruction == "startfunc":
                self.functions.append(Function())
            elif instruction == "endfunc":
                self.functions[-1].add_fid(self.compile_time_stack.pop64())
            elif instruction == "deflabel":
                label = Label(self.compile_time_stack.pop64())
                self.functions[-1].add_step(f"{label};")
                self.functions[-1].add_label(label)
            elif instruction == "func2addr":
                self.functions[-1].add_step("r0 = r1;")
            elif instruction == "label2addr":
                self.functions[-1].add_step("r0 = r1;")
            elif instruction == "zero":
                self.compile_time_stack.push1(0)
            elif instruction == "one":
                self.compile_time_stack.push1(1)
            elif instruction == "ifz":
                self.functions[-1].add_step("if(r1 == 0){")
                # self.functions[-1].add_step("    goto *ltable[r0];")
                self.functions[-1].add_step(GOTO)
                self.functions[-1].add_step("}")
            elif instruction == "pushl8":
                self.functions[-1].add_step(f"s0.push({self.compile_time_stack.pop8()});")
            elif instruction == "xchg01":
                self.functions[-1].add_step("std::swap(r0,r1);")
            elif instruction == "xchg12":
                self.functions[-1].add_step("std::swap(r1,r2);")
            else:
                raise ParseError(f"invalid instruction {instruction}", meta.line)

    def start(self, _):
        lan22_initializer = Function("lan22_init")
        for func in self.functions:
            lan22_initializer.add_step(f"ftable[{func.fid}]=&{func.name};")
        for byte in reversed(self.initial_s1):
            lan22_initializer.add_step(f"s1.push({byte});")
        lan22_initializer.add_step("r0 = 0;")
        lan22_initializer.add_step("r1 = 0;")
        lan22_initializer.add_step("r2 = 0;")
        self.functions.append(lan22_initializer)

        entrypoint = Function("main", "int")
        self.functions.append(entrypoint)
        entrypoint.add_step("lan22_init();")
        entrypoint.add_step("ftable[0]();")
        return Discard

    def dump(self, outputfile) -> None:
        outputfile.write(self.dumps())

    def dumps(self) -> str:
        result = """
#include<iostream>
#include<unordered_map>
#include<stack>
#include<functional>

std::uint64_t r0,r1,r2;
std::stack<std::uint8_t> s0,s1,s2;
std::unordered_map<std::uint64_t,std::function<void(void)>> ftable;
        """.strip(
            "\n"
        ).rstrip(
            " "
        )
        for func in self.functions:
            result += f"{func}\n"
        return result


def parse(source: str) -> Tree:
    with open(Path(__file__).parent / "22lan.lark", "r", encoding="utf8") as larkfile:
        parser = Lark(larkfile.read(), propagate_positions=True)
    return parser.parse(source)


def main() -> None:
    parser = argparse.ArgumentParser(description="convert 22lan source code to nyulan assembly", prog="22lan.py")
    parser.add_argument("-s", "--source", help="source file", required=True)
    parser.add_argument("-o", "--output", help="output filename (in result folder)")
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug output")
    args = parser.parse_args()

    if args.output == None:
        args.output = Path(args.source).with_suffix(".cpp")

    with open(args.source, "r", encoding="utf8") as sourcefile:
        parsed_data = parse(sourcefile.read())
    generator = NyulanGenerator()
    try:
        generator.from_tree(parsed_data)
    except ParseError as e:
        print(sys.stderr, f"parse error at {args.source}:{e.linenum} info:{e}")

    if args.debug:
        print(generator)

    with open(args.output, "w", encoding="utf8") as outfile:
        generator.dump(outfile)


if __name__ == "__main__":
    main()
