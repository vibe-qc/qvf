#!/usr/bin/env python3
"""Kind catalogue rendering used by gen_kinds.py (Apache-2.0).

Renders ``docs/kinds.md``: one entry per canonical section kind, in the order
of ``registry.json``, with its members, section-level fields, payload fields,
fixed units and an example taken from the must-pass conformance corpus. Every
fact comes from ``spec/qvf_manifest.schema.json``, ``registry.json`` and the
corpus archives, so ``gen_kinds.py --check`` keeps the page from drifting.
Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from typing import Any

CORPUS_DIR = os.path.join("conformance", "corpus")

#: Section properties every kind shares (``$defs/Section``); listed once in
#: the page introduction rather than under each kind.
COMMON_FIELDS = ("id", "kind", "members")

#: Abbreviation limits for corpus examples: an array keeps its first
#: EXAMPLE_ITEMS items, unless it holds at most SCALAR_ITEMS scalars.
EXAMPLE_ITEMS = 3
SCALAR_ITEMS = 8
EXAMPLE_DEPTH = 4
EXAMPLE_LINES = 60


def _anchor(kind: str) -> str:
    return "kind-" + re.sub(r"[^a-z0-9]+", "-", kind.lower()).strip("-")


def _def_anchor(name: str) -> str:
    return "def-" + name.lower()


def _cell(text: str) -> str:
    """One Markdown table cell: whitespace collapsed, pipes escaped."""
    return " ".join(str(text).split()).replace("|", "\\|")


class Catalogue:
    def __init__(self, schema: dict, model: Any, root: str) -> None:
        self.defs: dict = schema["$defs"]
        self.model = model
        self.root = root
        self.archives = self._load_corpus()
        self.linked: set[str] = set()

    def _is_object(self, name: str) -> bool:
        target = self.defs[name]
        return target.get("type") == "object" or "properties" in target

    def _refs(self, node: Any) -> list[str]:
        """Every ``$defs`` name a schema node refers to, at any depth."""
        out: list[str] = []
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                out.append(self._def_name(ref))
            for v in node.values():
                out += self._refs(v)
        elif isinstance(node, list):
            for v in node:
                out += self._refs(v)
        return out

    def reachable(self, roots: list[str]) -> list[str]:
        """Object definitions reachable from ``roots`` (excluded themselves),
        alphabetically."""
        seen: set[str] = set()
        todo = list(roots)
        while todo:
            name = todo.pop()
            for ref in self._refs(self.defs[name]):
                if ref not in seen and ref not in roots:
                    seen.add(ref)
                    todo.append(ref)
        return sorted(n for n in seen if self._is_object(n))

    # schema helpers ----------------------------------------------------------
    def _def_name(self, ref: str) -> str:
        return ref.rsplit("/", 1)[1]

    def _merged(self, node: Any) -> tuple[dict, list[str], str]:
        """(properties, required, description) of an object definition,
        following ``$ref`` and ``allOf``. Later parts win on a field."""
        props: dict = {}
        required: list[str] = []
        desc = ""
        if not isinstance(node, dict):
            return props, required, desc
        parts = []
        if "$ref" in node:
            parts.append(self.defs[self._def_name(node["$ref"])])
        parts += node.get("allOf", [])
        for part in parts:
            p, r, d = self._merged(part)
            props.update(p)
            required += r
            desc = desc or d
        props.update(node.get("properties", {}))
        required += node.get("required", [])
        return props, list(dict.fromkeys(required)), node.get("description", desc)

    def type_of(self, node: Any) -> str:
        """A compact human summary of a property schema."""
        if not isinstance(node, dict):
            return "any"
        if "$ref" in node and len(node) <= 2:
            name = self._def_name(node["$ref"])
            if name in self.linked:
                return f"[`{name}`](#{_def_anchor(name)})"
            if self._is_object(name):
                return f"`{name}`"
            return self.type_of(self.defs[name])
        if "const" in node:
            return f"const `{json.dumps(node['const'])}`"
        if "enum" in node:
            values = " | ".join(f"`{json.dumps(v)}`" for v in node["enum"])
            return f"one of {values}" if len(node["enum"]) <= 8 else \
                f"one of {len(node['enum'])} values"
        for key in ("oneOf", "anyOf"):
            if key in node:
                alts = list(dict.fromkeys(self.type_of(a) for a in node[key]))
                return " or ".join(alts)
        if "allOf" in node:
            refs = [p for p in node["allOf"] if isinstance(p, dict) and "$ref" in p]
            if refs:
                return self.type_of(refs[0])
        t = node.get("type")
        if isinstance(t, list):
            return " or ".join(t)
        if t == "array":
            items = node.get("items")
            inner = self.type_of(items) if isinstance(items, dict) else "any"
            lo, hi = node.get("minItems"), node.get("maxItems")
            size = (f"[{lo}]" if lo is not None and lo == hi else
                    f"[{lo or 0}..{'' if hi is None else hi}]" if lo or hi else "")
            return f"array{size} of {inner}"
        if t:
            return str(t)
        if "properties" in node:
            return "object"
        return "any"

    def _fields_table(self, props: dict, required: list[str],
                      skip: tuple = ()) -> list[str]:
        rows = [k for k in props if k not in skip]
        if not rows:
            return []
        out = ["| Field | Required | Type | Description |", "|---|---|---|---|"]
        for name in rows:
            node = props[name]
            desc = node.get("description", "") if isinstance(node, dict) else ""
            if not desc and isinstance(node, dict) and "$ref" in node:
                desc = self.defs[self._def_name(node["$ref"])].get("description", "")
            out.append(f"| `{name}` | {'yes' if name in required else ''} | "
                       f"{_cell(self.type_of(node))} | {_cell(desc)} |")
        return out

    # corpus --------------------------------------------------------------------
    def _load_corpus(self) -> list[tuple[str, dict, dict]]:
        """(archive name, manifest, {member path: bytes}) of each corpus
        archive, read eagerly so no archive stays open."""
        folder = os.path.join(self.root, CORPUS_DIR)
        out = []
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".qvf"):
                continue
            with zipfile.ZipFile(os.path.join(folder, name)) as zf:
                files = {n: zf.read(n) for n in zf.namelist() if n.endswith(".json")}
            out.append((name, json.loads(files["manifest.json"]), files))
        return out

    def _example_archive(self, kind: str):
        """The corpus archive that best shows ``kind``: one named after the
        kind, else the one with the fewest sections, then the smallest
        manifest (ties by name). Archives
        about deprecated or legacy spellings never serve as examples."""
        stem = kind.replace(".", "_")
        best = None
        for name, manifest, files in self.archives:
            if "deprecated" in name or "legacy" in name:
                continue
            sections = manifest.get("sections", [])
            hits = [s for s in sections if s.get("kind") == kind]
            if not hits:
                continue
            key = (name[:-4] != stem, len(sections), len(files["manifest.json"]), name)
            if best is None or key < best[0]:
                best = (key, name, hits[0], files)
        return best

    @staticmethod
    def _abbreviate(value: Any, depth: int = 0) -> Any:
        if isinstance(value, list):
            if depth >= EXAMPLE_DEPTH:
                return [f"… {len(value)} items"] if value else []
            if len(value) <= SCALAR_ITEMS and not any(isinstance(v, (list, dict))
                                                      for v in value):
                return value
            head = [Catalogue._abbreviate(v, depth + 1) for v in value[:EXAMPLE_ITEMS]]
            if len(value) > EXAMPLE_ITEMS:
                head.append(f"… {len(value) - EXAMPLE_ITEMS} more")
            return head
        if isinstance(value, dict):
            if depth >= EXAMPLE_DEPTH:
                return {"…": f"{len(value)} keys"}
            return {k: Catalogue._abbreviate(v, depth + 1) for k, v in value.items()}
        return value

    @staticmethod
    def _dumps(value: Any, indent: str = "") -> str:
        """JSON with two-space indentation, keeping an array or object of
        scalars on one line when it fits."""
        inner = indent + "  "
        if isinstance(value, (list, dict)) and value:
            items = value.items() if isinstance(value, dict) else value
            flat = all(not isinstance(v, (list, dict)) or not v
                       for v in (value.values() if isinstance(value, dict) else value))
            if flat:
                one = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
                if len(indent) + len(one) <= 88:
                    return one
            if isinstance(value, dict):
                parts = [f"{inner}{json.dumps(k, ensure_ascii=False)}: "
                         f"{Catalogue._dumps(v, inner)}" for k, v in items]
                return "{\n" + ",\n".join(parts) + "\n" + indent + "}"
            parts = [inner + Catalogue._dumps(v, inner) for v in items]
            return "[\n" + ",\n".join(parts) + "\n" + indent + "]"
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _json_block(value: Any) -> list[str]:
        lines = Catalogue._dumps(value).splitlines()
        if len(lines) > EXAMPLE_LINES:
            lines = lines[:EXAMPLE_LINES] + [f"… {len(lines) - EXAMPLE_LINES} more lines"]
        return ["```json", *lines, "```"]

    # rendering -------------------------------------------------------------------
    def kind_entry(self, entry: dict) -> list[str]:
        kind = entry["kind"]
        section = self.defs[entry["def"]]
        props, required, desc = self._merged(section)
        out = [f'<a id="{_anchor(kind)}"></a>', "", f"## `{kind}`", ""]
        out.append(f"Schema definition: `$defs/{entry['def']}`.")
        if desc:
            out += ["", " ".join(desc.split())]

        out += ["", "**Members**", "",
                "| Role | Required | Format | dtypes | Rank | Payload |",
                "|---|---|---|---|---|---|"]
        for role in entry["roles"]:
            name = f"`{role['role']}`" + (" (pattern)" if role["pattern"] else "")
            dtypes = ", ".join(f"`{d}`" for d in role["dtypes"])
            if role["format"] != "binary":
                rank = ""
            elif role["max_rank"] < 0:
                rank = f"≥ {role['min_rank']}"
            elif role["min_rank"] == role["max_rank"]:
                rank = str(role["min_rank"])
            else:
                rank = f"{role['min_rank']}–{role['max_rank']}"
            payload = (f"[`{role['payload_def']}`](#{_def_anchor(role['payload_def'])})"
                       if role["payload_def"] else "")
            out.append(f"| {_cell(name)} | {'yes' if role['required'] else ''} | "
                       f"{role['format']} | {dtypes} | {rank} | {payload} |")
        if entry["allow_extra_members"]:
            out += ["", "Other member roles are allowed."]

        fields = self._fields_table(props, required, COMMON_FIELDS)
        if fields:
            out += ["", "**Section fields**", "", *fields]

        example = self._example_archive(kind)
        if example is not None:
            _, archive, sec, files = example
            out += ["", f"**Example** (from `conformance/corpus/{archive}`, "
                        "long arrays shortened)", "",
                    "Manifest section:", "", *self._json_block(sec)]
            for role in entry["roles"]:
                member = sec.get("members", {}).get(role["role"])
                if not role["payload_def"] or not isinstance(member, dict):
                    continue
                payload = json.loads(files[member["path"]])
                out += ["", f"`{role['role']}` payload (`{member['path']}`):", "",
                        *self._json_block(self._abbreviate(payload))]
        return out

    def def_entry(self, name: str, kinds: list[str]) -> list[str]:
        props, required, desc = self._merged(self.defs[name])
        out = [f'<a id="{_def_anchor(name)}"></a>', "", f"### `{name}`"]
        if kinds:
            used = ", ".join(f"[`{k}`](#{_anchor(k)})" for k in kinds)
            out += ["", f"Used by: {used}."]
        if desc:
            out += ["", " ".join(desc.split())]
        fields = self._fields_table(props, required)
        if fields:
            out += ["", *fields]
        fixed = dict(self.model.fixed_units).get(name)
        if fixed:
            units = ", ".join(f"`{k}` = `{v}`" for k, v in fixed)
            out += ["", f"Fixed units: {units}."]
        return out

    def render(self, generated_note: str, regen_note: str) -> str:
        m = self.model
        users: dict[str, list[str]] = {}
        for kind, _role, defname in m.payload_defs:
            users.setdefault(defname, [])
            if kind not in users[defname]:
                users[defname].append(kind)
        section_defs = [e["def"] for e in m.kinds] + ["Section"]
        nested = [n for n in self.reachable(sorted(users) + section_defs)
                  if n not in users and not n.endswith(("Member", "Binary"))]
        self.linked = set(users) | set(nested)
        out = [f"<!-- {generated_note}. -->", "", "# QVF kind catalogue", "",
               f"This page lists every canonical section kind of QVF version "
               f"{m.qvf_version}, in the order of `registry.json`. It is generated "
               f"from the [schema](../spec/qvf_manifest.schema.json), the "
               f"[registry](../registry.json) and the "
               f"[conformance corpus](../conformance/corpus); the "
               f"[specification](../spec/qvf-format-spec.md) is normative and wins "
               f"where this summary is shorter. {regen_note}", "",
               "Every section also carries the common fields of `$defs/Section`:", "",
               *self._fields_table(*self._merged(self.defs["Section"])[:2]),
               "", "Member formats: *json* is a JSON member checked against its payload "
               "definition, *binary* is a raw little-endian array with the listed "
               "dtypes and rank, *opaque* is a binary member without a dtype.",
               "", "## Kinds", ""]
        for entry in m.kinds:
            out.append(f"- [`{entry['kind']}`](#{_anchor(entry['kind'])})")
        for entry in m.kinds:
            out += ["", *self.kind_entry(entry)]
        out += ["", "## Payload definitions", "",
                "The JSON payload definitions named in the member tables, in "
                "alphabetical order."]
        for name in sorted(users):
            out += ["", *self.def_entry(name, users[name])]
        out += ["", "## Other definitions", "",
                "The object definitions the fields above refer to, in "
                "alphabetical order."]
        for name in nested:
            out += ["", *self.def_entry(name, [])]
        return "\n".join(out) + "\n"


def render(schema: dict, model: Any, root: str, generated_note: str,
           regen_note: str) -> str:
    return Catalogue(schema, model, root).render(generated_note, regen_note)
