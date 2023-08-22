#!/bin/fish

set DIR ./extra_wheels/
set wheels (path sort -r (ls $DIR))
set latest $wheels[1]

poetry add $DIR$latest
