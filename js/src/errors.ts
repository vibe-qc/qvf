/**
 * Error type of the reader.
 *
 * `code` is a finding code from the specification's Appendix B (for example
 * `E_ZIP_UNREADABLE`), so a caller can branch on it exactly as it matches a
 * validation finding. The message starts with the code, like the messages of
 * the Python and C++ readers.
 */
export class QvfError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(`${code}: ${message}`);
    this.name = "QvfError";
    this.code = code;
  }
}
