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

import shutil

from git import Repo
from git.exc import GitCommandError as GitGotGot
from superflore.utils import err
from superflore.utils import info
from superflore.utils import ok


class RepoInstance(object):
    def __init__(self, repo_owner, repo_name, repo_dir=None, do_clone=True):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        repo_url = 'https://github.com/{0}/{1}'
        self.repo_url = repo_url.format(self.repo_owner, self.repo_name)
        self.repo_dir = repo_dir or self.repo_name
        if do_clone:
            self.repo = Repo.clone_from(self.repo_url, self.repo_dir)
        else:
            self.repo = Repo(repo_dir)
        self.git = self.repo.git

    def clone(self, branch=None):
        shutil.rmtree(self.repo_dir)
        msg = 'Cloning repo {0}/{1}'.format(self.repo_owner, self.repo_name)
        if self.repo_dir != self.repo_name:
            msg += (' into directory {0}'.format(self.repo_dir))
        msg += '...'
        info(msg)
        self.repo = Repo.clone_from(self.repo_url, self.repo_dir)
        if branch:
            self.git.checkout(branch)

    def remove_file(self, filename, ignore_fail=False):
        try:
            self.git.rm('-f', filename)
        except GitGotGot as g:
            if ignore_fail:
                return
            fail_msg = 'Failed to remove file {0}'.format(filename)
            fail_msg += 'from source control.'
            err(fail_msg)
            err(' Exception: {0}'.format(g))

    def create_branch(self, branch_name):
        """
        @todo: error checking
        """
        info(self.git.checkout('HEAD', b=branch_name))

    def remove_branch(self, branch_name):
        """
        @todo: error checking
        """
        self.git.branch('-D', branch_name)

    def change_branch(self, branch_name):
        """
        @todo: error checking
        """
        self.git.checkout(branch_name)

    def rebase(self, target):
        """
        @todo: error checking
        """
        self.git.rebase(i=target)

    def pull_request(self, message, title, branch='master', remote='origin'):
        info('Filing pull-request...')
        self.git.pull_request(
            m='{0}'.format(message),
            title='{0}'.format(title),
            target_branch='{0}'.format(branch),
            target_remote='{0}'.format(remote),
        )
        ok('Successfully filed a pull request.')
