# tests/test_multilang_analyzer.py
import pytest
from src.services.code_analyzer import CodeAnalyzer


def test_python_analysis():
    analyzer = CodeAnalyzer()
    code = """
def hello():
    print("Hello")

class Foo:
    def bar(self):
        pass
"""
    result = analyzer.analyze(code, language="python")

    assert "hello" in result.functions
    assert "Foo" in result.classes
    assert "bar" in result.methods


def test_javascript_analysis():
    analyzer = CodeAnalyzer()
    code = """
function hello() {
    console.log("Hello");
}

class Foo {
    bar() {
        return 42;
    }
}

const add = (a, b) => a + b;
"""
    result = analyzer.analyze(code, language="javascript")

    assert "hello" in result.functions
    assert "Foo" in result.classes
    assert "bar" in result.methods


def test_typescript_analysis():
    analyzer = CodeAnalyzer()
    code = """
function greet(name: string): string {
    return `Hello, ${name}`;
}

interface User {
    name: string;
    age: number;
}
"""
    result = analyzer.analyze(code, language="typescript")

    assert "greet" in result.functions


def test_java_analysis():
    analyzer = CodeAnalyzer()
    code = """
public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    private void print(String message) {
        System.out.println(message);
    }
}
"""
    result = analyzer.analyze(code, language="java")

    assert "Calculator" in result.classes
    assert "add" in result.methods
    assert "print" in result.methods


def test_go_analysis():
    analyzer = CodeAnalyzer()
    code = """
package main

import "fmt"

type Calculator struct {
    value int
}

func (c *Calculator) Add(n int) {
    c.value += n
}

func main() {
    fmt.Println("Hello")
}
"""
    result = analyzer.analyze(code, language="go")

    assert "Calculator" in result.classes
    assert "Add" in result.functions
    assert "main" in result.functions


def test_rust_analysis():
    analyzer = CodeAnalyzer()
    code = """
use std::io;

struct Calculator {
    value: i32,
}

impl Calculator {
    fn new() -> Calculator {
        Calculator { value: 0 }
    }

    fn add(&mut self, n: i32) {
        self.value += n;
    }
}

fn main() {
    let mut calc = Calculator::new();
    calc.add(5);
}
"""
    result = analyzer.analyze(code, language="rust")

    assert "Calculator" in result.classes
    assert "new" in result.functions
    assert "add" in result.functions
    assert "main" in result.functions


def test_unknown_language():
    analyzer = CodeAnalyzer()
    code = "some code"
    result = analyzer.analyze(code, language="unknown")

    assert result.functions == []
    assert result.classes == []
