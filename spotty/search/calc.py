"""
Калькулятор: безопасный разбор выражения через ast, без eval.

Понимает + - * / // % ^ **, скобки, запятую как десятичный знак, × ÷ и «x»
между числами, константы pi, e, tau и функции sqrt, sin, cos, tan, asin, acos,
atan, ln, log, log2, log10, exp, abs, round, floor, ceil, fact.
"""

import ast
import math
import operator
import re

_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: None,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "π": math.pi}


def _fact(n):
    if n != int(n) or n < 0 or n > 1000:
        raise ValueError("factorial")
    return math.factorial(int(n))


_FUNCTIONS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "ln": math.log, "log": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp, "abs": abs, "round": round, "floor": math.floor,
    "ceil": math.ceil, "fact": _fact,
}

_HAS_DIGIT = re.compile(r"\d")
_ALLOWED = re.compile(r"^[\d\s.,+\-*/%^()×÷xх·a-zπ]+$")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_TIMES = re.compile(r"(?<=[\d)])\s*[xх×·]\s*(?=[\d(])")
_OPERATOR = re.compile(r"[+\-*/%^×÷·]|\b[a-z]+\(|(?<=\d)\s*[xх]\s*\d|π|\bpi\b")


def _pow(base, exp):
    # 9**9**9 повесил бы программу на минуты — ограничиваем размер заранее.
    if abs(exp) > 1000 or (abs(base) > 1 and abs(exp) * math.log10(abs(base)) > 300):
        raise OverflowError("power")
    return operator.pow(base, exp)


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            return _pow(left, right)
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _FUNCTIONS and not node.keywords:
        return _FUNCTIONS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError("unsupported")


def evaluate(text):
    """Результат-строка или None, если это не выражение."""
    expr = text.strip().lower().rstrip("=").strip()
    if not expr or not _HAS_DIGIT.search(expr) or not _ALLOWED.match(expr):
        return None
    # Одно число без операций — не вычисление, а, например, поиск «2024».
    if not _OPERATOR.search(expr):
        return None
    expr = _TIMES.sub("*", expr)
    # Запятая между цифрами — десятичная, если только это не аргументы функции.
    if "(" not in expr or not re.search(r"[a-z]\(", expr):
        expr = _DECIMAL_COMMA.sub(".", expr)
    expr = (expr.replace("^", "**").replace("×", "*").replace("÷", "/")
            .replace("·", "*").replace("π", "pi"))
    try:
        value = _eval(ast.parse(expr, mode="eval"))
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError,
            OverflowError, RecursionError):
        return None
    return format_number(value)


def format_number(value):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        text = "%.12g" % value
        return text
    if isinstance(value, int) and len(str(abs(value))) > 30:
        return "%.12g" % value
    return str(value)
