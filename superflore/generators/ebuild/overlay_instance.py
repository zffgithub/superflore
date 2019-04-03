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

import os
import time

import docker
from superflore.docker import Docker
from superflore.repo_instance import RepoInstance
from superflore.utils import info
from superflore.utils import rand_ascii_str


class RosOverlay(object):
    def __init__(self, repo_dir, do_clone, org='ros', repo='ros-overlay'):
        self.repo = RepoInstance(
            org, repo, repo_dir=repo_dir, do_clone=do_clone
        )
        self.branch_name = 'gentoo-bot-%s' % rand_ascii_str()
        info('Creating new branch {0}...'.format(self.branch_name))
        self.repo.create_branch(self.branch_name)

    def commit_changes(self, distro):
        info('Adding changes...')
        self.repo.git.add(self.repo.repo_dir)
        info('Committing to branch {0}...'.format(self.branch_name))
        commit_msg = {
            'update': 'rosdistro sync, ',
            'all': 'regenerate all distros, ',
            'lunar': 'regenerate ros-lunar, ',
            'indigo': 'regenerate ros-indigo, ',
            'kinetic': 'regenerate ros-kinetic, ',
            'melodic': 'regenerate ros-melodic, ',
            'ardent': 'regenerate ros2-ardent, ',
            'bouncy': 'regenerate ros2-bouncy, ',
            'crystal': 'regenerate ros2-crystal, ',
        }[distro or 'update'] + time.ctime()
        self.repo.git.commit(m='{0}'.format(commit_msg))

    def regenerate_manifests(
        self, regen_dict, image_owner='allenh1', image_name='ros_gentoo_base'
    ):
        info(
            "Pulling docker image '%s/%s:latest'..." % (
                image_owner, image_name
            )
        )
        dock = Docker()
        dock.pull(image_owner, image_name)
        info('Running docker image...')
        info('Generating manifests...')
        dock.map_directory(
            '/home/%s/.gnupg' % os.getenv('USER'),
            '/root/.gnupg'
        )
        dock.map_directory(self.repo.repo_dir, '/tmp/ros-overlay')
        for key in regen_dict.keys():
            for pkg in regen_dict[key]:
                pkg_dir = '/tmp/ros-overlay/ros-{0}/{1}'.format(key, pkg)
                dock.add_bash_command('cd {0}'.format(pkg_dir))
                dock.add_bash_command('repoman manifest')
        try:
            dock.run(show_cmd=True)
        except docker.errors.ContainerError:
            print(dock.log)
            raise

    def pull_request(self, message, overlay=None):
        pr_title = 'rosdistro sync, {0}'.format(time.ctime())
        self.repo.pull_request(message, pr_title)
