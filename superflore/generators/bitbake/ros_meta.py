# Copyright 2017 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re
import time

from superflore.repo_instance import RepoInstance
from superflore.utils import info


class RosMeta(object):
    def __init__(
        self, dir, do_clone, branch, org='ros', repo='meta-ros', from_branch=''
    ):
        self.repo = RepoInstance(
            org, repo, dir, do_clone, from_branch=from_branch)
        self.branch_name = branch
        info('Creating new branch {0}...'.format(self.branch_name))
        self.repo.create_branch(self.branch_name)

    def clean_ros_recipe_dirs(self, distro=None):
        if distro:
            info(
                'Cleaning up generated-recipes-{} directory...'.format(distro))
            self.repo.git.rm('-rf', 'generated-recipes-{}'.format(distro))
        else:
            info('Cleaning up generated-recipes-* directories...')
            self.repo.git.rm('-rf', 'generated-recipes-*')

    def commit_changes(self, distro):
        info('Adding changes...')
        if distro == 'all':
            commit_msg = 'regenerate all distros, {0}'
            self.repo.git.add('generated-recipes-*')
            self.repo.git.add(
                'conf/ros-distro/include/*/generated-ros-distro.inc')
            self.repo.git.add('files/*/cache.*')
            self.repo.git.add('files/*/rosdep-resolve.yaml')
            self.repo.git.add('files/*/newer-platform-components.list')
            self.repo.git.add('files/*/superflore-change-summary.txt')
        else:
            commit_msg = 'regenerate ros-{1}, {0}'
            self.repo.git.add('generated-recipes-{0}'.format(distro))
            self.repo.git.add(
                'conf/ros-distro/include/{0}/generated-ros-distro.inc'
                .format(distro))
            self.repo.git.add('files/{0}/cache.*'.format(distro))
            self.repo.git.add('files/{0}/rosdep-resolve.yaml'.format(distro))
            self.repo.git.add(
                'files/{0}/newer-platform-components.list'.format(distro))
            self.repo.git.add(
                'files/{0}/superflore-change-summary.txt'.format(distro))
        commit_msg = commit_msg.format(time.ctime(), distro)
        info('Committing to branch {0}...'.format(self.branch_name))
        self.repo.git.commit(m='{0}'.format(commit_msg))

    def pull_request(self, message, distro=None, title=''):
        if not title:
            title = 'rosdistro sync, {0}'.format(time.ctime())
        self.repo.pull_request(message, title, branch=distro)

    def get_file_revision_logs(self, *file_path):
        return self.repo.git.log('--oneline', '--', *file_path)

    def get_change_summary(self):
        self.repo.git.add('-N', 'generated-recipes-*')
        sep = '-' * 5
        return '\n'.join([
            sep,
            re.sub('^On branch.*\n', '', self.repo.git.status(), re.MULTILINE),
            sep, self.repo.git.diff('conf'), sep, self.repo.git.diff('files'),
        ])
