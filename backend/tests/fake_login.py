#!/usr/bin/env python3
"""Pretends to be an OAuth CLI: prints a (hard-wrapped) URL, waits for a pasted code, then exits."""
import sys

print("Opening browser to sign in...")
print("If the browser didn't open, visit: https://example.com/oauth/authorize?client_id=abc&state=xyz&scope=a+b+c+d+e+f+g+h+i+j+k+l+m+n+")
print("o+p+q&redirect_uri=https%3A%2F%2Fexample.com%2Fcb")
print()
print("Paste code here if prompted > ", end="", flush=True)
code = sys.stdin.readline().strip()
print(f"\nLogin OK for code={code}")
sys.exit(0 if code == "good-code" else 1)
