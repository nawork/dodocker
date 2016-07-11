"""
======================================================================
dodocker. A build tool for independent docker images and registries.
Copyright (C) 2014-2016  n@work Internet Informationssysteme GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
======================================================================
"""

from __future__ import print_function

DEFAULT_DODOCKER_CONFIG = {'registry_path' : 'localhost:5000',
                           'insecure'      : True}

DOIT_CONFIG = {'default_tasks': ['build']}

dodocker_config_path = '.dodocker.cfg'

import os, yaml, json, sys, re, time, hashlib, argparse
from doit.tools import result_dep, run_once
import docker
import subprocess
import git

doc = docker.Client(base_url='unix://var/run/docker.sock',
                    version='1.17',
                    timeout=10)
dodocker_config = {}

def image_id(image):
    def image_id_callable():
        try:
            data = doc.inspect_image(image)
        except docker.errors.APIError as e:
            if e.response.status_code != 404:
                raise
            return False
        return data['Id']
    return image_id_callable

def check_available(image):
    def check_available_callable():
        try:
            data = doc.inspect_image(image)
        except docker.errors.APIError as e:
            if e.response.status_code != 404:
                raise
            return False
        return True
    return check_available_callable

def docker_build(path,tag,dockerfile,pull=False,rm=True):
    def docker_build_callable():
        error = False
        print(path,tag)
        for line in doc.build(path,tag=tag,stream=True,pull=pull,dockerfile=dockerfile,
                              rm=rm,nocache=dodocker_config.get('no_cache',False)):
            line_parsed = json.loads(line)
            if 'stream' in line_parsed:
                sys.stdout.write(line_parsed['stream'].encode('utf8'))
            if line_parsed.get('errorDetail'):
                sys.stdout.write(line_parsed['errorDetail']['message']+'\n')
                error = True
        return not error
    return docker_build_callable

