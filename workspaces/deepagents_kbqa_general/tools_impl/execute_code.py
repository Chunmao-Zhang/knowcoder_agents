"""
kbqa_tool_execute_code.py  -  execute_code Tool for deepagents_kbqa
==============================================================

功能：执行 LLM 生成的 Python 推理代码（纯文件驱动）。

设计（对齐 docs/kbqa_tools_design.md §2.5）：
  1. 接受 code_lines: List[str] 与 schema_file: str（均必填）。
  2. 从 schema_file 加载 triplets / topic_mids（由 build_subgraph_schema 写出）。
  3. 调用 build_ontology + generate_class_code 现场重建 Python schema。
  4. 子进程 subprocess.run 沙盒执行 LLM 代码，返回 result_dict。
  5. 工具间不共享内存 session：状态只通过文件传递，便于调试与并发。
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import subprocess
import sys
import uuid
from typing import List, Optional

from loguru import logger

# ── 路径设置 ────────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
# _PROJECT_ROOT points to a workspace-managed runtime directory containing
# `freebase_env/` and tool caches. It deliberately does not default to the
# deleted source tree.
from .paths import configure_environment

_PROJECT_ROOT = str(configure_environment())


# ══════════════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════════════

EXEC_TIMEOUT_SEC = int(os.getenv("KBQA_EXEC_TIMEOUT", "30"))
MAX_OUTPUT_LEN   = int(os.getenv("KBQA_MAX_OUTPUT_LEN", "2000"))

# 禁止在用户代码里出现的危险模块/函数
_DANGEROUS_PATTERNS = [
    r"\bimport\s+os\b",
    r"\bimport\s+subprocess\b",
    r"\bimport\s+sys\b",
    r"\bos\.system\b",
    r"\bos\.popen\b",
    r"\bsubprocess\.",
    # open() is checked via AST below to avoid false positives in string literals
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"__import__",
    r"\bshutil\b",
]

_AST_BANNED_CALLS = {"open"}

def _check_safe(code: str) -> str | None:
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            return f"[Error] Unsafe code detected: pattern '{pattern}' is not allowed."
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"[SyntaxError] {e}"
    # AST-based check for open() — avoids false positives inside string literals
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name and name in _AST_BANNED_CALLS:
                return f"[Error] Unsafe code detected: call to '{name}()' is not allowed."
    return None


def _parse_stdout_answer(stdout_output: str) -> list[str]:
    """Recover answers from an explicit `ANSWER: [...]` print when result_dict was empty."""
    answers: list[str] = []
    for line in (stdout_output or "").splitlines():
        match = re.match(r"^\s*ANSWER\s*:\s*(.+?)\s*$", line)
        if not match:
            continue
        raw = match.group(1).strip()
        try:
            parsed = ast.literal_eval(raw)
        except Exception:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw
        if isinstance(parsed, (list, tuple, set)):
            values = [str(item) for item in parsed if item is not None]
        elif parsed is None:
            values = []
        else:
            values = [str(parsed)]
        if values:
            answers = values
    return list(dict.fromkeys(answers))

# ══════════════════════════════════════════════════════════════════════════════
# 主函数：execute_code
# ══════════════════════════════════════════════════════════════════════════════

def execute_code(
    code_lines: List[str],
    schema_file: str,
    run_id: Optional[str] = None,  # 内部任务标识，仅用于日志关联；不暴露给 LLM
) -> str:
    """在沙盒中基于 build_subgraph_schema 生成的子图执行 Python。

    对齐 docs/kbqa_tools_design.md §2.5。

    Args:
        code_lines: 一行 Python 一个列表元素（必填）。
        schema_file: build_subgraph_schema 返回的 `# schema_file: <path>` 路径（必填）。
        run_id: 内部任务标识，仅用于日志关联；非 LLM 可见入参。

    Returns:
        成功：`ANSWER: [...]`（result_dict 序列化）。
        异常：`[CODE_HINT] Empty result | CVT removed | AttributeError | ...`。
    """
    # ── 1. 校验 code_lines ──
    if not isinstance(code_lines, list) or not code_lines:
        return "[Error] execute_code requires non-empty `code_lines: List[str]`."
    code = "\n".join(str(line) for line in code_lines if line is not None)
    if not code.strip():
        return "[Error] execute_code requires non-empty `code_lines: List[str]`."

    # ── 2. 校验 schema_file ──
    if not isinstance(schema_file, str) or not schema_file.strip():
        return (
            "[Error] execute_code requires `schema_file: <path>` from a previous "
            "build_subgraph_schema response (look for `# schema_file: <path>`)."
        )
    schema_file = schema_file.strip()
    # ── Resolve schema_file path ─────────────────────────────────────────────
    # build_subgraph_schema returns a path RELATIVE to the project root, e.g.
    #   tools/.subgraph_cache/subgraph_abc123.json
    # But we also accept absolute paths from legacy calls and
    # fall back to locating the file by basename in the subgraph_cache (handles
    # stale absolute prefixes like /Users/.../ from older local traces).
    if not os.path.isabs(schema_file):
        schema_file = os.path.join(_PROJECT_ROOT, schema_file)
    if not os.path.isfile(schema_file):
        _bn = os.path.basename(schema_file)
        # Build candidate basenames in priority order:
        #   1. raw basename as given (e.g. "subgraph_abc123.json")
        #   2. with "subgraph_" prefix added if missing (e.g. "fc82b760.json"
        #      -> "subgraph_fc82b760.json" — handles models that copy only
        #      the uuid part of the path)
        _bn_candidates = []
        if _bn.startswith("subgraph_") and _bn.endswith(".json"):
            _bn_candidates.append(_bn)
        elif re.match(r"^[a-f0-9]{6,12}\.json$", _bn):
            _bn_candidates.append("subgraph_" + _bn)
        _resolved = None
        for _cand_bn in _bn_candidates:
            _cand = os.path.join(_PROJECT_ROOT, "tools_impl", ".subgraph_cache", _cand_bn)
            if os.path.isfile(_cand):
                _resolved = _cand
                break
        if _resolved:
            schema_file = _resolved
        else:
            return f"[Error] schema_file not found: {schema_file}"

    # ── 3. 加载 subgraph ──
    try:
        with open(schema_file, "r", encoding="utf-8") as _sf:
            _file_data = json.load(_sf)
    except Exception as e:
        return f"[Error] Failed to load schema_file {schema_file}: {e}"

    all_triplets: list = []
    seen_triple_keys: set = set()
    for t in _file_data.get("triplets", []) or []:
        if not isinstance(t, (list, tuple)) or len(t) != 3:
            continue
        key = (str(t[0]), str(t[1]), str(t[2]) if t[2] is not None else "")
        if key in seen_triple_keys:
            continue
        seen_triple_keys.add(key)
        all_triplets.append(tuple(t))

    all_topic_mids: list = []
    seen_mid_set: set = set()
    for m in _file_data.get("topic_mids", []) or []:
        if isinstance(m, str) and m and m not in seen_mid_set:
            seen_mid_set.add(m)
            all_topic_mids.append(m)

    if not all_triplets:
        return (
            "[Error] No triples found in schema_file. "
            "Ensure build_subgraph_schema actually returned data."
        )

    # ── 4. 现场重建 ontology + Python class_code ──
    try:
        from .build_subgraph_schema import build_ontology, generate_class_code
    except Exception as e:
        return f"[Error] Cannot load schema builder: {e}"

    try:
        type_relation_tuples, type_map, mid_name_map = build_ontology(
            all_triplets, all_topic_mids
        )
        class_code = generate_class_code(
            type_relation_tuples,
            type_map,
            mid_name_map,
            topic_mids=all_topic_mids,
            query="",  # semantic_hint 已在 build_subgraph_schema 入参中删除
        )
    except Exception as e:
        return f"[Error] Schema build failed: {type(e).__name__}: {e}"

    if not class_code:
        return (
            "[Error] Schema generation produced empty class_code. "
            "The schema_file may contain only schema-level placeholders without entity names."
        )

    triplets = list(all_triplets)
    topic_mids_local = list(all_topic_mids)
    ontology = {
        "ontology": type_relation_tuples,
        "type_map": type_map,
        "mid_name_map": mid_name_map,
    }
    # logger.info(
    #     f"[execute_code] Loaded schema_file={schema_file}, "
    #     f"{len(triplets)} unique triples, {sum(len(v) for v in type_map.values())} entities"
    # )

    unsafe_err = _check_safe(code)
    if unsafe_err:
        return unsafe_err

    # ── Save LLM code for inspection ──
    try:
        _cache_dir = os.path.join(_PROJECT_ROOT, "tools_impl", ".subgraph_cache")
        os.makedirs(_cache_dir, exist_ok=True)
        # Derive filename from schema_file (prefer subgraph_*.json)
        _fid = None
        base = os.path.basename(schema_file)
        for _prefix in ("subgraph_", "entity_", "pred_"):
            if base.startswith(_prefix):
                _fid = base.replace(_prefix, "").replace(".json", "")
                break
        if not _fid:
            _fid = uuid.uuid4().hex[:8]
        # Append counter to avoid overwrite when execute_code is called multiple times
        _code_idx = 0
        while os.path.exists(os.path.join(_cache_dir, f"code_{_fid}_{_code_idx}.py")):
            _code_idx += 1
        _code_file = os.path.join(_cache_dir, f"code_{_fid}_{_code_idx}.py")
        with open(_code_file, "w", encoding="utf-8") as _cf:
            _cf.write(code)
        # logger.info(f"[execute_code] Saved LLM code to {_code_file}")
    except Exception as e:
        logger.warning(f"Failed to save LLM code file: {e}")

    # ── Trim triplets for large subgraphs to avoid _instantiate_all timeout ──
    MAX_ENTITY_FOR_FULL = 10000
    MAX_REACHABLE = 50000  # cap BFS expansion to prevent hub explosion
    total_entity_count = sum(len(mids) for mids in type_map.values())
    if total_entity_count > MAX_ENTITY_FOR_FULL and triplets:
        anchor_mids = set(topic_mids_local)
        # Also keep exact generic entity names that the LLM explicitly references.
        for entity_name in mid_name_map:
            if entity_name and entity_name in code:
                anchor_mids.add(entity_name)
        if anchor_mids:
            # BFS from anchor_mids with a cap on total reachable nodes
            reachable = set(anchor_mids)
            frontier = set(anchor_mids)
            adj = {}
            for h, p, t in triplets:
                h_str = str(h)
                t_str = str(t)
                adj.setdefault(h_str, []).append(t_str)
                adj.setdefault(t_str, []).append(h_str)
            for hop in range(4):
                if len(reachable) >= MAX_REACHABLE:
                    break
                next_frontier = set()
                for mid in frontier:
                    for nbr in adj.get(mid, []):
                        if nbr not in reachable:
                            reachable.add(nbr)
                            next_frontier.add(nbr)
                            if len(reachable) >= MAX_REACHABLE:
                                break
                    if len(reachable) >= MAX_REACHABLE:
                        break
                frontier = next_frontier
                if not frontier:
                    break
            # Keep triplets where head is reachable AND:
            #   - tail is a literal (always keep), OR
            #   - tail is an entity that is also reachable
            # This prevents hub nodes from pulling in 100k+ unreachable entities.
            trimmed = []
            for h, p, t in triplets:
                if str(h) not in reachable:
                    continue
                tail_is_entity = isinstance(t, str) and t in mid_name_map
                if tail_is_entity and str(t) not in reachable:
                    continue
                trimmed.append((h, p, t))
            triplets = trimmed
            # Rebuild type_map to match trimmed triplets
            kept_mids = set()
            for h, p, t in triplets:
                kept_mids.add(str(h))
                if isinstance(t, str) and t in mid_name_map:
                    kept_mids.add(t)
            type_map = {
                cls: [m for m in mids if m in kept_mids]
                for cls, mids in type_map.items()
            }
            type_map = {cls: mids for cls, mids in type_map.items() if mids}
            new_count = sum(len(v) for v in type_map.values())
            # logger.info(f"[execute_code] Trimmed: {total_entity_count} -> {new_count} entities, {len(triplets)} triplets")

    sandbox_id = str(uuid.uuid4())[:8]
    work_dir = os.path.join(_PROJECT_ROOT, "tools_impl", ".sandbox")
    os.makedirs(work_dir, exist_ok=True)
    
    data_path = os.path.join(work_dir, f"data_{sandbox_id}.json")
    script_path = os.path.join(work_dir, f"exec_{sandbox_id}.py")
    res_path = os.path.join(work_dir, f"res_{sandbox_id}.json")
    
    ontology_tuples = ontology.get("ontology", []) if isinstance(ontology, dict) else ontology
    init_data = {
        "type_map": type_map,
        "mid_name_map": mid_name_map,
        "triplets": triplets,
        "ontology": list(ontology_tuples)
    }
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(init_data, f)
        
    # ========== 独立进程的 Python 脚本模板 ==========
    script_template = """
