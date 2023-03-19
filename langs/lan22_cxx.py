#!/usr/bin/env python3
import argparse
from lark.visitors import Discard, v_args
import base64
import sys
from pathlib import Path
import re
from . import base


class Label:
    def __init__(self, lid: int):
        self.name = f"l{lid:b}"
        self.lid = lid

    def __str__(self) -> str:
        return f"{self.name}:"


GOTO = "__GOTO__"


class Function:
    def __init__(self, name="", rettype="void", fid=None, debug_level=0):
        self.name: str = name
        self.steps: list[str] = []
        self.labels: list[Label] = []
        self.rettype = rettype
        self.fid = fid
        if fid is not None:
            self.add_fid(fid)
        self.debug_level = debug_level

    def add_step(self, step: str):
        self.steps.append(step)

    def add_label(self, label: Label):
        self.labels.append(label)

    def add_fid(self, fid: int):
        self.name = f"f{fid:b}"
        self.fid = fid

    def __str__(self) -> str:
        result = ""
        result += f"{self.rettype} {self.name}(){{\n"
        # if self.fid is not None:
        #     result += "    std::unordered_map<std::uint64_t,void*> ltable;\n"
        #     for label in self.labels:
        #         result += f"    ltable[{label.lid}]=&&{label.name};\n"
        if self.debug_level >= 3:
            result += f'    std::cerr<<";start {self.name}"<<std::endl;\n'
        for step in self.steps:
            match = re.match(f"( *){GOTO}", step)
            if match:
                lines = []
                lines.append(f"    {match[1]}switch(r0){{\n")
                for label in self.labels:
                    lines.append(f"    {match[1]}    case {label.lid}:goto {label.name};break;\n")
                lines.append(
                    f'    {match[1]}    default:{{std::cerr<<"invalid label id "<<r0<<std::endl;std::exit(1);}}\n'
                )
                lines.append(f"    {match[1]}}}\n")
                for line in lines:
                    result += line
            else:
                result += f"    {step}\n"
        if self.debug_level >= 3:
            result += f'    std::cerr<<";end {self.name}"<<std::endl;\n'
        result += "}"
        return result


