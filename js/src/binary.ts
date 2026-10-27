/**
 * Binary members: dtype and shape checks (spec § 4.2) and decoding of
 * little-endian bytes into typed arrays.
 */

import { DTYPE_ITEMSIZE, type BinaryArray, type DType, type TypedArray } from "./model.js";

/** Whether the host stores multi-byte numbers least-significant byte first. */
const HOST_IS_LITTLE_ENDIAN = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;

/** Whether `name` is one of the dtype names of spec § 4.2. */
export function isDType(name: unknown): name is DType {
  return typeof name === "string" && Object.hasOwn(DTYPE_ITEMSIZE, name);
}

/** Whether `shape` is a list of non-negative integers. */
export function isShape(shape: unknown): shape is number[] {
  return (
    Array.isArray(shape) && shape.every((d) => typeof d === "number" && Number.isInteger(d) && d >= 0)
  );
}

/** `itemsize * prod(shape)`, exact for any shape (an empty shape is a scalar). */
export function expectedByteLength(itemsize: number, shape: readonly number[]): bigint {
  let n = BigInt(itemsize);
  for (const d of shape) n *= BigInt(d);
  return n;
}

/**
 * A member spec's declared `size` against the uncompressed size its ZIP entry
 * records (spec § 4.2), checked before the member is read: `null` when `size`
 * is absent or equal, otherwise the finding code (`E_MEMBER_MALFORMED` when it
 * is not a non-negative integer, `E_BINARY_SIZE` when it differs) and a
 * message.
 */
export function declaredSizeProblem(
  spec: Readonly<Record<string, unknown>>,
  entrySize: number,
  name: string,
): ["E_MEMBER_MALFORMED" | "E_BINARY_SIZE", string] | null {
  if (!Object.hasOwn(spec, "size")) return null;
  const size = spec.size;
  if (typeof size !== "number" || !Number.isInteger(size) || size < 0) {
    return [
      "E_MEMBER_MALFORMED",
      `member '${name}': size must be a non-negative integer, got ${JSON.stringify(size) ?? String(size)}`,
    ];
  }
  if (size !== entrySize) {
    return [
      "E_BINARY_SIZE",
      `member '${name}': declared size ${size} != ${entrySize} bytes recorded in the ZIP central directory`,
    ];
  }
  return null;
}

function swapBytes(bytes: Uint8Array, itemsize: number): void {
  for (let i = 0; i + itemsize <= bytes.length; i += itemsize) {
    for (let a = i, b = i + itemsize - 1; a < b; a++, b--) {
      const t = bytes[a]!;
      bytes[a] = bytes[b]!;
      bytes[b] = t;
    }
  }
}

/**
 * Decode little-endian `bytes` as a flat typed array of `dtype`.
 *
 * The result is a view on `bytes` when its offset is aligned to the element
 * size and the host is little-endian; otherwise the bytes are copied first
 * (and byte-swapped on a big-endian host). The length of `bytes` must be a
 * multiple of the element size.
 */
export function toTypedArray(dtype: DType, bytes: Uint8Array): TypedArray {
  const itemsize = DTYPE_ITEMSIZE[dtype];
  if (bytes.length % itemsize !== 0) {
    throw new RangeError(`${bytes.length} bytes is not a multiple of the ${dtype} size ${itemsize}`);
  }
  let source = bytes;
  const aligned = bytes.byteOffset % itemsize === 0;
  if (!aligned || (!HOST_IS_LITTLE_ENDIAN && itemsize > 1)) {
    source = new Uint8Array(bytes); // a copy in a fresh buffer: offset 0, safe to byte-swap
    if (!HOST_IS_LITTLE_ENDIAN && itemsize > 1) swapBytes(source, itemsize);
  }
  const buffer = source.buffer;
  const offset = source.byteOffset;
  const count = source.length / itemsize;
  switch (dtype) {
    case "int8":
      return new Int8Array(buffer, offset, count);
    case "int16":
      return new Int16Array(buffer, offset, count);
    case "int32":
      return new Int32Array(buffer, offset, count);
    case "int64":
      return new BigInt64Array(buffer, offset, count);
    case "uint8":
      return new Uint8Array(buffer, offset, count);
    case "uint16":
      return new Uint16Array(buffer, offset, count);
    case "uint32":
      return new Uint32Array(buffer, offset, count);
    case "uint64":
      return new BigUint64Array(buffer, offset, count);
    case "float32":
      return new Float32Array(buffer, offset, count);
    case "float64":
      return new Float64Array(buffer, offset, count);
  }
}

/** Decode a binary member's bytes with its declared dtype and shape. */
export function decodeBinary(dtype: DType, shape: number[], bytes: Uint8Array): BinaryArray {
  return { dtype, shape, data: toTypedArray(dtype, bytes) } as BinaryArray;
}