import json
import sys
import re
from collections import defaultdict

# 1. 挂载 Class 定义
{class_code}

# 2. 挂载实例化函数
def _instantiate_all(type_map, mid_name_map, triplets, ontology):
    mid_to_types = {{}}
    for cls_name, mids in type_map.items():
        for m in mids:
            mid_to_types.setdefault(m, set()).add(cls_name)

    cls_is_entity = {{}}
    for cls_name, mids in type_map.items():
        cls_is_entity[cls_name] = bool(mids) and all(isinstance(t, str) for t in mids)

    predicate_to_pairs = defaultdict(list)
    if ontology:
        for cls_head, prop, cls_tail in ontology:
            predicate_to_pairs[prop].append((cls_head, cls_tail))

    class_cache = globals()
    unified_instances = {{}}

    def get_unified_instance(mid, default_type):
        if mid not in unified_instances:
            types = mid_to_types.get(mid, set())
            if default_type and default_type != "Entity":
                types.add(default_type)
            
            bases = []
            for t in types:
                if t in class_cache and isinstance(class_cache[t], type):
                    bases.append(class_cache[t])
            
            if not bases:
                class DummyEntity:
                    def __init__(self, _entity_name=None):
                        self._entity_name = _entity_name
                bases.append(DummyEntity)
            
            try:
                CombinedType = type("Combined_" + re.sub(r"\\W+", "_", str(mid)).strip("_"), tuple(bases), {{}})
                obj = CombinedType(_entity_name=mid)
            except Exception:
                obj = bases[0](_entity_name=mid)
                
            name = mid_name_map.get(mid)
            if name and name not in ("Entity Name", "CVT node"):
                obj._name = name
                obj._label = name
            else:
                obj._name = ""
                obj._label = mid
                
            unified_instances[mid] = obj
        return unified_instances[mid]

    literal_instances = {{}}

    for h_mid, predicate, t_mid in triplets:
        if isinstance(predicate, list):
            predicate = predicate[1]

        rel_attr = re.sub(r"\\W+", "_", str(predicate)).strip("_")
        if rel_attr and rel_attr[0].isdigit():
            rel_attr = "rel_" + rel_attr
        pairs = predicate_to_pairs.get(predicate)
        
        if not pairs:
            continue
            
        for head_type, tail_type in pairs:
            h_obj = get_unified_instance(h_mid, head_type)

            if not hasattr(h_obj, rel_attr) or not isinstance(getattr(h_obj, rel_attr), list):
                setattr(h_obj, rel_attr, [])

            tail_is_entity = isinstance(t_mid, str) and t_mid in mid_name_map

            if tail_is_entity:
                t_obj = get_unified_instance(t_mid, tail_type)
            else:
                lit_key = f"{{tail_type}}_{{t_mid}}"
                if lit_key not in literal_instances:
                    T = class_cache.get(tail_type)
                    if T is None:
                        class DummyLiteral:
                            def __init__(self, _value=None):
                                self._value = _value
                            def __str__(self): return str(self._value)
                            def __repr__(self): return str(self._value)
                        T = DummyLiteral
                        globals()[tail_type] = T
                        
                    try:
                        literal_instances[lit_key] = T(_value=str(t_mid))
                    except TypeError:
                        try:
                            literal_instances[lit_key] = T(_mid=str(t_mid))
                        except Exception:
                            literal_instances[lit_key] = t_mid
                t_obj = literal_instances[lit_key]

            if t_obj not in getattr(h_obj, rel_attr):
                getattr(h_obj, rel_attr).append(t_obj)

    return list(unified_instances.values()) + list(literal_instances.values())

