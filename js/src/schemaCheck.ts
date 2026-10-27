/**
 * The table-driven JSON Schema checker of the validator.
 *
 * `scripts/gen_kinds.py` compiles `spec/qvf_manifest.schema.json` into the
 * instruction table of `schemaTable.ts`: one node per schema object, one op
 * per assertion keyword, with shared pools of strings, numbers, JSON literals
 * and compiled patterns. This module interprets that table. It knows nothing
 * about QVF: everything schema-specific is in the table, so a schema change
 * only needs the table regenerated. It is the same interpreter as the C++
 * `cpp/src/qvf_schema_check.hpp`.
 *
 * The errors are the ones the Python reference validator gets from
 * jsonschema's `Draft202012Validator.iter_errors()`: keywords that apply to
 * children (`properties`, `patternProperties`, `additionalProperties` with a
 * schema, `prefixItems`, `items`, `allOf`, `$ref`, `if`/`then`/`else`,
 * `dependentSchemas`) report their children's errors at the children's
 * locations; every other keyword (`oneOf`, `anyOf`, `not` and `contains`
 * among them) reports one error at the instance it applies to. A finding's
 * location is therefore the same JSON pointer in every validator; the
 * messages are worded independently.
 *
 * Patterns run on a small Pike VM over code points (linear time, no
 * `RegExp`), with ECMA-262 semantics: `$` matches only at the end of the
 * string.
 */

import {
  DEFS,
  LISTS,
  NODES,
  NUMBERS,
  Op,
  OPS,
  PAIRS,
  PAYLOAD_DEFS,
  ROOT,
  RX_OPS,
  RX_PROGRAMS,
  RX_RANGES,
  RX_SOURCES,
  RxOp,
  STRINGS,
  TRIPLES,
  TypeBit,
  VALUES,
} from "./schemaTable.js";

/** One schema error. */
export interface SchemaError {
  /** RFC 6901 JSON pointer of the failing value inside the checked document ("" = the document). */
  pointer: string;
  /** The same path unescaped and `/`-joined, as the Python validator prints it. */
  location: string;
  message: string;
}

type Obj = Record<string, unknown>;

const isObject = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const at = (table: readonly number[], i: number): number => table[i] as number;
const str = (i: number): string => STRINGS[i] as string;

/** The JSON literals of the table (const / enum values). */
const LITERALS: readonly unknown[] = VALUES.map((text) => JSON.parse(text) as unknown);

const PAYLOAD_DEF_MAP: ReadonlyMap<string, string> = new Map(
  PAYLOAD_DEFS.map(([kind, role, def]) => [`${kind}\u0000${role}`, def]),
);

/** The `$defs` entry specifying the JSON payload of a (kind, role) member, if any. */
export function payloadDefinition(kind: string, role: string): string | undefined {
  return PAYLOAD_DEF_MAP.get(`${kind}\u0000${role}`);
}

/** JSON equality as jsonschema decides it: booleans are not numbers, values compare deeply. */
export function jsonEqual(a: unknown, b: unknown): boolean {
  if (typeof a === "boolean" || typeof b === "boolean") return a === b;
  if (typeof a === "number" || typeof b === "number") return a === b;
  if (typeof a === "string" || typeof b === "string") return a === b;
  if (a === null || b === null) return a === b;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => jsonEqual(x, b[i]));
  }
  if (isObject(a) && isObject(b)) {
    const keys = Object.keys(a);
    if (keys.length !== Object.keys(b).length) return false;
    return keys.every((k) => Object.hasOwn(b, k) && jsonEqual(a[k], b[k]));
  }
  return false;
}

function show(v: unknown): string {
  let text: string;
  try {
    text = JSON.stringify(v) ?? String(v);
  } catch {
    return "<value>";
  }
  return text.length > 80 ? `${text.slice(0, 77)}...` : text;
}

/** Number of Unicode code points (a surrogate pair is one). */
function codePointCount(s: string): number {
  return Array.from(s).length;
}

function typeMatches(mask: number, v: unknown): boolean {
  if (v === null) return (mask & TypeBit.null) !== 0;
  switch (typeof v) {
    case "boolean":
      return (mask & TypeBit.boolean) !== 0;
    case "string":
      return (mask & TypeBit.string) !== 0;
    case "number":
      return (mask & TypeBit.number) !== 0 || ((mask & TypeBit.integer) !== 0 && Number.isInteger(v));
    case "object":
      return (mask & (Array.isArray(v) ? TypeBit.array : TypeBit.object)) !== 0;
    default:
      return false;
  }
}

function typeNames(mask: number): string {
  return (Object.entries(TypeBit) as Array<[string, number]>)
    .filter(([, bit]) => (mask & bit) !== 0)
    .map(([name]) => `'${name}'`)
    .join(", ");
}

