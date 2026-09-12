#!/bin/bash
# Test script to verify the shell guards work with adversarial inputs

echo "Testing shell guards with adversarial inputs..."

echo
echo "Test 1: Multiline numeric '12\\n34' -> should return '12'"
input_val=$'12\n34'
raw_age=$(echo "$input_val" | head -n 1 | tr -d '[:space:]')
case "${raw_age}" in
    ''|*[!0-9]*) raw_age=9999;;
esac
echo "Result: $raw_age"
if [ "$raw_age" = "12" ]; then
    echo "✓ PASS"
else
    echo "✗ FAIL: Expected '12', got '$raw_age'"
    exit 1
fi

echo
echo "Test 2: Number with warning '42\\nwarning: ...' -> should return '42'"
input_val=$'42\nwarning: something'
raw_age=$(echo "$input_val" | head -n 1 | tr -d '[:space:]')
case "${raw_age}" in
    ''|*[!0-9]*) raw_age=9999;;
esac
echo "Result: $raw_age"
if [ "$raw_age" = "42" ]; then
    echo "✓ PASS"
else
    echo "✗ FAIL: Expected '42', got '$raw_age'"
    exit 1
fi

echo
echo "Test 3: Empty string -> should return '9999'"
input_val=""
raw_age=$(echo "$input_val" | head -n 1 | tr -d '[:space:]')
case "${raw_age}" in
    ''|*[!0-9]*) raw_age=9999;;
esac
echo "Result: $raw_age"
if [ "$raw_age" = "9999" ]; then
    echo "✓ PASS"
else
    echo "✗ FAIL: Expected '9999', got '$raw_age'"
    exit 1
fi

echo
echo "Test 4: Pure garbage 'warning:somethingbad' -> should return '9999' with no integer error"
input_val="warning:somethingbad"
raw_age=$(echo "$input_val" | head -n 1 | tr -d '[:space:]')
case "${raw_age}" in
    ''|*[!0-9]*) raw_age=9999;;
esac
echo "Result: $raw_age"
if [ "$raw_age" = "9999" ]; then
    echo "✓ PASS"
else
    echo "✗ FAIL: Expected '9999', got '$raw_age'"
    exit 1
fi

echo
echo "Test 5: Negative number '-5' -> should return '9999' (negative goes to 9999)"
input_val="-5"
raw_age=$(echo "$input_val" | head -n 1 | tr -d '[:space:]')
case "${raw_age}" in
    ''|*[!0-9]*) raw_age=9999;;
esac
echo "Result: $raw_age"
if [ "$raw_age" = "9999" ]; then
    echo "✓ PASS (negative correctly converted to 9999)"
else
    echo "✗ FAIL: Expected '9999', got '$raw_age'"
    exit 1
fi

echo
echo "All tests passed! Shell guards are working correctly."
