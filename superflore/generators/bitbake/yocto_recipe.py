# -*- coding: utf-8 -*-
#
# Copyright (c) 2016 David Bensoussan, Synapticon GmbH
# Copyright (c) 2017 Open Source Robotics Foundation, Inc.
#
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal  in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
#

from collections import defaultdict
import hashlib
import os.path
import re
from subprocess import DEVNULL, PIPE, Popen
import tarfile
from time import gmtime, strftime, strptime
from urllib.request import urlretrieve

from rosdistro import get_distribution_cache_string, get_index, get_index_url
from superflore.exceptions import NoPkgXml
from superflore.exceptions import UnresolvedDependency
from superflore.generators.bitbake.oe_query import OpenEmbeddedLayersDB
from superflore.PackageMetadata import PackageMetadata
from superflore.utils import err
from superflore.utils import get_distros
from superflore.utils import get_license
from superflore.utils import get_pkg_version
from superflore.utils import get_superflore_version
from superflore.utils import info
from superflore.utils import make_dir
from superflore.utils import ok
from superflore.utils import resolve_dep
from superflore.utils import warn
import yaml


class yoctoRecipe(object):
    rosdep_cache = defaultdict(set)
    generated_recipes = dict()
    generated_components = set()
    generated_native_recipes = set()
    generated_test_deps = set()
    generated_non_test_deps = set()
    not_generated_recipes = set()
    platform_deps = set()
    max_component_name = 0

    def __init__(
        self, component_name, num_pkgs, pkg_name, pkg_xml, distro, src_uri,
        tar_dir, md5_cache, sha256_cache, skip_keys
    ):
        self.component = component_name
        yoctoRecipe.max_component_name = max(
            yoctoRecipe.max_component_name, len(component_name))
        self.oe_component = yoctoRecipe.convert_to_oe_name(component_name)
        self.num_pkgs = num_pkgs
        self.name = pkg_name
        self.distro = distro.name
        self.version = get_pkg_version(distro, pkg_name, is_oe=True)
        self.src_uri = src_uri
        self.pkg_xml = pkg_xml
        self.author = None
        if self.pkg_xml:
            pkg_fields = PackageMetadata(pkg_xml)
            maintainer_name = pkg_fields.upstream_name
            maintainer_email = pkg_fields.upstream_email
            author_name = pkg_fields.author_name
            author_email = pkg_fields.author_email
            self.maintainer = maintainer_name + ' <' + maintainer_email + '>'
            if author_name or author_email:
                self.author = author_name + \
                    (' <' + author_email + '>' if author_email else '')
            self.license = pkg_fields.upstream_license
            self.description = pkg_fields.description
            self.homepage = pkg_fields.homepage
            self.build_type = pkg_fields.build_type
        else:
            self.description = ''
            self.license = None
            self.homepage = None
            self.build_type = 'catkin'
            self.maintainer = "OSRF"
        self.depends = set()
        self.depends_external = set()
        self.buildtool_depends = set()
        self.buildtool_depends_external = set()
        self.export_depends = set()
        self.export_depends_external = set()
        self.buildtool_export_depends = set()
        self.buildtool_export_depends_external = set()
        self.rdepends = set()
        self.rdepends_external = set()
        self.tdepends = set()
        self.tdepends_external = set()
        self.license_line = None
        self.archive_name = None
        self.license_md5 = None
        self.tar_dir = tar_dir
        if self.getArchiveName() not in md5_cache or \
           self.getArchiveName() not in sha256_cache:
            self.downloadArchive()
            md5_cache[self.getArchiveName()] = hashlib.md5(
                open(self.getArchiveName(), 'rb').read()).hexdigest()
            sha256_cache[self.getArchiveName()] = hashlib.sha256(
                open(self.getArchiveName(), 'rb').read()).hexdigest()
        self.src_sha256 = sha256_cache[self.getArchiveName()]
        self.src_md5 = md5_cache[self.getArchiveName()]
        self.skip_keys = skip_keys
        self.multi_hyphen_re = re.compile('-{2,}')

    def getArchiveName(self):
        if not self.archive_name:
            self.archive_name = self.tar_dir + "/" \
                + self.name.replace('-', '_') + '-' + str(self.version) \
                + '-' + self.distro + '.tar.gz'
        return self.archive_name

    def get_license_line(self):
        self.license_line = ''
        self.license_md5 = ''
        i = 0
        if not self.pkg_xml:
            raise NoPkgXml('No package xml file!')
        for line in str(self.pkg_xml, 'utf-8').split('\n'):
            i += 1
            if 'license' in line:
                self.license_line = str(i)
                md5 = hashlib.md5()
                md5.update((line + '\n').encode())
                self.license_md5 = md5.hexdigest()
                break

    def downloadArchive(self):
        if os.path.exists(self.getArchiveName()):
            info("using cached archive for package '%s'..." % self.name)
        else:
            info("downloading archive version for package '%s' from %s..." %
                 (self.name, self.src_uri))
            urlretrieve(self.src_uri, self.getArchiveName())

    def extractArchive(self):
        tar = tarfile.open(self.getArchiveName(), "r:gz")
        tar.extractall()
        tar.close()

    def add_build_depend(self, bdepend, internal=True):
        if bdepend not in self.skip_keys:
            if internal:
                if bdepend not in self.depends_external:
                    self.depends.add(bdepend)
            else:
                if bdepend not in self.depends:
                    self.depends_external.add(bdepend)

    def add_buildtool_depend(self, btdepend, internal=True):
        if btdepend not in self.skip_keys:
            if internal:
                if btdepend not in self.buildtool_depends_external:
                    self.buildtool_depends.add(btdepend)
            else:
                if btdepend not in self.buildtool_depends:
                    self.buildtool_depends_external.add(btdepend)

    def add_export_depend(self, edepend, internal=True):
        if edepend not in self.skip_keys:
            if internal:
                if edepend not in self.export_depends_external:
                    self.export_depends.add(edepend)
            else:
                if edepend not in self.export_depends:
                    self.export_depends_external.add(edepend)

    def add_buildtool_export_depend(self, btedepend, internal=True):
        if btedepend not in self.skip_keys:
            if internal:
                if btedepend not in self.buildtool_export_depends_external:
                    self.buildtool_export_depends.add(btedepend)
            else:
                if btedepend not in self.buildtool_export_depends:
                    self.buildtool_export_depends_external.add(btedepend)

    def add_run_depend(self, rdepend, internal=True):
        if rdepend not in self.skip_keys:
            if internal:
                if rdepend not in self.rdepends_external:
                    self.rdepends.add(rdepend)
            else:
                if rdepend not in self.rdepends:
                    self.rdepends_external.add(rdepend)

    def add_test_depend(self, tdepend, internal=True):
        if tdepend not in self.skip_keys:
            if internal:
                if tdepend not in self.tdepends_external:
                    self.tdepends.add(tdepend)
            else:
                if tdepend not in self.tdepends:
                    self.tdepends_external.add(tdepend)

    def get_src_location(self):
        """
        Parse out the folder name.
        TODO(allenh1): add a case for non-GitHub packages,
        after they are supported.
        """
        github_start = 'https://github.com/'
        structure = self.src_uri.replace(github_start, '')
        dirs = structure.split('/')
        return '{0}-{1}-{2}-{3}-{4}'.format(dirs[1], dirs[3],
                                            dirs[4], dirs[5],
                                            dirs[6]).replace('.tar.gz', '')

    def get_top_inherit_line(self):
        ret = 'inherit ros_distro_${ROS_DISTRO}\n'
        ret += 'inherit ros_superflore_generated\n\n'
        return ret

    def get_bottom_inherit_line(self):
        ret = 'inherit ${ROS_COMPONENT_TYPE}_component\n'
        ret += 'inherit ros_${ROS_BUILD_TYPE}\n'
        return ret

    def trim_hyphens(self, s):
        return self.multi_hyphen_re.sub('-', s)

    def translate_license(self, l):
        conversion_table = {ord(' '): '-', ord('/'): '-', ord(':'): '-',
                            ord('+'): '-', ord('('): '-', ord(')'): '-'}
        return self.trim_hyphens(l.translate(conversion_table))

    @staticmethod
    def get_native_suffix(is_native=False):
        return '-native' if is_native else ''

    @staticmethod
    def get_spacing_prefix():
        return '\n' + ' ' * 4

    @staticmethod
    def convert_dep_except_oe_vars(dep):
        """
        Convert dependency name to lowercase and replace '_' by '-'
        except in ${OE} variables.
        """
        BEGIN_PATTERN = '${'
        END_PATTERN = '}'
        result = ''
        begin = dep.find(BEGIN_PATTERN)
        while begin != -1:
            result += dep[:begin].lower().replace('_', '-')
            remaining = dep[begin + len(BEGIN_PATTERN):]
            end = remaining.find(END_PATTERN)
            if end == -1:
                dep = dep[begin:]
                break
            oe_var = remaining[:end]
            result += BEGIN_PATTERN + oe_var + END_PATTERN
            dep = remaining[end + len(END_PATTERN):]
            begin = dep.find(BEGIN_PATTERN)
        result += dep.lower().replace('_', '-')
        return result

    @classmethod
    def convert_to_oe_name(cls, dep, is_native=False):
        # Discard meta-layer information past '@'
        dep = dep.split('@')[0]
        if dep.endswith('_native'):
            dep = dep[:-len('_native')] + '-rosnative'
        elif dep.endswith('_dev'):
            dep = dep[:-len('_dev')] + '-rosdev'
        elif dep in ('ros1', 'ros2'):
            dep += '--distro-renamed'
        return cls.convert_dep_except_oe_vars(dep) \
            + cls.get_native_suffix(is_native)

    @classmethod
    def generate_multiline_variable(cls, var, container, sort=True, key=None):
        if sort:
            container = sorted(container, key=key)
        assignment = '{0} = "'.format(var)
        expression = '"\n'
        if container:
            expression = ' \\' + cls.get_spacing_prefix()
            expression += cls.get_spacing_prefix().join(
                [item + ' \\' for item in container]) + '\n"\n'
        return assignment + expression

    def get_dependencies(
            self, internal_depends, external_depends, is_native=False):
        dependencies = set()
        system_dependencies = set()
        union_deps = internal_depends | external_depends
        if len(union_deps) <= 0:
            return dependencies, system_dependencies
        for dep in union_deps:
            if dep in internal_depends:
                recipe = self.convert_to_oe_name(dep, is_native)
                dependencies.add(recipe)
                info('Internal dependency add: ' + recipe)
                continue
            try:
                results = resolve_dep(dep, 'openembedded', self.distro)[0]
                if not results:
                    yoctoRecipe.rosdep_cache[dep] = []
                    continue
                for res in results:
                    recipe = self.convert_to_oe_name(res, is_native)
                    dependencies.add(recipe)
                    system_dependencies.add(self.convert_to_oe_name(res))
                    yoctoRecipe.rosdep_cache[dep].add(res)
                    info('External dependency add: ' + recipe)
            except UnresolvedDependency:
                info('Unresolved dependency: ' + dep)
                if dep in yoctoRecipe.rosdep_cache:
                    cached_deps = yoctoRecipe.rosdep_cache[dep]
                    if cached_deps == set(['null']):
                        system_dependencies.add(dep)
                        recipe = dep + self.get_native_suffix(is_native)
                        dependencies.add(recipe)
                        msg = 'Failed to resolve (cached):'
                        warn('{0} {1}: {2}'.format(msg, dep, recipe))
                    elif cached_deps:
                        system_dependencies |= cached_deps
                        for d in cached_deps:
                            recipe = self.convert_to_oe_name(d, is_native)
                            dependencies.add(recipe)
                            msg = 'Resolved in OpenEmbedded (cached):'
                            info('{0} {1}: {2}'.format(msg, dep, recipe))
                    continue
                oe_query = OpenEmbeddedLayersDB()
                oe_query.query_recipe(self.convert_to_oe_name(dep))
                if oe_query.exists():
                    recipe = self.convert_to_oe_name(oe_query.name, is_native)
                    dependencies.add(recipe)
                    oe_name = self.convert_to_oe_name(oe_query.name)
                    system_dependencies.add(oe_name)
                    yoctoRecipe.rosdep_cache[dep].add(oe_name)
                    info('Resolved in OpenEmbedded: ' + dep + ' as ' +
                         oe_query.name + ' in ' + oe_query.layer +
                         ' as recipe ' + recipe)
                else:
                    recipe = dep + self.get_native_suffix(is_native)
                    dependencies.add(recipe)
                    system_dependencies.add(dep)
                    yoctoRecipe.rosdep_cache[dep].add('null')
                    warn('Failed to resolve fully: ' + dep)
        return dependencies, system_dependencies

    def get_recipe_text(self, distributor):
        """
        Generate the Yocto Recipe, given the distributor line
        and the license text.
        """
        ret = "# Generated by superflore -- DO NOT EDIT\n#\n"
        ret += "# Copyright " + strftime("%Y", gmtime()) + " "
        ret += distributor + "\n\n"
        ret += self.get_top_inherit_line()
        # description
        if self.description:
            self.description = self.description.replace('\n', ' ')
            ret += 'DESCRIPTION = "' + self.description + '"\n'
        else:
            ret += 'DESCRIPTION = "None"\n'
        # author
        ret += 'AUTHOR = "' + self.maintainer + '"\n'
        if self.author:
            ret += 'ROS_AUTHOR = "' + self.author + '"\n'
        if self.homepage:
            ret += 'HOMEPAGE = "' + self.homepage + '"\n'
        # section
        ret += 'SECTION = "devel"\n'
        # license
        self.get_license_line()
        if isinstance(self.license, str):
            ret += 'LICENSE = "%s"\n' % self.translate_license(
                get_license(self.license))
        elif isinstance(self.license, list):
            ret += 'LICENSE = "'
            ret += ' & '.join([self.translate_license(
                get_license(l)) for l in self.license]) + '"\n'
        ret += 'LIC_FILES_CHKSUM = "file://package.xml;beginline='
        ret += str(self.license_line)
        ret += ';endline='
        ret += str(self.license_line)
        ret += ';md5='
        ret += str(self.license_md5)
        ret += '"\n\n'
        ret += 'ROS_CN = "' + self.component + '"\n'
        ret += 'ROS_BPN = "' + self.name + '"\n\n'
        # depends
        deps, sys_deps = self.get_dependencies(
            self.depends, self.depends_external)
        yoctoRecipe.platform_deps |= sys_deps
        buildtool_native_deps, sys_deps = self.get_dependencies(
            self.buildtool_depends,
            self.buildtool_depends_external,
            is_native=True
        )
        native_deps = set(buildtool_native_deps)
        yoctoRecipe.platform_deps |= sys_deps
        export_deps, sys_deps = self.get_dependencies(
            self.export_depends, self.export_depends_external)
        yoctoRecipe.platform_deps |= sys_deps
        buildtool_export_native_deps, sys_deps = self.get_dependencies(
            self.buildtool_export_depends,
            self.buildtool_export_depends_external,
            is_native=True
        )
        native_deps |= buildtool_export_native_deps
        yoctoRecipe.platform_deps |= sys_deps
        yoctoRecipe.generated_native_recipes |= native_deps
        exec_deps, sys_deps = self.get_dependencies(
            self.rdepends, self.rdepends_external)
        yoctoRecipe.platform_deps |= sys_deps
        test_deps, sys_deps = self.get_dependencies(self.tdepends,
                                                    self.tdepends_external)
        yoctoRecipe.platform_deps |= sys_deps
        yoctoRecipe.generated_non_test_deps |= deps | export_deps | \
            native_deps | exec_deps
        yoctoRecipe.generated_test_deps |= test_deps
        ret += yoctoRecipe.generate_multiline_variable(
            'ROS_BUILD_DEPENDS', deps) + '\n'
        ret += yoctoRecipe.generate_multiline_variable(
            'ROS_BUILDTOOL_DEPENDS', buildtool_native_deps) + '\n'
        if self.name == 'ament_cmake':
            ret += yoctoRecipe.generate_multiline_variable(
                'ROS_EXPORT_DEPENDS', '') + '\n'
            ament_cmake_native_deps, sys_deps = self.get_dependencies(
                self.export_depends,
                self.export_depends_external,
                is_native=True
            )
            buildtool_export_native_deps |= ament_cmake_native_deps
            yoctoRecipe.generated_non_test_deps |= ament_cmake_native_deps
            yoctoRecipe.generated_native_recipes |= ament_cmake_native_deps
            yoctoRecipe.platform_deps |= sys_deps
        else:
            ret += yoctoRecipe.generate_multiline_variable(
                'ROS_EXPORT_DEPENDS', export_deps) + '\n'
        ret += yoctoRecipe.generate_multiline_variable(
            'ROS_BUILDTOOL_EXPORT_DEPENDS',
            buildtool_export_native_deps) + '\n'
        ret += yoctoRecipe.generate_multiline_variable(
            'ROS_EXEC_DEPENDS', exec_deps) + '\n'
        ret += '# Currently informational only -- see '
        ret += 'http://www.ros.org/reps/rep-0149.html#dependency-tags.\n'
        ret += yoctoRecipe.generate_multiline_variable(
            'ROS_TEST_DEPENDS', test_deps) + '\n'
        ret += 'DEPENDS = "${ROS_BUILD_DEPENDS} ${ROS_BUILDTOOL_DEPENDS}"\n'
        ret += '# Bitbake doesn\'t support the "export" concept, so build them'
        ret += ' as if we needed them to build this package (even though we'
        ret += ' actually\n# don\'t) so that they\'re guaranteed to have been'
        ret += ' staged should this package appear in another\'s DEPENDS.\n'
        ret += 'DEPENDS += "${ROS_EXPORT_DEPENDS} '
        ret += '${ROS_BUILDTOOL_EXPORT_DEPENDS}"\n\n'
        ret += 'RDEPENDS_${PN} += "${ROS_EXEC_DEPENDS}"' + '\n\n'
        # SRC_URI
        ret += 'SRC_URI = "' + self.src_uri + ';'
        ret += 'downloadfilename=${ROS_SP}.tar.gz"\n'
        ret += 'SRC_URI[md5sum] = "' + self.src_md5 + '"\n'
        ret += 'SRC_URI[sha256sum] = "' + self.src_sha256 + '"\n'
        ret += 'S = "${WORKDIR}/'
        ret += self.get_src_location() + '"\n\n'
        ret += 'ROS_COMPONENT_TYPE = "${@ros_distro__get_component_type(\''
        ret += self.oe_component + '\', d)}"\n'
        ret += 'ROS_BUILD_TYPE = "' + self.build_type + '"\n'
        # include
        ret += '\n# Allow the above settings to be overridden.\n'
        ret += 'ROS_INCLUDES_TREE := '
        ret += '"${@ros_superflore_generated__get_includes_tree(\''
        ret += self.oe_component + '\', d)}"\n'
        inc_prefix = 'include ${ROS_LAYERDIR}/'
        component_path = '/' + self.oe_component + '/' + self.oe_component
        inc_suffix = '_common.inc\n'
        ret += inc_prefix + '${ROS_INCLUDES_TREE}' + component_path + \
            inc_suffix
        ret += inc_prefix + '${ROS_INCLUDES_TREE}' + \
            component_path + '-${PV}' + inc_suffix
        path_prefix = inc_prefix + '${ROS_INCLUDES_TREE}/' + self.oe_component
        ret += path_prefix + '/${BPN}.inc\n'
        ret += path_prefix + '/${BPN}-${PV}.inc\n'
        # Inherits
        ret += '\n' + self.get_bottom_inherit_line()
        return ret

    @staticmethod
    def _get_cache_last_modified_time(distro):
        try:
            from urllib.request import urlopen
        except ImportError:
            from urllib2 import urlopen
        dist = get_index(get_index_url()).distributions[distro]
        conn = urlopen(dist['distribution_cache'])
        last_modified = conn.headers['last-modified']
        ts = strptime(last_modified, '%a, %d %b %Y %H:%M:%S %Z')
        return strftime('%Y%m%d%H%M%S', ts)

    @staticmethod
    def _get_ros_version(distro):
        distros = get_distros()
        return 2 if distro not in distros \
            else int(distros[distro]['distribution_type'][len('ros'):])

    @staticmethod
    def generate_rosdistro_conf(
            basepath, distro, version, platforms, skip_keys=[]):
        conf_dir = '{}/conf/ros-distro/include/{}/'.format(basepath, distro)
        conf_file_name = 'generated-ros-distro.inc'
        conf_path = '{}{}'.format(conf_dir, conf_file_name)
        try:
            make_dir(conf_dir)
            with open(conf_path, 'w') as conf_file:
                conf_file.write('# {}/{}\n'.format(distro, conf_file_name))
                conf_file.write('# Generated by superflore -- DO NOT EDIT')
                conf_file.write(
                    ' (except ROS_DISTRO_METADATA_VERSION_REVISION)\n#\n')
                conf_file.write(
                    '# Copyright 2019 Open Source Robotics Foundation\n\n')
                conf_file.write(
                    '# Increment every time meta-ros is released because of '
                    + 'a manually created change, ie, NOT as a result of a '
                    + 'superflore run (which\n# resets it to "0").')
                conf_file.write(
                    '\nROS_DISTRO_METADATA_VERSION_REVISION = "0"\n')
                conf_file.write(
                    '\nROS_SUPERFLORE_PROGRAM_VERSION = "{}"\n'
                    .format(get_superflore_version()))
                conf_file.write('ROS_SUPERFLORE_GENERATION_SCHEME = "1"\n')
                ros_version = yoctoRecipe._get_ros_version(distro)
                conf_file.write(
                    '\nROS_DISTRO_TYPE = "ros{}"\n'.format(ros_version))
                conf_file.write('ROS_VERSION = "{}"\n'.format(ros_version))
                conf_file.write('# DO NOT OVERRIDE ROS_PYTHON_VERSION\n')
                ros_python_version = 3
                if ros_version == 1:
                    ros_python_version = 2
                conf_file.write(
                    'ROS_PYTHON_VERSION = "{}"\n'.format(ros_python_version))
                conf_file.write(
                    '\n# The last-modified timestamp in UTC of the upstream '
                    + 'ROS_DISTRO-cache.yaml from which superflore generated '
                    + 'the recipes. The date\n# portion is used as the second'
                    + ' version field of DISTRO_VERSION prior to the first '
                    + 'release of a ROS_DISTRO.')
                conf_file.write(
                    '\nROS_SUPERFLORE_GENERATION_DATETIME = "{0}"\n\n'.format(
                        yoctoRecipe._get_cache_last_modified_time(distro)))
                oe_skip_keys = map(
                    lambda skip_key: yoctoRecipe.convert_to_oe_name(skip_key),
                    skip_keys
                )
                conf_file.write(yoctoRecipe.generate_multiline_variable(
                    'ROS_SUPERFLORE_GENERATION_SKIP_LIST', oe_skip_keys)
                    + '\n')
                conf_file.write(
                    '# Superflore was unable to generate recipes for these '
                    + 'packages, eg, because their repositories are not on '
                    + 'GitHub.\n')
                conf_file.write(yoctoRecipe.generate_multiline_variable(
                    'ROS_SUPERFLORE_GENERATION_NOT_POSSIBLE',
                    yoctoRecipe.not_generated_recipes) + '\n')
                conf_file.write(
                    '# Number of commits that will be returned by'
                    + ' "git log files/ROS_DISTRO-cache.yaml" when the '
                    + 'generated files are committed. This is\n# used for the'
                    + ' third version field of DISTRO_VERSION.\n')
                version = 1 if not version else len(version.splitlines()) + 1
                conf_file.write(
                    'ROS_NUM_CACHE_YAML_COMMITS = "{}"'.format(version)
                    + '\n\n')
                conf_file.write(
                    '# Iterated values of '
                    + 'ROS_DISTRO-cache.distribution_file.release_platforms.'
                    + '<LINUX-DISTRO>.[ <NAME> ... ] .\n')
                release_platforms = []
                for p in sorted(platforms.items()):
                    for release in p[1]:
                        release_platforms.append(p[0] + '-' + release)
                conf_file.write(yoctoRecipe.generate_multiline_variable(
                    'ROS_DISTRO_RELEASE_PLATFORMS', release_platforms) + '\n')
                conf_file.write(yoctoRecipe.generate_multiline_variable(
                    'ROS_SUPERFLORE_GENERATED_RECIPES',
                    yoctoRecipe.generated_recipes.keys()) + '\n')
                conf_file.write(yoctoRecipe.generate_multiline_variable(
                    'ROS_SUPERFLORE_GENERATED_RECIPE_BASENAMES_WITH_COMPONENT',
                    [(yoctoRecipe.max_component_name - len(component)) * ' '
                     + component + '/' + recipe + '_' + version
                     for recipe, (version, component)
                     in yoctoRecipe.generated_recipes.items()],
                    key=lambda recipe: recipe.split('/')[1].split('_')[0]))
                conf_file.write(
                    '\n# What\'s built by packagegroup-ros-world. Does not '
                    + 'include packages that appear solely in '
                    + 'ROS_SUPERFLORE_GENERATED_BUILDTOOLS\n# (with a -native'
                    + ' suffix) or ROS_SUPERFLORE_GENERATED_TESTS.\n')
                recipes_set = set(yoctoRecipe.generated_recipes.keys())
                test_deps = set(map(
                    lambda test_dep: yoctoRecipe.convert_to_oe_name(test_dep),
                    yoctoRecipe.generated_test_deps
                    - yoctoRecipe.generated_non_test_deps
                ))
                conf_file.write(yoctoRecipe.generate_multiline_variable(
                    'ROS_SUPERFLORE_GENERATED_WORLD_PACKAGES', recipes_set
                    - yoctoRecipe.generated_native_recipes - test_deps))
                conf_file.write(
                    '\n# Packages found in the <buildtool_depend> and '
                    + '<buildtool_export_depend> items, ie, ones for which a '
                    + '-native is built. Does not\n# include those found in '
                    + 'the ROS_EXEC_DEPENDS values in the recipes of build '
                    + 'tools.\n')
                conf_file.write(
                    yoctoRecipe.generate_multiline_variable(
                        'ROS_SUPERFLORE_GENERATED_BUILDTOOLS',
                        yoctoRecipe.generated_native_recipes) + '\n')
                conf_file.write(yoctoRecipe.generate_multiline_variable(
                    'ROS_SUPERFLORE_GENERATED_PLATFORM_PACKAGE_DEPENDENCIES',
                    yoctoRecipe.platform_deps))
                conf_file.write(
                    '\n# Packages found only in <test_depend> items. Does not'
                    + ' include those found only in the ROS_*_DEPENDS of '
                    + 'recipes of tests.\n')
                conf_file.write(
                    yoctoRecipe.generate_multiline_variable(
                        'ROS_SUPERFLORE_GENERATED_TESTS',
                        test_deps) + '\n')
                conf_file.write(
                    yoctoRecipe.generate_multiline_variable(
                        'ROS_SUPERFLORE_GENERATED_RECIPES_FOR_COMPONENTS',
                        yoctoRecipe.generated_components))
                ok('Wrote {0}'.format(conf_path))
        except OSError as e:
            err('Failed to write conf {} to disk! {}'.format(conf_path, e))
            raise e

    @staticmethod
    def generate_distro_cache(basepath, distro, skip_keys=[]):
        distro_cache_dir = '{0}/files/{1}/'.format(basepath, distro)
        distro_cache_path = '{0}cache.yaml'.format(distro_cache_dir)
        try:
            index = get_index(get_index_url())
            yaml_str = get_distribution_cache_string(index, distro)
            make_dir(distro_cache_dir)
            with open(distro_cache_path, 'w') as distro_cache_file:
                distro_cache_file.write('# {}/cache.yaml\n'.format(distro))
                distro_cache_file.write(yaml_str)
                ok('Wrote {0}'.format(distro_cache_path))
        except OSError as e:
            err('Failed to write distro cache {} to disk! {}'.format(
                distro_cache_path, e))
            raise e
        # Generate a diff'able cache file
        distro_cache_diff_path = '{}cache.diffme'.format(distro_cache_dir)
        try:
            def replace_all_patterns(d, text):
                for k, v in d.items():
                    text = re.sub(k, v, text, flags=re.M)
                return text
            replacement_table = {
                r"{([^ }][^ }]*)}": r'[[\1]]',
                r"{": r"{\n",
                r"}": r"\n}",
                r"\[\[": r"{",
                r"\]\]": r"}",
                r", ": r",\n",
                r"^    ": r"-----\n",
                r"<version>[^<]*</version>": r"",
                r"><": r">\n<",
                r"^  ": r"-----\n",
                r"^(source_repo_package_xmls:)": r"-----\n\1",
            }
            with open(distro_cache_diff_path, 'w') as distro_cache_diff_file:
                distro_cache_diff_file.write(
                    '# {}/cache.diffme\n'.format(distro))
                yaml_str = replace_all_patterns(replacement_table, yaml_str)
                distro_cache_diff_file.write(yaml_str)
                ok('Wrote {0}'.format(distro_cache_diff_path))
        except OSError as e:
            err('Failed to write diffme distro cache {} to disk! {}'.format(
                distro_cache_diff_path, e))
            raise e

    @staticmethod
    def generate_rosdep_resolve(basepath, distro):
        rosdep_resolve_dir = '{0}/files/{1}/'.format(basepath, distro)
        rosdep_resolve_path = '{0}rosdep-resolve.yaml'.format(
            rosdep_resolve_dir)
        try:
            make_dir(rosdep_resolve_dir)
            with open(rosdep_resolve_path, 'w') as rosdep_resolve_file:
                rosdep_resolve_file.write(
                    '# {}/rosdep-resolve.yaml\n'.format(distro))
                cache_as_dict_of_list = {
                    k: list(v) for k, v in yoctoRecipe.rosdep_cache.items()}
                rosdep_resolve_file.write(yaml.dump(
                    cache_as_dict_of_list, default_flow_style=False))
                ok('Wrote {0}'.format(rosdep_resolve_path))
        except OSError as e:
            err('Failed to write rosdep resolve cache {} to disk! {}'.format(
                rosdep_resolve_path, e))
            raise e

    @staticmethod
    def generate_superflore_change_summary(basepath, distro, change_summary):
        change_summary_dir = '{0}/files/{1}/'.format(basepath, distro)
        change_summary_path = '{0}superflore-change-summary.txt'.format(
            change_summary_dir)
        try:
            make_dir(change_summary_dir)
            with open(change_summary_path, 'w') as change_summary_file:
                change_summary_file.write(
                    '{}/superflore-change-summary.txt\n'.format(distro))
                change_summary_file.write(change_summary)
                ok('Wrote {0}'.format(change_summary_path))
        except OSError as e:
            err('Failed to write change summary {} to disk! {}'.format(
                change_summary_path, e))
            raise e

    @staticmethod
    def generate_newer_platform_components(basepath, distro):
        newer_sys_comps_dir = '{0}/files/{1}/'.format(basepath, distro)
        newer_sys_comps_path = '{0}newer-platform-components.list'.format(
            newer_sys_comps_dir)
        ros_version = yoctoRecipe._get_ros_version(distro)
        str_distro = 'ros' if ros_version == 1 else 'ros{}'.format(ros_version)
        args1_wget = ['wget', '-O', '-', 'http://packages.ros.org/'
                      + str_distro
                      + '/ubuntu/dists/bionic/main/source/Sources.gz']
        args2_gunzip = ['gunzip', '-']
        args3_grep = ['grep', '-E', '^(Package|Version|Build-Depends)']
        args4_awk = ['awk', '$1 ~ /^Package:/ && $2 !~ /^ros-/ '
                     + '{ printf "%s;", $2; getline; '
                     + 'printf "%s;", $2; getline; '
                     + 'gsub(/Build-Depends: /, ""); gsub(/, /, ","); print}']
        args5_sort = ['sort', '-t', ';', '-k', '1,1']
        try:
            make_dir(newer_sys_comps_dir)
            wget = Popen(args1_wget, stdout=PIPE, stderr=DEVNULL)
            gunzip = Popen(args2_gunzip, stdin=wget.stdout,
                           stdout=PIPE, stderr=DEVNULL)
            grep = Popen(args3_grep, stdin=gunzip.stdout,
                         stdout=PIPE, stderr=DEVNULL)
            awk = Popen(args4_awk, stdin=grep.stdout,
                        stdout=PIPE, stderr=DEVNULL)
            sort = Popen(args5_sort, env={'LC_ALL': 'C'},
                         stdin=awk.stdout, stdout=PIPE, stderr=DEVNULL)
            cmds = [wget, gunzip, grep, awk]
            # Allow previous process to receive a SIGPIPE
            # if the next one in the pipeline exits.
            for cmd in cmds:
                cmd.stdout.close()
            # Run the pipeline and collect the output
            txt_output = sort.communicate()[0].decode()
            # Consume the return value of the other processes
            for cmd in cmds:
                cmd.wait()
            cmds.append(sort)
            if any([cmd.returncode for cmd in cmds]):
                errors = ['{}[{}]'.format(cmd.args[0], cmd.returncode)
                          for cmd in cmds]
                raise RuntimeError('Error codes ' + ' '.join(errors))
            with open(newer_sys_comps_path, 'w') as newer_sys_comps_file:
                newer_sys_comps_file.write(
                    '# {}/newer-platform-components.list\n'.format(distro))
                newer_sys_comps_file.write(txt_output)
                ok('Wrote {0}'.format(newer_sys_comps_path))
        except (OSError, RuntimeError) as e:
            err('Failed to write change summary {} to disk! {}'.format(
                newer_sys_comps_path, e))
            raise e

    @staticmethod
    def reset():
        yoctoRecipe.rosdep_cache = defaultdict(set)
        yoctoRecipe.generated_recipes = dict()
        yoctoRecipe.generated_components = set()
        yoctoRecipe.generated_native_recipes = set()
        yoctoRecipe.generated_test_deps = set()
        yoctoRecipe.generated_non_test_deps = set()
        yoctoRecipe.not_generated_recipes = set()
        yoctoRecipe.platform_deps = set()
        yoctoRecipe.max_component_name = 0