def instantiate_from_ontology_n_subgraph(ontology_dict=None, subgraphs_list=None):
    return entities

# 3. 加载数据与初始化上下文
with open("{data_path}", "r", encoding="utf-8") as f:
    _d = json.load(f)

class EntityList(list):
    def __getitem__(self, key):
        if isinstance(key, str):
            for entity in self:
                if getattr(entity, "_entity_name", None) == key:
                    return entity
            raise KeyError(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError, TypeError):
            return default

    def by_mid(self, mid, default=None):
        return self.get(mid, default)

entities = _instantiate_all(
    _d["type_map"], _d["mid_name_map"], _d["triplets"], _d["ontology"]
)
entities = EntityList([e for e in entities if hasattr(e, "_entity_name")])
entities_by_name = {{e._entity_name: e for e in entities if getattr(e, "_entity_name", None)}}
entities_by_mid = entities_by_name
entities_by_id = entities_by_name

mid_name_map = _d["mid_name_map"]
entity_name_map = mid_name_map

def get_name(entity):
    if entity is None:
        return ""
    if hasattr(entity, "_entity_name") and entity._entity_name:
        return mid_name_map.get(entity._entity_name, "")
    return ""

def nested_dict():
    return defaultdict(nested_dict)

result_dict = {{
    "detailed_results": nested_dict(),
    "direct_results": []
}}

