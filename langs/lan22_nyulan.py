#!/usr/bin/env python3
import argparse
from lark.visitors import Transformer, Discard, v_args
from lark.lexer import Token
from lark.tree import Tree
from lark.lark import Lark
import base64
import sys
from pathlib import Path
from . import base


class Register:
    def __init__(self, value: int):
        self.value = value

    def __str__(self) -> str:
        return f"r{self.value}"


class Label:
    def __init__(self, name: str, funcname: str = ""):
        self.name = name
        self.funcname = funcname

    def __str__(self) -> str:
        if self.name.startswith("."):
            return f"@{{{self.funcname}{self.name}}}"
        else:
            return f"@{{{self.name}}}"


class Variable:
    def __init__(self, name: str):
        self.name = name

    def __str__(self) -> str:
        return f"${{{self.name}}}"


class Literal:
    def __init__(self, value: str | int):
        self.value = value

    def __str__(self) -> str:
        return str(self.value)


class Placeholder:
    def __init__(self, name: str):
        self.name = name


class LabelDefinition:
    def __init__(self, name: str):
        self.name = name

    def __str__(self) -> str:
        return f"{self.name}:"


class OneStep:
    def __init__(self, instruction: str, operands: list[Register | Label | Variable | Literal | Placeholder]):
        self.instruction = instruction
        self.operands = operands

    def solve_placeholders(self, info: str):
        for i in range(len(self.operands)):
            operand = self.operands[i]
            if isinstance(operand, Placeholder) and operand.name == "funcname":
                self.operands[i] = Label(info)

    def _print_operands(self) -> str:
        result = ""
        for operand in self.operands:
            result += f"{operand},"
        return result.rstrip(",")

    def __str__(self) -> str:
        return f"{self.instruction} {self._print_operands()}"


class Function:
    def __init__(self, name=""):
        self.name: str = name
        self.steps: list[OneStep | LabelDefinition] = []
        self.labels: list[str] = []

    def add_step(self, step: OneStep | LabelDefinition):
        self.steps.append(step)

    def add_label(self, label: str):
        self.labels.append(label)

    def __str__(self) -> str:
        result = ""
        result += f"{self.name}:\n"
        for step in self.steps:
            if isinstance(step, OneStep):
                step.solve_placeholders(self.name)
            result += f"    {step}\n"
        return result