// --- patterns ----------------------------------------------------------------------

function rxClassMatch(code: number, first: number, count: number, c: number): boolean {
  let hit = false;
  for (let k = 0; k < count && !hit; k++) {
    const r = 2 * (first + k);
    hit = c >= at(RX_RANGES, r) && c <= at(RX_RANGES, r + 1);
  }
  return code === RxOp.Class ? hit : !hit;
}

/**
 * True when compiled pattern `rx` matches anywhere in `text` (JSON Schema
 * patterns are unanchored). A Pike VM: every live thread advances in lock
 * step, so the run time is linear in the text and the program.
 */
export function rxSearch(rx: number, text: string): boolean {
  const first = at(RX_PROGRAMS, 2 * rx);
  const count = at(RX_PROGRAMS, 2 * rx + 1);
  const cps = Array.from(text, (ch) => ch.codePointAt(0) as number);
  const mark = new Int32Array(count).fill(-1);
  let step = 0;
  let matched = false;
  let cur: number[] = [];
  const stack: number[] = [];
  const add = (list: number[], start: number, pos: number): void => {
    stack.push(start);
    while (stack.length > 0) {
      const pc = stack.pop() as number;
      if (mark[pc] === step) continue;
      mark[pc] = step;
      const o = 3 * (first + pc);
      const code = at(RX_OPS, o);
      if (code === RxOp.Jump) stack.push(at(RX_OPS, o + 1));
      else if (code === RxOp.Split) stack.push(at(RX_OPS, o + 2), at(RX_OPS, o + 1));
      else if (code === RxOp.LineStart) {
        if (pos === 0) stack.push(pc + 1);
      } else if (code === RxOp.LineEnd) {
        if (pos === cps.length) stack.push(pc + 1);
      } else if (code === RxOp.Match) matched = true;
      else list.push(pc); // Class / NotClass
    }
  };
  add(cur, 0, 0);
  for (let pos = 0; pos < cps.length && !matched; pos++) {
    step++;
    const next: number[] = [];
    const c = cps[pos] as number;
    for (const pc of cur) {
      const o = 3 * (first + pc);
      if (rxClassMatch(at(RX_OPS, o), at(RX_OPS, o + 1), at(RX_OPS, o + 2), c)) add(next, pc + 1, pos + 1);
    }
    add(next, 0, pos + 1); // a match may start at any position
    cur = next;
  }
  return matched;
}

// --- the interpreter ---------------------------------------------------------------

function escapeSegment(s: string): string {
  return s.replaceAll("~", "~0").replaceAll("/", "~1");
}

class Evaluator {
  private readonly path: string[] = [];

  /** Collects errors into `out`; with `null` it only decides validity and stops at the first failure. */
  constructor(private readonly out: SchemaError[] | null) {}

  eval(node: number, v: unknown): boolean {
    const first = at(NODES, 2 * node);
    const count = at(NODES, 2 * node + 1);
    let ok = true;
    for (let i = 0; i < count; i++) {
      if (!this.apply(first + i, first, count, v)) {
        ok = false;
        if (!this.out) return false;
      }
    }
    return ok;
  }

  private static valid(node: number, v: unknown): boolean {
    return new Evaluator(null).eval(node, v);
  }

  private fail(message: string): boolean {
    if (this.out) {
      this.out.push({
        pointer: this.path.map((s) => `/${escapeSegment(s)}`).join(""),
        location: this.path.join("/"),
        message,
      });
    }
    return false;
  }

  /** Evaluate a child value under `node`, one path segment deeper. */
  private descend(node: number, v: unknown, segment: string): boolean {
    if (!this.out) return this.eval(node, v);
    this.path.push(segment);
    const ok = this.eval(node, v);
    this.path.pop();
    return ok;
  }

  /** Whether `key` is named by the node's own Properties or PatternProperties ops. */
  private static declared(first: number, count: number, key: string): boolean {
    for (let i = first; i < first + count; i++) {
      const code = at(OPS, 4 * i);
      const a = at(OPS, 4 * i + 1);
      const b = at(OPS, 4 * i + 2);
      if (code === Op.Properties) {
        for (let k = 0; k < b; k++) if (key === str(at(PAIRS, a + 2 * k))) return true;
      } else if (code === Op.PatternProperties) {
        for (let k = 0; k < b; k++) if (rxSearch(at(PAIRS, a + 2 * k), key)) return true;
      }
    }
    return false;
  }