# 4. 执行 LLM 代码
{llm_code}

# 5. 后处理与输出写入
_flat_direct = []
for _v in result_dict.get("direct_results", []):
    if isinstance(_v, list):
        _flat_direct.extend([str(x) for x in _v])
    elif _v is not None:
        _flat_direct.append(str(_v))
_flat_direct = list(dict.fromkeys(_flat_direct))

def _append_custom_answer(_bucket, _value):
    if _value is None:
        return
    if isinstance(_value, (list, tuple, set)):
        for _item in _value:
            _append_custom_answer(_bucket, _item)
        return
    if isinstance(_value, dict):
        if "_name" in _value and _value.get("_name"):
            _bucket.append(str(_value.get("_name")))
            return
        for _item in _value.values():
            _append_custom_answer(_bucket, _item)
        return
    _bucket.append(str(_value))

if not _flat_direct:
    _custom_direct = []
    for _key, _value in list(result_dict.items()):
        if _key in ("direct_results", "detailed_results") or str(_key).startswith("_"):
            continue
        _append_custom_answer(_custom_direct, _value)
    _flat_direct = list(dict.fromkeys(_custom_direct))

_det = result_dict.get("detailed_results", {{}})
if hasattr(_det, "items") and hasattr(_det, "default_factory"):
    _det = dict(_det)