class NyulanGenerator(base.BasicGeneratorFromLan22):
    functions: list[Function]

    def __repr__(self):
        return f"""
NyulanGenerator{{
    initial_s1_size:{len(self.initial_s1_base32)}
    initial_s1:{self.initial_s1_base32}
}}
        """

    def __init__(self) -> None:
        super().__init__()
        self.functions = []

    @v_args(meta=True)
    def line(self, meta, nodes: list):
        if len(nodes) != 0 and nodes[0].type == "INSTRUCTION":
            instruction = nodes[0]
            if instruction == "nand":
                self.functions[-1].add_step(OneStep("AND", [Register(0), Register(1)]))
                self.functions[-1].add_step(OneStep("NOT", [Register(0)]))
            elif "shift" in instruction:
                self.functions[-1].add_step(OneStep("PUSHL8", [Literal(0xFF)]))
                self.functions[-1].add_step(OneStep("POP8", [Register(2)]))
                self.functions[-1].add_step(OneStep("AND", [Register(2), Register(1)]))
                self.functions[-1].add_step(OneStep(instruction.capitalize(), [Register(0), Register(2)]))
            elif instruction == "push8s0":
                self.functions[-1].add_step(OneStep("PUSHR8", [Register(0)]))
            elif instruction == "pop8s0":
                self.functions[-1].add_step(OneStep("POP8", [Register(0)]))
            elif instruction == "push8s1":
                self.functions[-1].add_step(OneStep("PUSHR8", [Register(1)]))
                self.functions[-1].add_step(OneStep("PUSHL64", [Label("lan22_push8s1")]))
                self.functions[-1].add_step(OneStep("POP64", [Register(2)]))
                self.functions[-1].add_step(OneStep("CALL", [Register(2)]))
            elif instruction == "pop8s1":
                self.functions[-1].add_step(OneStep("PUSHL64", [Label("lan22_pop8s1")]))
                self.functions[-1].add_step(OneStep("POP64", [Register(2)]))
                self.functions[-1].add_step(OneStep("CALL", [Register(2)]))
                self.functions[-1].add_step(OneStep("POP8", [Register(1)]))
            elif instruction == "call":
                self.functions[-1].add_step(OneStep("CALL", [Register(0)]))
            elif instruction == "ret":
                self.functions[-1].add_step(OneStep("RET", []))
            elif instruction == "print":
                self.functions[-1].add_step(OneStep("PUSHR8", [Register(0)]))
                self.functions[-1].add_step(OneStep("PUSHL64", [Label("lan22_print")]))
                self.functions[-1].add_step(OneStep("POP64", [Register(2)]))
                self.functions[-1].add_step(OneStep("CALL", [Register(2)]))
            elif instruction == "read":
                self.functions[-1].add_step(OneStep("PUSHL64", [Label("lan22_read")]))
                self.functions[-1].add_step(OneStep("POP64", [Register(2)]))
                self.functions[-1].add_step(OneStep("CALL", [Register(2)]))
                self.functions[-1].add_step(OneStep("POP8", [Register(0)]))
            elif instruction == "exit":
                self.functions[-1].add_step(OneStep("PUSHR8", [Register(0)]))
                self.functions[-1].add_step(OneStep("PUSHL64", [Literal((1 << 63) | 60)]))
                self.functions[-1].add_step(OneStep("POP64", [Register(2)]))
                self.functions[-1].add_step(OneStep("CALL", [Register(2)]))
            elif instruction == "startfunc":
                self.functions.append(Function())
            elif instruction == "endfunc":
                self.functions[-1].name = f"lan22_f{self.compile_time_stack.pop64():b}"
            elif instruction == "deflabel":
                labelname = f".lan22_l{self.compile_time_stack.pop64():b}"
                self.functions[-1].add_step(LabelDefinition(labelname))
                self.functions[-1].add_label(labelname)
            elif instruction == "func2addr":
                self.functions[-1].add_step(OneStep("PUSHR64", [Register(1)]))
                self.functions[-1].add_step(OneStep("PUSHL64", [Label("lan22_func2addr")]))
                self.functions[-1].add_step(OneStep("POP64", [Register(2)]))
                self.functions[-1].add_step(OneStep("CALL", [Register(2)]))
                self.functions[-1].add_step(OneStep("POP64", [Register(0)]))
            elif instruction == "label2addr":
                self.functions[-1].add_step(OneStep("PUSHR64", [Register(1)]))
                self.functions[-1].add_step(OneStep("PUSHL64", [Placeholder("funcname")]))
                self.functions[-1].add_step(OneStep("PUSHL64", [Label("lan22_label2addr")]))
                self.functions[-1].add_step(OneStep("POP64", [Register(2)]))
                self.functions[-1].add_step(OneStep("CALL", [Register(2)]))
                self.functions[-1].add_step(OneStep("POP64", [Register(0)]))
            elif instruction == "zero":
                self.compile_time_stack.push1(0)
            elif instruction == "one":
                self.compile_time_stack.push1(1)
            elif instruction == "ifz":
                self.functions[-1].add_step(OneStep("IFZ", [Register(0), Register(1)]))
            elif instruction == "pushl8":
                self.functions[-1].add_step(OneStep("PUSHL8", [Literal(self.compile_time_stack.pop8())]))
            elif instruction == "xchg":
                self.functions[-1].add_step(OneStep("PUSHR64", [Register(0)]))
                self.functions[-1].add_step(OneStep("MOV", [Register(0), Register(1)]))
                self.functions[-1].add_step(OneStep("POP64", [Register(1)]))
            else:
                raise base.ParseError(f"invalid instruction {instruction}", meta.line)

    def start(self, _):
        lan22_initializer = Function("lan22_init")
        lan22_initializer.add_step(OneStep("XOR", [Register(0), Register(0)]))
        lan22_initializer.add_step(OneStep("XOR", [Register(1), Register(1)]))
        lan22_initializer.add_step(OneStep("PUSHL64", [Label("lan22_new_func_dict")]))
        lan22_initializer.add_step(OneStep("POP64", [Register(0)]))
        lan22_initializer.add_step(OneStep("CALL", [Register(0)]))
        lan22_initializer.add_step(OneStep("POP64", [Register(4)]))
        lan22_initializer.add_step(OneStep("PUSHL64", [Label("lan22_new_stack")]))
        lan22_initializer.add_step(OneStep("POP64", [Register(0)]))
        lan22_initializer.add_step(OneStep("CALL", [Register(0)]))
        lan22_initializer.add_step(OneStep("POP64", [Register(5)]))
        lan22_initializer.add_step(OneStep("PUSHL64", [Label("lan22_func_dict_add_item")]))
        lan22_initializer.add_step(OneStep("POP64", [Register(0)]))
        lan22_initializer.add_step(OneStep("PUSHL64", [Label("lan22_new_label_dict")]))
        lan22_initializer.add_step(OneStep("POP64", [Register(1)]))
        lan22_initializer.add_step(OneStep("PUSHL64", [Label("lan22_label_dict_add_item")]))
        lan22_initializer.add_step(OneStep("POP64", [Register(2)]))
        for func in self.functions:
            lan22_initializer.add_step(OneStep("CALL", [Register(1)]))
            lan22_initializer.add_step(OneStep("POP64", [Register(3)]))
            for label in func.labels:
                lan22_initializer.add_step(OneStep("PUSHL64", [Label(label, func.name)]))
                lan22_initializer.add_step(OneStep("PUSHR64", [Register(3)]))
                lan22_initializer.add_step(OneStep("CALL", [Register(2)]))
            lan22_initializer.add_step(OneStep("PUSHR64", [Register(3)]))
            lan22_initializer.add_step(OneStep("PUSHL64", [Label(func.name)]))
            lan22_initializer.add_step(OneStep("PUSHR64", [Register(4)]))
            lan22_initializer.add_step(OneStep("CALL", [Register(0)]))
        for byte in reversed(base64.b32decode(self.initial_s1_base32 + "=" * (8 - len(self.initial_s1_base32) % 8))):
            lan22_initializer.add_step(OneStep("PUSHR8", [Register(1)]))
            lan22_initializer.add_step(OneStep("PUSHL64", [Literal(byte)]))
            lan22_initializer.add_step(OneStep("POP64", [Register(2)]))
            lan22_initializer.add_step(OneStep("CALL", [Register(2)]))
        lan22_initializer.add_step(OneStep("XOR", [Register(0), Register(0)]))
        lan22_initializer.add_step(OneStep("XOR", [Register(1), Register(1)]))
        lan22_initializer.add_step(OneStep("XOR", [Register(2), Register(2)]))
        lan22_initializer.add_step(OneStep("XOR", [Register(3), Register(3)]))
        self.functions.append(lan22_initializer)

        entrypoint = Function("_start")
        self.functions.append(entrypoint)
        entrypoint.add_step(OneStep("PUSHL64", [Label("lan22_init")]))
        entrypoint.add_step(OneStep("POP64", [Register(2)]))
        entrypoint.add_step(OneStep("CALL", [Register(2)]))
        entrypoint.add_step(OneStep("PUSHL64", [Literal(0)]))
        entrypoint.add_step(OneStep("PUSHL64", [Label("lan22_func2addr")]))
        entrypoint.add_step(OneStep("POP64", [Register(2)]))
        entrypoint.add_step(OneStep("CALL", [Register(2)]))
        entrypoint.add_step(OneStep("POP64", [Register(2)]))
        entrypoint.add_step(OneStep("CALL", [Register(2)]))
        return Discard

    def dumps(self) -> str:
        result = """
EXTERN lan22_push8s1
EXTERN lan22_pop8s1
EXTERN lan22_print
EXTERN lan22_read
EXTERN lan22_exit
EXTERN lan22_func2addr
EXTERN lan22_label2addr
EXTERN lan22_new_func_dict
EXTERN lan22_func_dict_add_item
EXTERN lan22_new_label_dict
EXTERN lan22_label_dict_add_item
EXTERN lan22_new_stack

GLOBAL _start

        """.strip(
            "\n"
        ).rstrip(
            " "
        )
        for func in self.functions:
            result += f"{func}\n"
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="convert 22lan source code to nyulan assembly", prog="22lan_nyulan.py")
    parser.add_argument("-s", "--source", help="source file", required=True)
    parser.add_argument("-o", "--output", help="output filename (in result folder)")
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug output")
    args = parser.parse_args()

    if args.output is None:
        args.output = Path(args.source).with_suffix(".nyu")

    with open(args.source, "r", encoding="utf8") as sourcefile:
        parsed_data = base.Lan22Parser.parse(sourcefile.read())
    generator = NyulanGenerator()
    try:
        generator.from_tree(parsed_data)
    except base.ParseError as e:
        print(sys.stderr, f"parse error at {args.source}:{e.linenum} info:{e}")

    if args.debug:
        print(generator)

    with open(args.output, "w", encoding="utf8") as outfile:
        generator.dump(outfile)


if __name__ == "__main__":
    main()
