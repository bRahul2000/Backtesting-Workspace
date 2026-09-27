"""Recursive-descent parser for Pine Script v5/v6.

The parser accepts the whole language surface (including features the runtime
does not execute yet, such as methods, user-defined types, imports and
generic calls), so an unsupported feature is reported by the analyzer as a
precise capability gap instead of a syntax error.
"""
from __future__ import annotations

from . import ast as A
from .errors import error
from .lexer import (COLOR, DEDENT, EOF, FLOAT, INDENT, INT, KEYWORD, NAME, NEWLINE, OP, STRING, Token,
                    tokenize)

QUALIFIERS = {"const", "input", "simple", "series"}
ASSIGN_OPS = (":=", "+=", "-=", "*=", "/=", "%=")


def parse(source: str) -> A.Script:
    lexed = tokenize(source)
    parser = Parser(lexed.tokens)
    script = parser.script()
    script.annotations = lexed.annotations
    version = lexed.annotations.get("version")
    script.version = int(version) if version and version.isdigit() else None
    return script


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens, self.pos = tokens, 0

    # -- token helpers ---------------------------------------------------------------------
    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        token = self.tokens[self.pos]
        self.pos = min(self.pos + 1, len(self.tokens) - 1)
        return token

    def expect_op(self, value: str) -> Token:
        if not self.tok.is_op(value):
            raise self.unexpected(f"`{value}`")
        return self.advance()

    def expect_kind(self, kind: str, what: str) -> Token:
        if self.tok.kind != kind:
            raise self.unexpected(what)
        return self.advance()

    def unexpected(self, expected: str):
        t = self.tok
        found = {NEWLINE: "end of line", INDENT: "indentation", DEDENT: "end of block", EOF: "end of script"}.get(
            t.kind, f"`{t.value}`")
        return error(f"Syntax error: expected {expected}, found {found}.", t.line, t.col)

    # -- program and blocks ------------------------------------------------------------------
    def script(self) -> A.Script:
        body = []
        while self.tok.kind != EOF:
            if self.tok.kind == NEWLINE:
                self.advance()
                continue
            if self.tok.kind in (INDENT, DEDENT):
                raise error("Unexpected indentation at the top level.", self.tok.line, self.tok.col)
            body.append(self.statement())
        return A.Script(1, 1, body=tuple(body))

    def block(self) -> A.Block:
        start = self.expect_kind(NEWLINE, "a new line before the indented block")
        if self.tok.kind != INDENT:
            raise self.unexpected("an indented block")
        self.advance()
        body = []
        while self.tok.kind not in (DEDENT, EOF):
            if self.tok.kind == NEWLINE:
                self.advance()
                continue
            body.append(self.statement())
        if self.tok.kind == DEDENT:
            self.advance()
        if not body:
            raise error("Empty block.", start.line, start.col)
        return A.Block(body[0].line, body[0].col, body=tuple(body))

    def body_after_arrow(self) -> A.Block:
        """After ``=>``: an indented block, or one expression on the same line."""
        if self.tok.kind == NEWLINE:
            return self.block()
        stmt = self.simple_statement()
        self.end_statement()
        return A.Block(stmt.line, stmt.col, body=(stmt,))

    def end_statement(self) -> None:
        previous = self.tokens[self.pos - 1] if self.pos else None
        if previous is not None and previous.kind == DEDENT:
            return                                   # a block statement already ended the line
        if self.tok.kind == NEWLINE:
            self.advance()
        elif self.tok.kind not in (EOF, DEDENT):
            raise self.unexpected("end of line")

    # -- statements ------------------------------------------------------------------------------
    def statement(self) -> A.Node:
        t = self.tok
        if t.is_kw("import"):
            return self.import_statement()
        exported = False
        if t.is_kw("export"):
            exported = True
            self.advance()
            t = self.tok
        if t.is_kw("method"):
            self.advance()
            return self.function_def(exported=exported, is_method=True)
        if t.is_kw("type", "enum"):
            return self.type_def(exported)
        if t.kind == NAME and self.peek().is_op("(") and self.is_function_def():
            return self.function_def(exported=exported)
        if exported:
            raise self.unexpected("a function, method or type after `export`")
        stmt = self.simple_statement()
        self.end_statement()
        return stmt

    def simple_statement(self) -> A.Node:
        t = self.tok
        if t.is_kw("break"):
            self.advance()
            return A.Break(t.line, t.col)
        if t.is_kw("continue"):
            self.advance()
            return A.Continue(t.line, t.col)
        if t.is_kw("var", "varip"):
            self.advance()
            return self.declaration(t, mode=t.value)
        if t.is_op("[") and self.is_tuple_decl():
            return self.tuple_decl()
        if t.kind == NAME:
            decl = self.try_typed_declaration()
            if decl is not None:
                return decl
            if self.peek().is_op("=") :
                return self.declaration(t)
        expr = self.expression()
        if self.tok.kind == OP and self.tok.value in ASSIGN_OPS:
            op = self.advance().value
            if not isinstance(expr, (A.Name, A.Attribute)):
                raise error("Only a variable (or an object field) can be reassigned.", expr.line, expr.col)
            return A.Assign(t.line, t.col, target=expr, op=op, value=self.rhs())
        if self.tok.is_op("="):
            raise error("`=` declares a variable; use `:=` to reassign.", self.tok.line, self.tok.col)
        return A.ExprStmt(expr.line, expr.col, expr=expr)

    def rhs(self) -> A.Node:
        return self.expression()

    def declaration(self, start: Token, mode: str | None = None) -> A.VarDecl:
        type_ref = None
        if self.tok.kind == NAME and not self.peek().is_op("="):
            type_ref = self.type_ref()
        name = self.expect_kind(NAME, "a variable name").value
        self.expect_op("=")
        return A.VarDecl(start.line, start.col, name=name, value=self.rhs(), mode=mode, type=type_ref)

    def try_typed_declaration(self) -> A.VarDecl | None:
        """[qualifier] type name = ...  (without var/varip)."""
        saved = self.pos
        start = self.tok
        try:
            type_ref = self.type_ref()
        except Exception:
            self.pos = saved
            return None
        if self.tok.kind == NAME and self.peek().is_op("="):
            name = self.advance().value
            self.advance()
            return A.VarDecl(start.line, start.col, name=name, value=self.rhs(), type=type_ref)
        self.pos = saved
        return None

    def type_ref(self) -> A.TypeRef:
        start = self.tok
        qualifier = None
        if start.kind == NAME and start.value in QUALIFIERS and self.peek().kind == NAME:
            qualifier = self.advance().value
        name_tok = self.expect_kind(NAME, "a type name")
        name = name_tok.value
        while self.tok.is_op(".") and self.peek().kind == NAME:
            self.advance()
            name += "." + self.advance().value
        args: list[A.TypeRef] = []
        if self.tok.is_op("<"):
            self.advance()
            args.append(self.type_ref())
            while self.tok.is_op(","):
                self.advance()
                args.append(self.type_ref())
            self.expect_op(">")
        array_suffix = False
        if self.tok.is_op("[") and self.peek().is_op("]"):
            self.advance()
            self.advance()
            array_suffix = True
        return A.TypeRef(start.line, start.col, name=name, qualifier=qualifier, args=tuple(args), array_suffix=array_suffix)

    def is_tuple_decl(self) -> bool:
        i = self.pos + 1
        while True:
            if self.tokens[i].kind != NAME:
                return False
            i += 1
            if self.tokens[i].is_op(","):
                i += 1
                continue
            return self.tokens[i].is_op("]") and self.tokens[i + 1].is_op("=") and not self.tokens[i + 1].is_op("==")

    def tuple_decl(self) -> A.TupleDecl:
        start = self.expect_op("[")
        names = [self.expect_kind(NAME, "a name").value]
        while self.tok.is_op(","):
            self.advance()
            names.append(self.expect_kind(NAME, "a name").value)
        self.expect_op("]")
        self.expect_op("=")
        return A.TupleDecl(start.line, start.col, names=tuple(names), value=self.rhs())

    def is_function_def(self) -> bool:
        depth, i = 0, self.pos + 1
        while i < len(self.tokens):
            t = self.tokens[i]
            if t.is_op("(", "["):
                depth += 1
            elif t.is_op(")", "]"):
                depth -= 1
                if depth == 0:
                    return self.tokens[i + 1].is_op("=>")
            elif t.kind in (NEWLINE, EOF) and depth == 0:
                return False
            i += 1
        return False

    def function_def(self, exported: bool = False, is_method: bool = False) -> A.FunctionDef:
        name_tok = self.expect_kind(NAME, "a function name")
        self.expect_op("(")
        params = []
        while not self.tok.is_op(")"):
            params.append(self.param())
            if self.tok.is_op(","):
                self.advance()
            elif not self.tok.is_op(")"):
                raise self.unexpected("`,` or `)`")
        self.expect_op(")")
        self.expect_op("=>")
        body = self.body_after_arrow()
        return A.FunctionDef(name_tok.line, name_tok.col, name=name_tok.value, params=tuple(params), body=body,
                             is_method=is_method, exported=exported)

    def param(self) -> A.Param:
        start = self.tok
        type_ref = None
        if self.tok.kind == NAME and not (self.peek().is_op(",", ")", "=")):
            type_ref = self.type_ref()
        name = self.expect_kind(NAME, "a parameter name").value
        default = None
        if self.tok.is_op("="):
            self.advance()
            default = self.expression()
        return A.Param(start.line, start.col, name=name, default=default, type=type_ref)

    def type_def(self, exported: bool) -> A.TypeDef:
        kw = self.advance()
        name = self.expect_kind(NAME, "a type name").value
        self.expect_kind(NEWLINE, "a new line")
        if self.tok.kind != INDENT:
            raise self.unexpected("indented fields")
        self.advance()
        fields = []
        while self.tok.kind not in (DEDENT, EOF):
            if self.tok.kind == NEWLINE:
                self.advance()
                continue
            start = self.tok
            mode = None
            if self.tok.is_kw("varip"):
                mode = self.advance().value
            if kw.value == "enum":
                field_name = self.expect_kind(NAME, "an enum field").value
                value = None
                if self.tok.is_op("="):
                    self.advance()
                    value = self.expression()
                fields.append(A.VarDecl(start.line, start.col, name=field_name, value=value))
            else:
                type_ref = self.type_ref()
                field_name = self.expect_kind(NAME, "a field name").value
                value = None
                if self.tok.is_op("="):
                    self.advance()
                    value = self.expression()
                fields.append(A.VarDecl(start.line, start.col, name=field_name, value=value, mode=mode, type=type_ref))
            self.end_statement()
        if self.tok.kind == DEDENT:
            self.advance()
        return A.TypeDef(kw.line, kw.col, name=name, fields=tuple(fields), exported=exported, is_enum=kw.value == "enum")

    def import_statement(self) -> A.Import:
        kw = self.advance()
        parts = []
        while self.tok.kind not in (NEWLINE, EOF) and not self.tok.is_kw("as"):
            parts.append(str(self.advance().value))
        alias = None
        if self.tok.is_kw("as"):
            self.advance()
            alias = self.expect_kind(NAME, "an alias").value
        self.end_statement()
        return A.Import(kw.line, kw.col, path="".join(parts), alias=alias)

    # -- structures (statements that are also expressions) ----------------------------------------
    def if_structure(self) -> A.If:
        kw = self.advance()
        condition = self.expression()
        body = self.block()
        orelse = None
        if self.tok.is_kw("else"):
            else_tok = self.advance()
            if self.tok.is_kw("if"):
                nested = self.if_structure()
                orelse = A.Block(else_tok.line, else_tok.col, body=(nested,))
            else:
                orelse = self.block()
        return A.If(kw.line, kw.col, condition=condition, body=body, orelse=orelse)

    def for_structure(self) -> A.Node:
        kw = self.advance()
        if self.tok.is_op("["):
            self.advance()
            first = self.expect_kind(NAME, "a name").value
            self.expect_op(",")
            second = self.expect_kind(NAME, "a name").value
            self.expect_op("]")
            if not self.tok.is_kw("in"):
                raise self.unexpected("`in`")
            self.advance()
            iterable = self.expression()
            return A.ForIn(kw.line, kw.col, names=(first, second), iterable=iterable, body=self.block())
        var = self.expect_kind(NAME, "a loop variable").value
        if self.tok.is_kw("in"):
            self.advance()
            iterable = self.expression()
            return A.ForIn(kw.line, kw.col, names=(var,), iterable=iterable, body=self.block())
        self.expect_op("=")
        start = self.expression()
        if not self.tok.is_kw("to"):
            raise self.unexpected("`to`")
        self.advance()
        end = self.expression()
        step = None
        if self.tok.is_kw("by"):
            self.advance()
            step = self.expression()
        return A.ForRange(kw.line, kw.col, var=var, start=start, end=end, step=step, body=self.block())

    def while_structure(self) -> A.While:
        kw = self.advance()
        condition = self.expression()
        return A.While(kw.line, kw.col, condition=condition, body=self.block())

    def switch_structure(self) -> A.Switch:
        kw = self.advance()
        subject = None if self.tok.kind == NEWLINE else self.expression()
        self.expect_kind(NEWLINE, "a new line after `switch`")
        if self.tok.kind != INDENT:
            raise self.unexpected("indented `switch` cases")
        self.advance()
        cases = []
        while self.tok.kind not in (DEDENT, EOF):
            if self.tok.kind == NEWLINE:
                self.advance()
                continue
            start = self.tok
            match = None
            if not self.tok.is_op("=>"):
                match = self.expression()
            self.expect_op("=>")
            body = self.body_after_arrow()
            cases.append(A.Case(start.line, start.col, match=match, body=body))
        if self.tok.kind == DEDENT:
            self.advance()
        return A.Switch(kw.line, kw.col, subject=subject, cases=tuple(cases))

    # -- expressions -----------------------------------------------------------------------------------
    def expression(self) -> A.Node:
        t = self.tok
        if t.is_kw("if"):
            return self.if_structure()
        if t.is_kw("switch"):
            return self.switch_structure()
        if t.is_kw("for"):
            return self.for_structure()
        if t.is_kw("while"):
            return self.while_structure()
        return self.ternary()

    def ternary(self) -> A.Node:
        condition = self.logical_or()
        if self.tok.is_op("?"):
            q = self.advance()
            then = self.ternary()
            self.expect_op(":")
            otherwise = self.ternary()
            return A.Ternary(q.line, q.col, condition=condition, then=then, otherwise=otherwise)
        return condition

    def _binary(self, next_level, ops: tuple[str, ...], keyword: bool = False) -> A.Node:
        left = next_level()
        while (self.tok.is_kw(*ops) if keyword else self.tok.is_op(*ops)):
            op_tok = self.advance()
            right = next_level()
            left = A.Binary(op_tok.line, op_tok.col, op=op_tok.value, left=left, right=right)
        return left

    def logical_or(self):
        return self._binary(self.logical_and, ("or",), keyword=True)

    def logical_and(self):
        return self._binary(self.equality, ("and",), keyword=True)

    def equality(self):
        return self._binary(self.relational, ("==", "!="))

    def relational(self):
        return self._binary(self.additive, ("<", ">", "<=", ">="))

    def additive(self):
        return self._binary(self.multiplicative, ("+", "-"))

    def multiplicative(self):
        return self._binary(self.unary, ("*", "/", "%"))

    def unary(self) -> A.Node:
        t = self.tok
        if t.is_op("-", "+") or t.is_kw("not"):
            self.advance()
            return A.Unary(t.line, t.col, op=t.value, operand=self.unary())
        return self.postfix()

    def postfix(self) -> A.Node:
        node = self.primary()
        while True:
            t = self.tok
            if t.is_op("("):
                node = self.call(node, ())
            elif t.is_op("<") and isinstance(node, (A.Name, A.Attribute)):
                generic = self.try_generic()
                if generic is None:
                    break
                node = self.call(node, generic)
            elif t.is_op(".") and self.peek().kind in (NAME, KEYWORD):
                self.advance()
                name_tok = self.advance()
                node = A.Attribute(name_tok.line, name_tok.col, target=node, name=str(name_tok.value))
            elif t.is_op("["):
                self.advance()
                offset = self.expression()
                self.expect_op("]")
                node = A.History(t.line, t.col, target=node, offset=offset)
            else:
                break
        return node

    def try_generic(self) -> tuple[A.TypeRef, ...] | None:
        saved = self.pos
        try:
            self.advance()
            args = [self.type_ref()]
            while self.tok.is_op(","):
                self.advance()
                args.append(self.type_ref())
            self.expect_op(">")
            if not self.tok.is_op("("):
                raise ValueError
            return tuple(args)
        except Exception:
            self.pos = saved
            return None

    def call(self, func: A.Node, generic: tuple) -> A.Call:
        open_tok = self.expect_op("(")
        args = []
        while not self.tok.is_op(")"):
            start = self.tok
            name = None
            if start.kind in (NAME, KEYWORD) and self.peek().is_op("=") :
                name = str(self.advance().value)
                self.advance()
            value = self.expression()
            args.append(A.Argument(start.line, start.col, value=value, name=name))
            if self.tok.is_op(","):
                self.advance()
            elif not self.tok.is_op(")"):
                raise self.unexpected("`,` or `)` in the argument list")
        self.expect_op(")")
        return A.Call(func.line, func.col, func=func, args=tuple(args), generic=generic)

    def primary(self) -> A.Node:
        t = self.tok
        if t.kind == INT:
            self.advance()
            return A.Literal(t.line, t.col, value=t.value, kind="int")
        if t.kind == FLOAT:
            self.advance()
            return A.Literal(t.line, t.col, value=t.value, kind="float")
        if t.kind == STRING:
            self.advance()
            return A.Literal(t.line, t.col, value=t.value, kind="string")
        if t.kind == COLOR:
            self.advance()
            return A.Literal(t.line, t.col, value=t.value, kind="color")
        if t.is_kw("true", "false"):
            self.advance()
            return A.Literal(t.line, t.col, value=t.value == "true", kind="bool")
        if t.kind == NAME:
            self.advance()
            return A.Name(t.line, t.col, name=t.value)
        if t.is_op("("):
            self.advance()
            inner = self.expression()
            self.expect_op(")")
            return inner
        if t.is_op("["):
            self.advance()
            items = []
            while not self.tok.is_op("]"):
                items.append(self.expression())
                if self.tok.is_op(","):
                    self.advance()
                elif not self.tok.is_op("]"):
                    raise self.unexpected("`,` or `]`")
            self.expect_op("]")
            return A.TupleExpr(t.line, t.col, items=tuple(items))
        if t.is_kw("if", "switch", "for", "while"):
            return self.expression()
        raise self.unexpected("an expression")
