import os

from conans.cli.command import conan_command, COMMAND_GROUPS, OnceArgument
from conans.cli.commands.install import _get_conanfile_path
from conans.cli.common import get_lockfile, add_reference_args
from conans.cli.output import ConanOutput


def common_args_export(parser):
    parser.add_argument("path", help="Path to a folder containing a recipe (conanfile.py)")
    add_reference_args(parser)


@conan_command(group=COMMAND_GROUPS['creator'])
def export(conan_api, parser, *args):
    """
    Export recipe to the Conan package cache
    """
    common_args_export(parser)
    parser.add_argument("-l", "--lockfile", action=OnceArgument,
                        help="Path to a lockfile.")
    parser.add_argument("--lockfile-partial", action="store_true",
                        help="Do not raise an error if some dependency is not found in lockfile")

    args = parser.parse_args(*args)

    cwd = os.getcwd()
    path = _get_conanfile_path(args.path, cwd, py=True)
    lockfile = get_lockfile(lockfile_path=args.lockfile, cwd=cwd, conanfile_path=path,
                            partial=args.lockfile_partial)
    ref = conan_api.export.export(path=path,
                                  name=args.name, version=args.version,
                                  user=args.user, channel=args.channel,
                                  lockfile=lockfile)
    ConanOutput().success("Exported recipe: {}".format(ref.repr_humantime()))