def shell_build(shell_cmd,image,path='.',force=False):
    def docker_build_callable():
        print(shell_cmd,image)
        if check_available(image)() and not force:
            return True
        p = subprocess.Popen([shell_cmd],cwd=path,shell=True,
                             stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        while p.poll() is None:
            sys.stdout.write(p.stdout.readline())
        return p.wait() == 0
    return docker_build_callable

def docker_tag(image,repository,tag=None):
    def docker_tag_callable():
        print("TAG:",image,repository,tag)
        return doc.tag(image,repository,tag,force=True)
    return docker_tag_callable

def docker_push(repository,tag):
    def docker_push_callable():
        error = False
        print("push:",repository,tag)
        try:
            result = doc.push(repository,stream=True,tag=tag,insecure_registry=dodocker_config['insecure'])
        except docker.errors.DockerException as e:
            sys.exit(e)
        for line in result:
            line_parsed = json.loads(line)
            if 'status' in line_parsed:
                sys.stdout.write(line_parsed['status']+'\n')
            if line_parsed.get('errorDetail'):
                sys.stdout.write(line_parsed['errorDetail']['message']+'\n')
                error = True
        return not error
    return docker_push_callable

def get_file_dep(path):
    file_list = []
    for root,dirs,files in os.walk(path):
        [dirs.remove(i) for i in dirs if i.startswith('.')]
        for i in files:
            if i.startswith('.'):
                continue
            file_list.append(os.path.join(root,i))
    return file_list

def git_repos_path(url,checkout_type, checkout):
    return "dodocker_repos/{}".format(hashlib.md5(".".join((url,checkout_type,checkout))).hexdigest())

def update_git(git_url, checkout_type, checkout):
    def update_git_callable():
        error = False
        path = git_repos_path(git_url,checkout_type,checkout)
        if os.path.exists(path):
            if checkout_type in ('commit','tags'):
                # commit and tags don't change
                return not error
            repository = git.Repo(path)
            try:
                response = repository.git.pull()
            except git.GitCommandError:
                error = True
                print ("error on pull for {} {}/{}".format(git_url,checkout_type,checkout))
            else:
                print("git pull on {}".format(git_url))
                print(response)
        else:
            repository = git.Repo.clone_from(git_url,path)
            if checkout_type in ('branch', 'commit'):
                repository.git.checkout(checkout)
            elif checkout_type == 'tags':
                repository.git.checkout('tags/{}'.format(checkout))
            print("done git clone {}".format(git_url))
        return not error
    return update_git_callable

def parse_dodocker_yaml(mode):
    parse_errors = []
    try:
        with open('dodocker.yaml','r') as f:
            yaml_data = yaml.safe_load(f)
    except IOError:
        sys.exit('No dodocker.yaml found')
    for task_description in yaml_data:
        image = task_description['image']

        name = '%s_%s' % (mode, task_description['image'])
        path = str(task_description.get('path',''))
        if not path:
            parse_errors.append('image {}: no path given'.format(image))
        dockerfile = task_description.get('dockerfile','Dockerfile')
        new_task = {'basename':name, 'verbosity':0}
        git_url = git_checkout = git_checkout_type = None
        git_options = task_description.get('git_url',"").split()
        if git_options:
            git_url = git_options[0]
            if len(git_options) == 2:
                try:
                    (git_checkout_type, git_checkout) = git_options[1].split('/')
                except ValueError:
                    pass
                if not git_checkout_type in ('branch','tags','commit'):
                    parse_errors.append('image {}: wrong tree format {} for url {}'.format(image,git_options[1],git_url))
            else:
                git_checkout_type = 'branch'
                git_checkout = 'master'

        """ task dependencies
        """
        new_task['uptodate'] = []
        new_task['task_dep'] = []

        if 'depends' in task_description and mode in ('build','upload'):
            depends_subtask_name = task_description['depends']
            new_task['task_dep'].append('{}_{}'.format(mode,depends_subtask_name))

        if mode == 'git':
            if 'git_url' in task_description:
                new_task['actions']=[update_git(git_url,
                                                git_checkout_type,
                                                git_checkout)]
            else:
                continue

        elif mode == 'build':
            if 'shell_action' in task_description:
                task_type = 'shell'
            else:
                task_type = 'dockerfile'
            if git_url:
                new_task['task_dep'].append('git_{}'.format(image))
                path = "{}/{}".format(git_repos_path(git_url,git_checkout_type,git_checkout),path)
            if task_type == 'shell':
                if not path:
                    path = '.'
                new_task['actions'] = [shell_build(task_description['shell_action'],image,path=path,
                                                   force=dodocker_config.get('no_cache',False))]
            elif task_type == 'dockerfile':
                pull = task_description.get('pull',False)
                rm = task_description.get('rm',True)
                new_task['actions'] = [docker_build(path,tag=image,dockerfile=dockerfile,pull=pull,rm=rm)]
    
            # tagging
            if not 'tags' in task_description:
                tags = []
            else:
                tags = task_description['tags']
            tag = None
            image_no_tag = image
            if ':' in image:
                image_no_tag, tag = image.split(':')
            new_task['actions'].append(docker_tag(
                image, '%s/%s' % (dodocker_config['registry_path'],image_no_tag),tag))
            repo = tag = None
            for t in tags:
                if ':' in t:
                    repo,tag = t.strip().split(':')
                    if not repo:
                        repo = image_no_tag
                else:
                    repo = t
                    tag = None
                new_task['actions'].append(docker_tag(
                    image,'%s/%s' % (dodocker_config['registry_path'],repo) ,tag=tag))
                new_task['actions'].append(docker_tag(image,repo ,tag=tag))
                   
            # IMPORTANT: image_id has to be the last action. The output of the last action is used for result_dep.
            new_task['actions'].append(image_id(image))
            
            # intra build dependencies 
            if task_description.get('file_dep'):
                new_task['file_dep'] = [os.path.join(path,i) 
                                    for i in task_description.get('file_dep')]
            elif path:
                new_task['file_dep'] = get_file_dep(path)
            if 'depends' in task_description:
                new_task['uptodate'].append(result_dep('%s_%s' % (mode,depends_subtask_name)))

            if dodocker_config.get('no_cache') and image in dodocker_config['no_cache_targets']:
                # the image is not up to date, when the cache is disabled by the user
                new_task['uptodate'].append(lambda x=None: False)
            else:
                # an image has to be available
                new_task['uptodate'].append(check_available(image))
            # every task has to run once to build the result_dep chain for every image
            new_task['uptodate'].append(run_once)
        elif mode == 'upload':
            tag = None
            if ':' in image:
                image, tag = image.split(':')
            new_task['actions'] = [docker_push('%s/%s' % (dodocker_config['registry_path'],image), tag)]
        yield new_task
    if parse_errors:
        sys.exit("\n".join(parse_errors))

def task_git():
    all_build_tasks = []
    for task in parse_dodocker_yaml('git'):
        all_build_tasks.append(task['basename'])
        yield task
    if all_build_tasks:
        yield {'basename':'git',
               'actions': None,
               'task_dep': all_build_tasks}

def task_build():
    all_build_tasks = []
    for task in parse_dodocker_yaml('build'):
        all_build_tasks.append(task['basename'])
        yield task
    if all_build_tasks:
        yield {'basename':'build',
               'actions': None,
               'task_dep': all_build_tasks}

def task_upload():
    all_upload_tasks = []
    for task in parse_dodocker_yaml('upload'):
        all_upload_tasks.append(task['basename'])
        yield task

    yield {'basename':'upload',
           'actions': None,
           'task_dep': all_upload_tasks}

    
"""
pretty print a dump of build tasks for debugging purposes
"""
def task_build_dump():
    def build_dump():
        from pprint import pprint
        pprint(list(task_build()))
    return {'actions':[build_dump],
            'verbosity':2}

import doit
LICENSE_TEXT = """
dodocker (c) 2014-2016 n@work Internet Informationssysteme GmbH
written by Andreas Elvers - based on doit by Eduardo Schettino.

This program comes with ABSOLUTELY NO WARRANTY
This is free software, and you are welcome to redistribute it
under certain conditions. See this link for more information:
http://www.gnu.org/licenses/gpl-3.0.en.html

"""

def load_dodocker_config():
    if os.path.exists(dodocker_config_path):
        try:
            with open(dodocker_config_path,'r') as f:
                config = yaml.safe_load(f.read())
        except IOError:
            sys.exit('Failed to read {}'.format(dodocker_config_path))
        return config
    return DEFAULT_DODOCKER_CONFIG
    
def save_dodocker_config(config):
    try:
        with open(dodocker_config_path,'w') as f:
            f.write(yaml.safe_dump(config))
    except IOError:
        sys.exit('Failed to write {}'.format(path))
    
def config_set(key,value):
    if not key in DEFAULT_DODOCKER_CONFIG.keys():
        sys.exit('error: config knows these keys: {}'.format(" ".join(CONFIG.keys())))
    config = load_dodocker_config()
    config[key] = value
    save_dodocker_config(config)

def config_list():
    config = load_dodocker_config()
    for key in config:
        print('{} : {}'.format(key,config[key]))

def process_args(parsed,unparsed):
    if parsed.yamldir:
        os.chdir(parsed.yamldir)
    sys.argv = [sys.argv[0]]
    if parsed.subcommand == 'build':
        if parsed.verbose:
            sys.argv.extend(('--verbosity','2'))
        if parsed.parallel:
            sys.argv.extend(('-n',str(parsed.parallel[0])))
    if parsed.subcommand in ('build','upload'):
        if parsed.targets:
            
            for target in parsed.targets:
                sys.argv.append("{}_{}".format(parsed.subcommand, target))
        else:
            sys.argv.append(parsed.subcommand)
    if parsed.subcommand == 'build' and parsed.no_cache:
        dodocker_config['no_cache'] = True
        if parsed.targets:
            dodocker_config['no_cache_targets'] = parsed.targets

    elif parsed.subcommand == 'doit':
        sys.argv.extend(unparsed)
    elif parsed.subcommand == 'config':
        if parsed.config_mode == 'list':
            config_list()
        elif parsed.set_secure:
            config_set('insecure',False)
        elif parsed.set_insecure:
            config_set('insecure',True)
        elif parsed.set_registry_path:
            config_set('registry_path', parsed.set_registry_path)
        sys.exit(0)

def create_parser():
    parser = argparse.ArgumentParser(epilog=LICENSE_TEXT,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-c', dest='configfile',
                        metavar='config file',
                        help='use this docker config file')
    parser.add_argument('-d', dest='yamldir',
                        metavar='directory',
                        help='this directory contains the dodocker.yaml file')
    
    subparsers = parser.add_subparsers(
        title='sub-commands of dodocker',
        description='dodocker is devided into sub-commands. Please refer to their help.',
        dest='subcommand',
        help='sub-command help')
    build_parser = subparsers.add_parser(
        'build',
        help='build all or selected dodocker targets')
    build_parser.add_argument('-v','--verbose',action='store_true',help='display the build stdout')
    build_parser.add_argument('-n',nargs=1,type=int,metavar='count',
                              dest='parallel',help='number of tasks run in parallel')
    build_parser.add_argument('--no-cache', action='store_true', help='do a docker build without using the cache')
    
    build_parser.add_argument('targets',metavar='target',nargs='*',help='list of targets to build')
    upload_parser = subparsers.add_parser(
        'upload',
        help='upload built images to registry')
    upload_parser.add_argument('targets',metavar='target',nargs='*',help='list of targets to upload')
    doit_parser = subparsers.add_parser(
        'doit',
        help='pass raw doit commands')
    config_parser = subparsers.add_parser(
        'config',
        help='set config parameter')
    group = config_parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--set-insecure', action='store_true',
                       help='given registry is connected insecure (http/self-signed)')
    group.add_argument('--set-secure', action='store_true',
                       help='given registry is connected secure')
    group.add_argument('--set-registry-path', help='url to registry',metavar='url')
    group.add_argument('--list',dest='config_mode', action='store_const', const='list')
    return parser

def run_dodocker_cli(args):
    # helper function for external programs like tests
    parser = create_parser()
    parsed = parser.parse_known_args(args)
    dodocker_config.clear()
    dodocker_config.update(load_dodocker_config())
    process_args(*parsed)
    doit.run(globals())

def main():
    parser = create_parser()
    parsed = parser.parse_known_args()
    dodocker_config.update(load_dodocker_config())
    process_args(*parsed)
    doit.run(globals())

