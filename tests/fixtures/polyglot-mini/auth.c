#include <stdio.h>

int global = seed;

int check(int value)
{
    return value;
}

int login()
{
    int token = global;
    return check(token);
}
