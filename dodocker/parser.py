"""
======================================================================
dodocker. A build tool for independent docker images and registries.
Copyright (C) 2014-2016  n@work Internet Informationssysteme GmbH

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
======================================================================

======================
dodocker.yaml parser
======================
"""

import yaml, os, sys
import jinja2
import dodocker
from .errors import DodockerParseError

class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self

class TaskInfo:
    def __init__(self):
        self.bare_image_name = None
        self.buildargs = None
        self.depends_subtask_name = None
        self.dockerfile = None
        self.git_url = None
        self.git_checkout_type = None
        self.git_checkout = None
        self.image = None
        self.params = None
        self.path = None
        self.pull = False
        self.flatten = False
        self.rm = True
        self.tags = None
        self.task_type = None
        self.file_dep = None
        self.templates = None
        self.templateargs = None
        self.jinja_env = None

        
class TaskGroup:
    def __init__(self):
        self.task_descriptions = None
        self.base_directory = None
    def load_task_description_from_file(self, filename='dodocker.yaml'):
        self.base_directory = os.path.split(os.path.realpath(filename))[0]
        try:
            with open(filename, 'r') as f:
                yaml_data = yaml.safe_load(f.read())
        except IOError:
            sys.exit('No dodocker yaml defintion found at {}'.format(filename))
        self.task_descriptions = yaml_data
        
    def load_task_descriptions(self, yaml_data):
        self.task_descriptions = yaml.safe_load(yaml_data)
        
    def create_group_data(self):
        parse_errors = []
        group_tags = set()
        for i in self.task_descriptions:
            try:
                for task in self.create_task_data(i):
                    intersect = group_tags.intersection(set(task.tags)) 
                    if intersect:
                        raise DodockerParseError(
                            'Duplicated name:tags are not allowed. Offending name:tags are {}'.format(intersect))
                    group_tags.update(task.tags)
                    yield task
            except DodockerParseError as e:
                parse_errors.extend(e.args)
        if parse_errors:
            raise DodockerParseError(*parse_errors)
        
    def create_task_data(self,task_description):
        # parameter
        param = task_description.get('parameter')
        image = task_description['image']
        if param:
            if not param['mode'] == 'fixed':
                raise DodockerParseError('image {}: parameter is currently only supported with fixed parameter sets'.format(image))
            if 'shell_action' in task_description:
                raise DodockerParseError('image {}: parameter is not available with shell_actions'.format(image))
            if 'tags' in task_description:
                raise DodockerParseError('image {}: tags parameter is not available outside of parameter'.format(image))
            if ':' in task_description['image']:
                raise DodockerParseError('image {}: tag in image name not allowed with parameter'.format(image))
            if len([i for i in param['setup'] if 'tags' in i]) != len(param['setup']):
                raise DodockerParseError('image {}: every parameter item must provide a tags attribute'.format(image))

        if param:
            param_list= param['setup']
        else:
            param_list= [{}]
        for param_item in param_list:

            # general task attributes

            t = TaskInfo()
            t.task_group = self
            t.image = task_description['image']
            t.file_dep = task_description.get('file_dep')
            
            t.path = str(task_description.get('path',''))
            if 'shell_action' in task_description:
                t.task_type = 'shell'
                t.shell_action = task_description['shell_action']
            else:
                t.task_type = 'dockerfile'
                t.dockerfile = task_description.get('dockerfile','Dockerfile')
            if not t.path:
                raise DodockerParseError('image {}: no path given'.format(t.image))

            if param:
                t.buildargs = AttrDict(param_item.get('buildargs', {}))
                t.templateargs = AttrDict(param_item.get('templateargs', {}))
            else:
                t.buildargs = AttrDict(task_description.get('buildargs', {}))
                t.templateargs = AttrDict(task_description.get('templateargs', {}))
            
            t.git_url = git_checkout = git_checkout_type = None
            git_options = task_description.get('git_url',"").split()
            if git_options:
                t.git_url = git_options[0]
                if len(git_options) == 2:
                    try:
                        (t.git_checkout_type, t.git_checkout) = git_options[1].split('/')
                    except ValueError:
                        pass
                    if not t.git_checkout_type in ('branch','tags','commit'):
                        raise DodockerParseError('image {}: wrong tree format {}'.format(t.image,git_options))
                else:
                    t.git_checkout_type = 'branch'
                    t.git_checkout = 'master'
                t.path = os.path.join(dodocker.do.dodocker_build_path(t.git_url,
                                                                      t.git_checkout_type,
                                                                      t.git_checkout)
                                      ,t.path)

            t.depends_subtask_name = task_description.get('depends')

            if t.task_type == 'dockerfile':
                t.pull = task_description.get('pull', False)
                t.flatten = task_description.get('flatten', False)
                t.rm = task_description.get('rm', True)

            unprocessed_tags = []
            if 'tags' in task_description:
                unprocessed_tags.extend(task_description['tags'])
            if param_item.get('tags'):
                unprocessed_tags.extend(param_item['tags'])

            tag = None
            t.bare_image_name = t.image
            if ':' in t.image:
                t.bare_image_name, tag = t.image.split(':')
            if not param_item:
                if tag:
                    unprocessed_tags.insert(0,':'+tag)
                else:
                    unprocessed_tags.insert(0,t.bare_image_name)
            repo = tag = None
            t.tags = []
            for un_tag in unprocessed_tags:
                if ':' in un_tag:
                    repo,tag = un_tag.strip().split(':')
                    if tag == '':
                        tag = None
                    if not repo:
                        repo = t.bare_image_name
                else:
                    repo = un_tag
                    tag = None
                t.tags.append((repo,tag))
            if len(t.tags) != len(set(t.tags)):
                raise DodockerParseError('Duplicated name:tags are not allowed. name:tags are {}'.format(t.tags))
            # t.doit_image_name must contain a unique image name to serve as a doit task name
            t.doit_image_name = ':'.join(filter(lambda x:x, t.tags[0]))
            # template scan
            t.templates = task_description.get('templates',())
            template_dict = {}
            for tmpl_path in t.templates:
                tpath = os.path.join(t.path, tmpl_path)
                assert os.path.realpath(tpath).startswith(self.base_directory)
                with open(tpath,'r') as fh:
                    template_dict[tmpl_path] = fh.read()
            if template_dict:
                t.jinja_env = jinja2.Environment(
                    loader=jinja2.DictLoader(template_dict))
                for tmpl_path in t.jinja_env.list_templates():
                    rendered = t.jinja_env.get_template(tmpl_path).render(
                        template = t.templateargs,
                        t = t.templateargs,
                        build = t.buildargs,
                        b = t.buildargs)
            yield t                
