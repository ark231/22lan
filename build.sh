#!/usr/bin/bash

script_dir=$(cd $(dirname $0);pwd)
CC="g++"
STD="gnu++20"

result_name=$(basename $1 .22l)

$script_dir/22lan_cxx.py -s $1 -o $result_name.cpp

$CC -std=$STD -o $result_name $result_name.cpp
