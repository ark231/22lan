#!/usr/bin/bash

script_dir=$(cd $(dirname $0);pwd)
CC="g++"
STD="gnu++20"

$script_dir/22lan_cxx.py -s $1 -o $1.cpp

$CC -std=$STD -o $2 $1.cpp
