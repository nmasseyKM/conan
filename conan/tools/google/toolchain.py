import textwrap

from jinja2 import Template

from conan.tools._check_build_profile import check_using_build_profile
from conan.tools._compilers import cppstd_flag
from conan.tools.apple import to_apple_arch, is_apple_os
from conan.tools.build.cross_building import cross_building
from conan.tools.files import save


def _get_cpu_name(conanfile):
    host_os = conanfile.settings.get_safe('os').lower()
    host_arch = conanfile.settings.get_safe('arch')
    if is_apple_os(conanfile):
        host_os = "darwin" if host_os == "macos" else host_os
        host_arch = to_apple_arch(conanfile)
    # FIXME: Probably it's going to fail, but let's try it because it normally follows this syntax
    return f"{host_os}_{host_arch}"


# FIXME: In the future, it could be BazelPlatform instead? Check https://bazel.build/concepts/platforms
class BazelToolchain:
    """
    Creates a simple conan_bzl.rc file which defines a conan-config configuration with all the
    attributes defined by the consumer. Bear in mind that this is not a complete toolchain, it
    only fills some common CLI attributes and save them in a *.rc file.

    Important: Maybe, this toolchain should create a new Conan platform with the user
    constraints, but it's not the goal for now as Bazel has tons of platforms and toolchains
    already available in its bazel_tools repo. For now, it only admits a list of platforms defined
    by the user.
    More information related:
        * Toolchains: https://bazel.build/extending/toolchains (deprecated)
        * Platforms: https://bazel.build/concepts/platforms (new default since Bazel 7.x)
        * Migrating to platforms: https://bazel.build/concepts/platforms
        * Issue related: https://github.com/bazelbuild/bazel/issues/6516

    Others:
        CROOSTOOL: https://github.com/bazelbuild/bazel/blob/cb0fb033bad2a73e0457f206afb87e195be93df2/tools/cpp/CROSSTOOL
        Cross-compiling with Bazel: https://ltekieli.com/cross-compiling-with-bazel/
        bazelrc files: https://bazel.build/run/bazelrc
        CLI options: https://bazel.build/reference/command-line-reference
        User manual: https://bazel.build/docs/user-manual
    """

    bazelrc_name = "conan_bzl.rc"
    bazelrc_config = "conan-config"
    bazelrc_template = textwrap.dedent("""
    # Automatic bazelrc file created by Conan
    {% if copt %}build:conan-config {{copt}}{% endif %}
    {% if conlyopt %}build:conan-config {{conlyopt}}{% endif %}
    {% if cxxopt %}build:conan-config {{cxxopt}}{% endif %}
    {% if linkopt %}build:conan-config {{linkopt}}{% endif %}
    {% if force_pic %}build:conan-config --force_pic={{force_pic}}{% endif %}
    {% if dynamic_mode %}build:conan-config --dynamic_mode={{dynamic_mode}}{% endif %}
    {% if compilation_mode %}build:conan-config --compilation_mode={{compilation_mode}}{% endif %}
    {% if compiler %}build:conan-config --compiler={{compiler}}{% endif %}
    {% if cpu %}build:conan-config --cpu={{cpu}}{% endif %}
    {% if crosstool_top %}build:conan-config --crosstool_top={{crosstool_top}}{% endif %}""")

    def __init__(self, conanfile, namespace=None):
        self._conanfile = conanfile
        # TODO: Remove namespace and check_using_build_profile in Conan 2.x
        if namespace:
            self._conanfile.output.warning("In BazelToolchain() call, namespace param has been "
                                        "deprecated as it's not used anymore.")
        check_using_build_profile(self._conanfile)

        # Flags
        # TODO: Should we read the buildenv to get flags?
        self.extra_cxxflags = []
        self.extra_cflags = []
        self.extra_ldflags = []
        self.extra_defines = []

        # Bazel build parameters
        shared = self._conanfile.options.get_safe("shared")
        fpic = self._conanfile.options.get_safe("fPIC")
        self.force_pic = fpic if (not shared and fpic is not None) else None
        # FIXME: Keeping this option but it's not working as expected. It's not creating the shared
        #        libraries at all.
        self.dynamic_mode = "fully" if shared else "off"
        self.cppstd = cppstd_flag(self._conanfile.settings)
        self.copt = []
        self.conlyopt = []
        self.cxxopt = []
        self.linkopt = []
        self.compilation_mode = {'Release': 'opt', 'Debug': 'dbg'}.get(
            self._conanfile.settings.get_safe("build_type")
        )
        # Be aware that this parameter does not admit a compiler absolute path
        # If you want to add it, you will have to use a specific Bazel toolchain
        self.compiler = None
        # cpu is the target architecture, and it's a bit tricky. If it's not a cross-compilation,
        # let Bazel guess it.
        self.cpu = None
        # TODO: cross-compilation process is so powerless. Needs to use the new platforms.
        if cross_building(self._conanfile):
            # Bazel is using those toolchains/platforms by default.
            # It's better to let it configure the project in that case
            self.cpu = _get_cpu_name(conanfile)
        # This is itself a toolchain but just in case
        self.crosstool_top = None
        # TODO: Have a look at https://bazel.build/reference/be/make-variables
        # FIXME: Missing host_xxxx options. When are they needed? Cross-compilation?

    @staticmethod
    def _filter_list_empty_fields(v):
        return list(filter(bool, v))

    @property
    def cxxflags(self):
        ret = [self.cppstd]
        conf_flags = self._conanfile.conf.get("tools.build:cxxflags", default=[], check_type=list)
        ret = ret  + self.extra_cxxflags + conf_flags
        return self._filter_list_empty_fields(ret)

    @property
    def cflags(self):
        conf_flags = self._conanfile.conf.get("tools.build:cflags", default=[], check_type=list)
        ret = self.extra_cflags + conf_flags
        return self._filter_list_empty_fields(ret)

    @property
    def ldflags(self):
        conf_flags = self._conanfile.conf.get("tools.build:sharedlinkflags", default=[],
                                              check_type=list)
        conf_flags.extend(self._conanfile.conf.get("tools.build:exelinkflags", default=[],
                                                   check_type=list))
        linker_scripts = self._conanfile.conf.get("tools.build:linker_scripts", default=[], check_type=list)
        conf_flags.extend(["-T'" + linker_script + "'" for linker_script in linker_scripts])
        ret = self.extra_ldflags + conf_flags
        return self._filter_list_empty_fields(ret)

    def _context(self):
        return {
            "copt": " ".join(f"--copt={flag}" for flag in self.copt),
            "conlyopt": " ".join(f"--conlyopt={flag}" for flag in (self.conlyopt + self.cflags)),
            "cxxopt": " ".join(f"--cxxopt={flag}" for flag in (self.cxxopt + self.cxxflags)),
            "linkopt": " ".join(f"--linkopt={flag}" for flag in (self.linkopt + self.ldflags)),
            "force_pic": self.force_pic,
            "dynamic_mode": self.dynamic_mode,
            "compilation_mode": self.compilation_mode,
            "compiler": self.compiler,
            "cpu": self.cpu,
            "crosstool_top": self.crosstool_top,
        }

    @property
    def _content(self):
        context = self._context()
        content = Template(self.bazelrc_template).render(context)
        return content

    def generate(self):
        # check_duplicated_generator(self, self._conanfile)  # uncomment for Conan 2.x
        save(self._conanfile, BazelToolchain.bazelrc_name, self._content)