  private apply(op: number, first: number, count: number, v: unknown): boolean {
    const code = at(OPS, 4 * op);
    const a = at(OPS, 4 * op + 1);
    const b = at(OPS, 4 * op + 2);
    const c = at(OPS, 4 * op + 3);
    const collect = this.out !== null;
    switch (code) {
      case Op.False:
        return this.fail(`False schema does not allow ${show(v)}`);
      case Op.Type:
        return typeMatches(a, v) || this.fail(`${show(v)} is not of type ${typeNames(a)}`);
      case Op.Const:
        return jsonEqual(v, LITERALS[a]) || this.fail(`${VALUES[a]} was expected`);
      case Op.Enum: {
        for (let k = 0; k < b; k++) if (jsonEqual(v, LITERALS[at(LISTS, a + k)])) return true;
        if (!collect) return false;
        const names: string[] = [];
        for (let k = 0; k < b; k++) names.push(VALUES[at(LISTS, a + k)] as string);
        return this.fail(`${show(v)} is not one of [${names.join(", ")}]`);
      }
      case Op.Ref:
        return this.eval(a, v);
      case Op.AllOf: {
        let ok = true;
        for (let k = 0; k < b; k++) {
          if (!this.eval(at(LISTS, a + k), v)) {
            ok = false;
            if (!collect) return false;
          }
        }
        return ok;
      }
      case Op.AnyOf:
        for (let k = 0; k < b; k++) if (Evaluator.valid(at(LISTS, a + k), v)) return true;
        return this.fail(`${show(v)} is not valid under any of the given schemas`);
      case Op.OneOf: {
        let matches = 0;
        for (let k = 0; k < b && matches < 2; k++) if (Evaluator.valid(at(LISTS, a + k), v)) matches++;
        if (matches === 1) return true;
        return this.fail(
          matches === 0
            ? `${show(v)} is not valid under any of the given schemas`
            : `${show(v)} is valid under more than one of the given schemas`,
        );
      }
      case Op.Not:
        return !Evaluator.valid(a, v) || this.fail(`${show(v)} should not be valid under the given schema`);
      case Op.If:
        if (Evaluator.valid(a, v)) return b < 0 || this.eval(b, v);
        return c < 0 || this.eval(c, v);
      case Op.Properties: {
        if (!isObject(v)) return true;
        let ok = true;
        for (let k = 0; k < b; k++) {
          const name = str(at(PAIRS, a + 2 * k));
          if (Object.hasOwn(v, name) && !this.descend(at(PAIRS, a + 2 * k + 1), v[name], name)) {
            ok = false;
            if (!collect) return false;
          }
        }
        return ok;
      }
      case Op.PatternProperties: {
        if (!isObject(v)) return true;
        let ok = true;
        for (let k = 0; k < b; k++) {
          const rx = at(PAIRS, a + 2 * k);
          for (const [key, value] of Object.entries(v)) {
            if (rxSearch(rx, key) && !this.descend(at(PAIRS, a + 2 * k + 1), value, key)) {
              ok = false;
              if (!collect) return false;
            }
          }
        }
        return ok;
      }
      case Op.AdditionalProperties: {
        if (!isObject(v)) return true;
        let ok = true;
        const extras: string[] = [];
        for (const [key, value] of Object.entries(v)) {
          if (Evaluator.declared(first, count, key)) continue;
          if (a < 0) {
            extras.push(`'${key}'`);
            if (!collect) return false;
          } else if (!this.descend(a, value, key)) {
            ok = false;
            if (!collect) return false;
          }
        }
        if (extras.length > 0) return this.fail(`additional properties are not allowed (${extras.join(", ")} unexpected)`);
        return ok;
      }
      case Op.Required: {
        if (!isObject(v)) return true;
        let ok = true;
        for (let k = 0; k < b; k++) {
          const name = str(at(LISTS, a + k));
          if (!Object.hasOwn(v, name)) {
            ok = this.fail(`'${name}' is a required property`);
            if (!collect) return false;
          }
        }
        return ok;
      }
      case Op.DependentRequired: {
        if (!isObject(v)) return true;
        let ok = true;
        for (let k = 0; k < b; k++) {
          const t = a + 3 * k;
          const prop = str(at(TRIPLES, t));
          if (!Object.hasOwn(v, prop)) continue;
          for (let d = 0; d < at(TRIPLES, t + 2); d++) {
            const dep = str(at(LISTS, at(TRIPLES, t + 1) + d));
            if (!Object.hasOwn(v, dep)) {
              ok = this.fail(`'${dep}' is a dependency of '${prop}'`);
              if (!collect) return false;
            }
          }
        }
        return ok;
      }
      case Op.DependentSchemas: {
        if (!isObject(v)) return true;
        let ok = true;
        for (let k = 0; k < b; k++) {
          if (Object.hasOwn(v, str(at(PAIRS, a + 2 * k))) && !this.eval(at(PAIRS, a + 2 * k + 1), v)) {
            ok = false;
            if (!collect) return false;
          }
        }
        return ok;
      }
      case Op.PropertyNames: {
        if (!isObject(v)) return true;
        let ok = true;
        for (const key of Object.keys(v)) {
          if (!this.eval(a, key)) {
            ok = false;
            if (!collect) return false;
          }
        }
        return ok;
      }
      case Op.MinProperties:
        return !isObject(v) || Object.keys(v).length >= a || this.fail(`${show(v)} does not have enough properties`);
      case Op.MaxProperties:
        return !isObject(v) || Object.keys(v).length <= a || this.fail(`${show(v)} has too many properties`);
      case Op.PrefixItems: {
        if (!Array.isArray(v)) return true;
        let ok = true;
        for (let k = 0; k < b && k < v.length; k++) {
          if (!this.descend(at(LISTS, a + k), v[k], String(k))) {
            ok = false;
            if (!collect) return false;
          }
        }
        return ok;
      }
      case Op.Items: {
        if (!Array.isArray(v) || v.length <= b) return true;
        if (a < 0) return this.fail(`expected at most ${b} items, found ${v.length}`);
        let ok = true;
        for (let i = b; i < v.length; i++) {
          if (!this.descend(a, v[i], String(i))) {
            ok = false;
            if (!collect) return false;
          }
        }
        return ok;
      }
      case Op.Contains: {
        if (!Array.isArray(v)) return true;
        let matches = 0;
        for (const item of v) {
          if (!Evaluator.valid(a, item)) continue;
          if (++matches > c && c >= 0) {
            return this.fail(`too many items match the given schema (expected at most ${c})`);
          }
        }
        if (matches >= b) return true;
        return this.fail(
          matches === 0
            ? `${show(v)} does not contain items matching the given schema`
            : `too few items match the given schema (expected at least ${b}, ${matches} matched)`,
        );
      }
      case Op.MinItems:
        return !Array.isArray(v) || v.length >= a || this.fail(`${show(v)} is too short (at least ${a} items)`);
      case Op.MaxItems:
        return !Array.isArray(v) || v.length <= a || this.fail(`${show(v)} is too long (at most ${a} items)`);
      case Op.UniqueItems: {
        if (!Array.isArray(v)) return true;
        for (let i = 0; i < v.length; i++) {
          for (let j = i + 1; j < v.length; j++) {
            if (jsonEqual(v[i], v[j])) return this.fail(`${show(v)} has non-unique elements`);
          }
        }
        return true;
      }
      case Op.Minimum:
      case Op.Maximum:
      case Op.ExclusiveMinimum:
      case Op.ExclusiveMaximum: {
        if (typeof v !== "number") return true;
        const lim = NUMBERS[a] as number;
        if (code === Op.Minimum) return v >= lim || this.fail(`${show(v)} is less than the minimum of ${lim}`);
        if (code === Op.Maximum) return v <= lim || this.fail(`${show(v)} is greater than the maximum of ${lim}`);
        if (code === Op.ExclusiveMinimum) {
          return v > lim || this.fail(`${show(v)} is less than or equal to the minimum of ${lim}`);
        }
        return v < lim || this.fail(`${show(v)} is greater than or equal to the maximum of ${lim}`);
      }
      case Op.MultipleOf: {
        if (typeof v !== "number") return true;
        const d = NUMBERS[a] as number;
        const bad = Number.isInteger(v) && Number.isInteger(d) ? v % d !== 0 : !Number.isInteger(v / d);
        return !bad || this.fail(`${show(v)} is not a multiple of ${d}`);
      }
      case Op.MinLength:
        return (
          typeof v !== "string" ||
          codePointCount(v) >= a ||
          this.fail(a === 1 ? `${show(v)} should be non-empty` : `${show(v)} is too short (at least ${a} characters)`)
        );
      case Op.MaxLength:
        return typeof v !== "string" || codePointCount(v) <= a || this.fail(`${show(v)} is too long (at most ${a} characters)`);
      case Op.Pattern:
        return typeof v !== "string" || rxSearch(a, v) || this.fail(`${show(v)} does not match '${RX_SOURCES[a]}'`);
      default:
        return this.fail(`unknown schema opcode ${code}`);
    }
  }
}

function checkNode(node: number, doc: unknown): SchemaError[] {
  const out: SchemaError[] = [];
  new Evaluator(out).eval(node, doc);
  return out;
}

/** Every schema error of a `manifest.json` document against the root schema. */
export function checkManifest(manifest: unknown): SchemaError[] {
  return checkNode(ROOT, manifest);
}

/** Every schema error of a payload against the `$defs` entry `def` (nothing for an unknown entry). */
export function checkDefinition(def: string, doc: unknown): SchemaError[] {
  const node = Object.hasOwn(DEFS, def) ? DEFS[def] : undefined;
  return node === undefined ? [] : checkNode(node, doc);
}
