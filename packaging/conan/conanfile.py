"""Conan 2 local recipe for the committed QVF C/C++ toolkit source."""
from pathlib import Path
import subprocess

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import check_min_cppstd
from conan.tools.cmake import CMake, CMakeToolchain, cmake_layout
from conan.tools.files import copy


class QvfRecipe(ConanFile):
    name = "qvf"
    package_type = "library"
    license = "Apache-2.0"
    url = "https://github.com/vibe-qc/qvf"
    description = "QVF archive reader, writer and validator with C and C++ APIs"
    topics = ("qvf", "quantum-chemistry", "archive")
    required_conan_version = ">=2.20 <3"
    settings = "os", "arch", "compiler", "build_type"
    options = {"shared": [True, False], "fPIC": [True, False]}
    default_options = {"shared": False, "fPIC": True}

    def set_version(self):
        root = Path(self.recipe_folder).resolve().parents[1]
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
        if self.version is not None and str(self.version) != version:
            raise ConanInvalidConfiguration("The package version must match QVF VERSION")
        self.version = version

    def export_sources(self):
        # Export immutable Git blobs, not a glob of the contributor's checkout.
        # This avoids caches, untracked files, checkout filters and symlinks.
        root = Path(self.recipe_folder).resolve().parents[1]
        paths = ["LICENSE", "NOTICE", "VERSION", "cpp/CMakeLists.txt", "cpp/include",
                 "cpp/src", "cpp/cmake", "cpp/qvf_single.hpp"]
        def git(*args):
            return subprocess.check_output(["git", "-C", str(root), *args])
        try:
            if Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != root:
                raise ConanInvalidConfiguration("Use this recipe in the QVF Git checkout")
            commit = git("rev-parse", "--verify", "HEAD").decode().strip()
            if not git("ls-tree", commit, "--", "packaging/conan/conanfile.py"):
                raise ConanInvalidConfiguration("Commit the Conan recipe before packaging")
            if git("diff", "--name-only", "--no-ext-diff", "--no-textconv", commit,
                   "--", *paths, "packaging/conan"):
                raise ConanInvalidConfiguration("Commit QVF source and recipe changes before packaging")
            records = git("ls-tree", "-rz", commit, "--", *paths)
            for record in filter(None, records.split(b"\0")):
                header, raw_path = record.split(b"\t", 1)
                mode, kind, oid = header.decode().split()
                if mode not in {"100644", "100755"} or kind != "blob":
                    raise ConanInvalidConfiguration("Only regular committed source files may be packaged")
                target = Path(self.export_sources_folder) / raw_path.decode()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(git("cat-file", "blob", oid))
                target.chmod(int(mode, 8) & 0o777)
        except (OSError, subprocess.CalledProcessError) as error:
            raise ConanInvalidConfiguration("A readable QVF Git checkout is required for local packaging") from error

    def config_options(self):
        if self.settings.os == "Windows":
            self.options.rm_safe("fPIC")

    def configure(self):
        if self.options.shared:
            self.options.rm_safe("fPIC")

    def validate(self):
        if self.settings.compiler.get_safe("cppstd"):
            check_min_cppstd(self, "17")

    def layout(self):
        cmake_layout(self)

    def generate(self):
        toolchain = CMakeToolchain(self)
        toolchain.user_presets_path = False
        toolchain.variables["QVF_BUILD_SHARED"] = bool(self.options.shared)
        toolchain.variables["QVF_BUILD_TESTS"] = False
        toolchain.variables["QVF_BUILD_EXAMPLES"] = False
        toolchain.variables["QVF_FORTRAN"] = False
        toolchain.variables["QVF_FUZZ"] = False
        toolchain.variables["CMAKE_INSTALL_LIBDIR"] = "lib"
        toolchain.generate()

    def build(self):
        cmake = CMake(self)
        cmake.configure(build_script_folder="cpp")
        cmake.build()

    def package(self):
        CMake(self).install()
        for name in ("LICENSE", "NOTICE"):
            copy(self, name, src=self.source_folder, dst=str(Path(self.package_folder) / "licenses"))

    def package_info(self):
        self.cpp_info.libs = ["qvf"]
        # Reuse upstream targets, including C++17 and QVF_SHARED usage rules.
        self.cpp_info.set_property("cmake_find_mode", "none")
        self.cpp_info.builddirs = ["lib/cmake/qvf"]
        self.cpp_info.set_property("pkg_config_name", "qvf")
        if self.options.shared:
            self.cpp_info.defines = ["QVF_SHARED=1"]
