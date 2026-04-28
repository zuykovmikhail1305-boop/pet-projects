from __future__ import annotations

import os
import re
import resource
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

BANNED_PATTERNS = [
    r"\bos\s*\.",
    r"\bio\s*\.",
    r"\bdebug\s*\.",
    r"\bpackage\s*\.",
    r"\brequire\s*\(",
    r"\bdofile\s*\(",
    r"\bloadfile\s*\(",
    r"\bload\s*\(",
]

LUA_BLOCK_RE = re.compile(r"lua\{([\s\S]*?)\}lua", re.IGNORECASE)


@dataclass
class ValidationResult:
    ok: bool
    phase: str
    message: str
    stdout: str = ""


class LuaTools:
    @staticmethod
    def extract_lua(text: str) -> str:
        match = LUA_BLOCK_RE.search(text)
        if match:
            return match.group(1).strip()
        return text.strip()

    @staticmethod
    def banned_check(code: str) -> ValidationResult:
        for pattern in BANNED_PATTERNS:
            if re.search(pattern, code):
                return ValidationResult(False, "security", f"Запрещённая конструкция: {pattern}")
        return ValidationResult(True, "security", "ok")

    @staticmethod
    def check_syntax(code: str) -> ValidationResult:
        with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["luac", "-p", tmp_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return ValidationResult(False, "syntax", (result.stderr or result.stdout).strip())
            return ValidationResult(True, "syntax", "ok")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @staticmethod
    def run_in_sandbox(code: str, context: dict | None = None) -> ValidationResult:
        context = context or {}
        security = LuaTools.banned_check(code)
        if not security.ok:
            return security

        lua_program = LuaTools._wrap_program(code, context)
        with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as tmp:
            tmp.write(lua_program)
            tmp_path = tmp.name
        try:
            completed = subprocess.run(
                ["lua", tmp_path],
                capture_output=True,
                text=True,
                timeout=5,
                preexec_fn=LuaTools._limit_resources,
            )
            if completed.returncode != 0:
                return ValidationResult(False, "runtime", (completed.stderr or completed.stdout).strip(), completed.stdout)
            return ValidationResult(True, "runtime", completed.stdout.strip() or "ok", completed.stdout)
        except subprocess.TimeoutExpired:
            return ValidationResult(False, "runtime", "Превышен таймаут выполнения (5 сек).")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @staticmethod
    def _limit_resources() -> None:
        memory_limit = 256 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
        os.setsid()

    @staticmethod
    def _to_lua_literal(value):
        if value is None:
            return "nil"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return repr(value)
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            return f'"{escaped}"'
        if isinstance(value, list):
            return "{" + ", ".join(LuaTools._to_lua_literal(v) for v in value) + "}"
        if isinstance(value, dict):
            items: list[str] = []
            for k, v in value.items():
                if isinstance(k, str) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k):
                    key = k
                else:
                    key = "[" + LuaTools._to_lua_literal(k) + "]"
                items.append(f"{key} = {LuaTools._to_lua_literal(v)}")
            return "{" + ", ".join(items) + "}"
        return "nil"

    @staticmethod
    def _wrap_program(code: str, context: dict) -> str:
        wf_vars = LuaTools._to_lua_literal(context.get("wf", {}).get("vars", {}))
        wf_init = LuaTools._to_lua_literal(context.get("wf", {}).get("initVariables", {}))
        escaped_code = code.replace("[[", "[=[").replace("]]", "]=]")
        return f'''
local wf = {{ vars = {wf_vars}, initVariables = {wf_init} }}
local _utils = {{
  array = {{
    new = function() return {{}} end,
    markAsArray = function(t) return t end
  }}
}}

local function serialize(value, depth)
  depth = depth or 0
  if depth > 4 then return '"<max-depth>"' end
  local t = type(value)
  if t == "nil" then return "null" end
  if t == "boolean" then return value and "true" or "false" end
  if t == "number" then return tostring(value) end
  if t == "string" then return string.format('%q', value) end
  if t == "table" then
    local parts = {{}}
    local max_index = 0
    local count = 0
    for k, _ in pairs(value) do
      count = count + 1
      if type(k) == 'number' and k > max_index and math.floor(k) == k then max_index = k end
    end
    local is_array = max_index == count
    if is_array then
      for i = 1, max_index do
        table.insert(parts, serialize(value[i], depth + 1))
      end
      return '[' .. table.concat(parts, ',') .. ']'
    end
    for k, v in pairs(value) do
      table.insert(parts, string.format('%q:%s', tostring(k), serialize(v, depth + 1)))
    end
    return '{{' .. table.concat(parts, ',') .. '}}'
  end
  return string.format('%q', '<' .. t .. '>')
end

local env = {{
  math = math,
  string = string,
  table = table,
  pairs = pairs,
  ipairs = ipairs,
  print = print,
  tostring = tostring,
  tonumber = tonumber,
  type = type,
  error = error,
  pcall = pcall,
  xpcall = xpcall,
  next = next,
  select = select,
  unpack = table.unpack,
  wf = wf,
  _utils = _utils,
}}

local fn, err = load([==[{escaped_code}]===], 'user_code', 't', env)
if not fn then
  error(err)
end

local ok, result = pcall(fn)
if not ok then
  error(result)
end

print(serialize(result))
'''