class CPlusPlusGenerator(base.BasicGeneratorFromLan22):
    functions: list[Function]

    def __repr__(self):
        return f"""
CPlusPlusGenerator{{
    initial_s0_size:{len(self.initial_s0)}
    initial_s0:{self.initial_s0}
    initial_s1_size:{len(self.initial_s1)}
    initial_s1:{self.initial_s1}
    initial_s2_size:{len(self.initial_s2)}
    initial_s2:{self.initial_s2}
}}
        """

    def __init__(self, debug_level=0):
        super().__init__(debug_level=debug_level)
        self.functions = []

    def _debug_comment_instruction(self, instruction: str):
        if self.debug_level >= 2:
            self.functions[-1].add_step(f"//{instruction}")
        if self.debug_level >= 4:
            self.functions[-1].add_step(
                'std::cerr<<std::hex<<"    r0: 0x"<<r0<<",r1: 0x"<<r1<<",r2: 0x"<<r2<<",r3: 0x"<<r3<<std::dec<<",s0.size(): "<<s0.size()<<",s1.size(): "<<s1.size()<<",s2.size(): "<<s2.size()<<std::endl;'
            )
        if self.debug_level >= 5:
            self.functions[-1].add_step('std::cerr<<"    s0: (hex,top here)"<<s0<<std::endl;')
            self.functions[-1].add_step('std::cerr<<"    s1: (hex,top here)"<<s1<<std::endl;')
            self.functions[-1].add_step('std::cerr<<"    s2: (hex,top here)"<<s2<<std::endl;')
        if self.debug_level >= 3:
            self.functions[-1].add_step(f'std::cerr<<"    {instruction}"<<std::endl;')

    @v_args(meta=True)
    def line(self, meta, nodes: list):
        if len(nodes) != 0 and nodes[0].type == "INSTRUCTION":
            instruction = nodes[0]
            if instruction == "nand":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("r2 = r0 & r1;")
                self.functions[-1].add_step("r2 = ~r2;")
            elif instruction == "lshift":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("{")
                self.functions[-1].add_step("    std::int8_t r1_8 = r1 & 0xff;")
                self.functions[-1].add_step("    if(r1_8 >= 0){")
                self.functions[-1].add_step("        if(r1_8 >= 64){")
                self.functions[-1].add_step("            r2 = 0;")
                self.functions[-1].add_step("        }else{")
                self.functions[-1].add_step("            r2 = r0 << r1_8;")
                self.functions[-1].add_step("        }")
                self.functions[-1].add_step("    }else{")
                self.functions[-1].add_step("        r1_8 = -r1_8;")
                self.functions[-1].add_step("        if(r1_8 >= 64){")
                self.functions[-1].add_step("            r2 = 0;")
                self.functions[-1].add_step("        }else{")
                self.functions[-1].add_step("            r2 = r0 >> r1_8;")
                self.functions[-1].add_step("        }")
                self.functions[-1].add_step("    }")
                self.functions[-1].add_step("}")
            elif instruction == "push8s0":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("s0.push(r0 & 0xff);")
            elif instruction == "pop8s0":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("r0 ^= (r0 & 0xff);")
                self.functions[-1].add_step("r0 |= s0.top();")
                self.functions[-1].add_step("s0.pop();")
            elif instruction == "push8s1":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("s1.push(r1 & 0xff);")
            elif instruction == "pop8s1":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("r1 ^= (r1 & 0xff);")
                self.functions[-1].add_step("r1 |= s1.top();")
                self.functions[-1].add_step("s1.pop();")
            elif instruction == "push8s2":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("s2.push(r2 & 0xff);")
            elif instruction == "pop8s2":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("r2 ^= (r2 & 0xff);")
                self.functions[-1].add_step("r2 |= s2.top();")
                self.functions[-1].add_step("s2.pop();")
            elif instruction == "call":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("ftable[r0]();")
            elif instruction == "print":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("std::cout.put(r0 & 0xff);")
            elif instruction == "read":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("r0 |= std::cin.get();")
            elif instruction == "exit":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("std::exit(r0);")
            elif instruction == "startfunc":
                self.functions.append(Function(debug_level=self.debug_level))
            elif instruction == "endfunc":
                self.functions[-1].add_fid(self.compile_time_stack.pop64())
            elif instruction == "deflabel":
                self._debug_comment_instruction(instruction)
                label = Label(self.compile_time_stack.pop64())
                self.functions[-1].add_step(f"{label};")
                self.functions[-1].add_label(label)
            elif instruction == "zero":
                self.compile_time_stack.push1(0)
            elif instruction == "one":
                self.compile_time_stack.push1(1)
            elif instruction == "ifz":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("if(r1 == 0){")
                # self.functions[-1].add_step("    goto *ltable[r0];")
                self.functions[-1].add_step(f"    {GOTO}")
                self.functions[-1].add_step("}")
            elif instruction == "pushl8":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step(f"s0.push({self.compile_time_stack.pop8()});")
            elif instruction == "xchg03":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("std::swap(r0,r3);")
            elif instruction == "xchg13":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("std::swap(r1,r3);")
            elif instruction == "xchg23":
                self._debug_comment_instruction(instruction)
                self.functions[-1].add_step("std::swap(r2,r3);")
            else:
                raise base.ParseError(f"invalid instruction {instruction}", meta.line)

    def start(self, _):
        lan22_initializer = Function("init", debug_level=self.debug_level)
        for func in self.functions:
            lan22_initializer.add_step(f"ftable[{func.fid}]=&{func.name};")

        if self.initial_stacks_base32 != "":
            if self.initial_stacks_base32[0] != "\\":
                self.initial_stacks_base32 = r"\1" + self.initial_stacks_base32
            for initial_stack_base32 in self.initial_stacks_base32.split("\\"):
                if initial_stack_base32 == "" or len(initial_stack_base32) < 2:
                    continue
                stack_id = "OI2".index(initial_stack_base32[0])
                current_value = getattr(self, f"initial_s{stack_id}")
                current_value += base64.b32decode(
                    initial_stack_base32[1:] + "=" * (8 - len(initial_stack_base32[1:]) % 8)
                )
                setattr(self, f"initial_s{stack_id}", current_value)
            for i in range(3):
                for byte in reversed(getattr(self, f"initial_s{i}")):
                    lan22_initializer.add_step(f"s{i}.push({byte});")
        lan22_initializer.add_step("r0 = 0;")
        lan22_initializer.add_step("r1 = 0;")
        lan22_initializer.add_step("r2 = 0;")
        lan22_initializer.add_step("r3 = 0;")
        self.functions.append(lan22_initializer)

        entrypoint = Function("main", "int", debug_level=self.debug_level)
        self.functions.append(entrypoint)
        entrypoint.add_step("lan22::init();")
        entrypoint.add_step("lan22::ftable[0]();")
        return Discard

    def dumps(self) -> str:
        result = """
#include<iostream>
#include<unordered_map>
#include<stack>
#include<functional>

namespace lan22{
std::uint64_t r0,r1,r2,r3;
std::stack<std::uint8_t> s0,s1,s2;
std::unordered_map<std::uint64_t,std::function<void(void)>> ftable;
        """.strip(
            "\n"
        ).rstrip(
            " "
        )
        if self.debug_level >= 5:
            result += """
std::ostream& operator<<(std::ostream& stream,std::stack<std::uint8_t> value){
    stream<<"[";
    auto size=value.size();
    for(std::size_t i=0;i<size;i++){
        stream<<std::hex<<static_cast<int>(value.top())<<std::dec;
        value.pop();
        if(i != size - 1){
            stream<<",";
        }
    }
    stream<<"]";
    return stream;
}
            """.strip(
                "\n"
            ).rstrip(
                " "
            )
        cxx_main = Function()
        for func in self.functions:
            if func.name == "main":
                cxx_main = func
                continue
            result += f"{func}\n"
        result += "}// namespace lan22\n"
        result += f"{cxx_main}"
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="convert 22lan source code to nyulan assembly", prog="22lan_cxx.py")
    parser.add_argument("-s", "--source", help="source file", required=True)
    parser.add_argument("-o", "--output", help="output filename (in result folder)")
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug output")
    args = parser.parse_args()

    if args.output is None:
        args.output = Path(args.source).with_suffix(".cpp")

    with open(args.source, "r", encoding="utf8") as sourcefile:
        parsed_data = base.Lan22Parser.parse(sourcefile.read())
    generator = CPlusPlusGenerator()
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