if not _flat_direct:
    result_dict = {{"detailed_results": _det}}
else:
    result_dict = {{
        "direct_results": _flat_direct,
        "detailed_results": _det
    }}

with open("{res_path}", "w", encoding="utf-8") as _out_f:
    json.dump(result_dict, _out_f, ensure_ascii=False)
"""
    
    script_content = script_template.format(
        class_code=class_code,
        data_path=data_path,
        res_path=res_path,
        llm_code=code
    )
    
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_content)

    python_exec = sys.executable or "python3"
    try:
        try:
            proc = subprocess.run(
                [python_exec, script_path],
                capture_output=True,
                text=True,
                timeout=int(os.getenv("KBQA_EXEC_TIMEOUT", str(EXEC_TIMEOUT_SEC)))
            )
            
            stdout_output = proc.stdout.strip()
            stderr_output = proc.stderr.strip()
            
            if proc.returncode != 0:
                error_lines = stderr_output.split('\n')
                if len(error_lines) > 5:
                    stderr_output = "\n".join(error_lines[-5:])
                return f"[Error] Execution failed:\n{stderr_output}"
                
        except subprocess.TimeoutExpired:
            # Provide entity count to help model understand WHY it timed out
            entity_count = sum(len(mids) for mids in type_map.values()) if type_map else 0
            hint = ""
            if entity_count > 500:
                hint = (
                    f" The subgraph has {entity_count} entities — iterating all of them is too slow. "
                    "Use `entity = entities_by_name['exact entity name']` to access topic/parent entities directly "
                    "instead of `for entity in entities`."
                )
            return f"[Error] Code execution timed out after {EXEC_TIMEOUT_SEC}s.{hint}"
        except Exception as e:
            return f"[Error] Subprocess execution err: {e}"

        if os.path.exists(res_path):
            try:
                with open(res_path, "r", encoding="utf-8") as f:
                    res_obj = json.load(f)
            except Exception as eval_e:
                res_obj = f"Failed to parse JSON: {eval_e}"
        else:
            res_obj = "File not generated."

        code_hint = ""
        if isinstance(res_obj, dict):
            detailed = res_obj.get("detailed_results", {})
            direct   = res_obj.get("direct_results", [])
            if not detailed and not direct:
                stdout_answers = _parse_stdout_answer(stdout_output)
                if stdout_answers:
                    res_obj["direct_results"] = stdout_answers
                    direct = stdout_answers

            # ── Optional CVT node detection. Generic graphs only use CVT when
            # the uploaded graph metadata marks mediator relations/nodes.
            if detailed and isinstance(detailed, dict):
                filtered = {}
                cvt_removed = []

                for mid_key, info in detailed.items():
                    name = ""
                    if isinstance(info, dict):
                        name = info.get("_name", "")
                    # CVT 判定：_name / graph label are explicitly "CVT node".
                    local_name = mid_name_map.get(mid_key, "")
                    is_cvt = (
                        (name == "CVT node")
                        or (local_name == "CVT node")
                        or str(mid_key).endswith("CVT")
                    )
                    if is_cvt:
                        cvt_removed.append(mid_key)
                    else:
                        filtered[mid_key] = info
                if cvt_removed:
                    res_obj["detailed_results"] = filtered
                    detailed = filtered
                    code_hint = (
                        f"[CODE_HINT] CVT error (category 2): {len(cvt_removed)} CVT intermediate node(s) "
                        f"removed: {cvt_removed[:3]}. "
                        "Your code collected intermediate CVT nodes instead of real entities. "
                        "Traverse one more hop through the CVT to reach the real entity or literal. "
                        "For example, if you stopped at a CVT with attr `some_relation`, "
                        "iterate its children to find the real answer entity.\n"
                    )

            # ── CODE_HINT: 4 类错误诊断（对齐 CoG code_regeneration_template）──
            # Category 1: Empty result (wrong attr or stopped at CVT)
            # Category 2: CVT nodes (handled above)
            # Category 3: Key error (unknown entity-id keys)
            # Category 4: Execution error (handled in returncode!=0 branch)
            if detailed and isinstance(detailed, dict) and not code_hint:
                all_mids = list(detailed.keys())
                all_known = all(str(k) in mid_name_map for k in all_mids)
                if not all_known:
                    bad_keys = [k for k in all_mids if str(k) not in mid_name_map][:3]
                    code_hint = (
                        f"[CODE_HINT] Key error (category 3): keys in detailed_results should be "
                        f"entity names from the active graph, but got: {bad_keys}. "
                        "Use entity._mid as the key in detailed_results.\n"
                    )
            elif not detailed and not direct:
                # Category 1: Empty result
                # Token-saving: do NOT dump all available attrs (model already sees them
                # in the build_subgraph_schema schema). Only emit fuzzy-match fixes for attrs the
                # model demonstrably mis-spelled in the code.
                available_attrs = set()
                ontology_tuples = ontology.get("ontology", []) if isinstance(ontology, dict) else []
                for _ht, rel, _tt in ontology_tuples:
                    available_attrs.add(rel.replace(".", "_").replace("-", "_"))

                used_attrs = set(re.findall(r'\b(\w+_\w+(?:_\w+)*)\b', code or ""))
                wrong_attrs = used_attrs - available_attrs - {
                    'result_dict', 'detailed_results', 'direct_results',
                    'mid_name_map', 'get_name', 'entities', 'entities_by_mid',
                    'nested_dict', 'hasattr', 'getattr', 'isinstance', 'str', 'int', 'float',
                }
                wrong_attrs = {a for a in wrong_attrs if len(a) > 5}  # filter noise

                fix_suggestions = []
                if wrong_attrs and available_attrs:
                    from difflib import get_close_matches
                    for wa in sorted(wrong_attrs):
                        matches = get_close_matches(wa, available_attrs, n=1, cutoff=0.5)
                        if matches:
                            fix_suggestions.append(f"'{wa}' -> '{matches[0]}'")

                fix_hint = ""
                if fix_suggestions:
                    # Cap at 5 to bound length
                    fix_hint = f" Possible fixes: {'; '.join(fix_suggestions[:5])}."

                # Show which entities the model accessed actually have populated
                accessed_entities = re.findall(
                    r"entities_by_name\s*\[\s*['\"]([^'\"]+)['\"]\s*\]", code or ""
                )
                entity_presence_hint = ""
                if accessed_entities:
                    from collections import defaultdict as _dd
                    _hpc: dict[str, dict[str, int]] = _dd(lambda: _dd(int))
                    for _h, _r, _t in all_triplets:
                        _a = re.sub(r"\W+", "_", str(_r)).strip("_")
                        _hpc[str(_h)][_a] += 1
                    _ep_lines: list[str] = []
                    for _ent in dict.fromkeys(accessed_entities):
                        _attrs = _hpc.get(_ent, {})
                        if _attrs:
                            _parts = [f"{a}({c})" for a, c in sorted(_attrs.items())]
                            _ep_lines.append(f"  {_ent}: {', '.join(_parts)}")
                        else:
                            _ep_lines.append(
                                f"  {_ent}: (tail-only — no outgoing attrs; "
                                "use a start entity that has this entity as a tail instead)"
                            )
                    if _ep_lines:
                        entity_presence_hint = (
                            " Entity attr presence in current subgraph:\n"
                            + "\n".join(_ep_lines[:8])
                        )

                code_hint = (
                    f"[CODE_HINT] Empty result: no answers collected. "
                    f"Re-read schema for correct attribute names, or traverse one more hop through CVT."
                    f"{fix_hint}{entity_presence_hint}\n"
                )

        out = io.StringIO()
        if code_hint: out.write(code_hint)
        if stdout_output:
            out.write("==== Standard Output ====\n")
            out.write(stdout_output + "\n")

        MAX_ANSWER_DISPLAY = 20
        out.write("ANSWER: ")
        ans_list = []
        if isinstance(res_obj, dict):
            if "detailed_results" in res_obj:
                ans_list.extend([v.get("_name") for v in res_obj["detailed_results"].values() if v.get("_name")])
            if "direct_results" in res_obj:
                for x in res_obj["direct_results"]:
                    ans_list.extend(x if isinstance(x, list) else [x])
        import json as _json
        total_count = len(ans_list)
        display_list = ans_list[:MAX_ANSWER_DISPLAY]
        out.write(_json.dumps(display_list, ensure_ascii=False))
        if total_count > MAX_ANSWER_DISPLAY:
            out.write(f" (showing {MAX_ANSWER_DISPLAY} of {total_count} results)")
        out.write("\n")

        final_output = out.getvalue()
        if len(final_output) > MAX_OUTPUT_LEN:
            final_output = final_output[:MAX_OUTPUT_LEN] + "\n...[Output truncated]"

        return final_output
    finally:
        for p in [data_path, script_path, res_path]:
            try: os.remove(p)
            except: pass
