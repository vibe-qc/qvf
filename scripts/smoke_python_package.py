"""Exercise an installed base wheel outside the source tree (stdlib only)."""
import importlib.metadata
import importlib.resources
import json
from pathlib import Path
import struct
import sys
import tempfile

from qvf import Reader, Section, Writer, __version__


def main():
    version = importlib.metadata.version("qvf-writer")
    assert __version__ == version, (__version__, version)
    import qvf
    assert Path(qvf.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), qvf.__file__
    schema = importlib.resources.files("qvf").joinpath("schema/qvf_manifest.schema.json")
    assert json.loads(schema.read_text(encoding="utf-8"))["$schema"]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "density.qvf"
        with Writer(path, program="package-smoke", version=version) as writer:
            writer.add_section(Section(id="rho", kind="volume.density", members={}))
            writer.add_json("rho", "grid", {
                "origin": [0, 0, 0],
                "voxel_vectors": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "shape": [1, 1, 2],
            })
            with writer.begin_binary("rho", "data", "float64", [1, 1, 2]) as member:
                member.write(struct.pack("<2d", 0.5, 0.25))
        with Reader(path) as reader:
            assert reader.tensor("rho", "data").tolist() == [[[0.5, 0.25]]]
            assert reader.validate()["ok"]
    print(f"Installed qvf-writer {version}: base read/write/validate/schema PASS")


if __name__ == "__main__":
    main()
