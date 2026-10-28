Python validation reports and both validation CLIs now identify the archive
format, reader/toolkit and bundled schema digest, distinguish skipped schema
checks, and explain unsupported archive format versions. Validation rules
remain unchanged; null optional job basis/functional metadata is covered by
a focused regression using the existing job fixture.
