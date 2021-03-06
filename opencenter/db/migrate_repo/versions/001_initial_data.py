#!/usr/bin/env python
#               OpenCenter(TM) is Copyright 2013 by Rackspace US, Inc.
##############################################################################
#
# OpenCenter is licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.  This
# version of OpenCenter includes Rackspace trademarks and logos, and in
# accordance with Section 6 of the License, the provision of commercial
# support services in conjunction with a version of OpenCenter which includes
# Rackspace trademarks and logos is prohibited.  OpenCenter source code and
# details are available at: # https://github.com/rcbops/opencenter or upon
# written request.
#
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 and a copy, including this
# notice, is available in the LICENSE file accompanying this software.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the # specific language governing permissions and limitations
# under the License.
#
##############################################################################

import json
import os

from sqlalchemy import *
from migrate import *

from opencenter.db.api import api_from_models


adventures = [
    {'name': 'Run Chef',
     'dsl': 'run_chef.json',
     'criteria': 'run_chef.criteria'},
    {'name': 'Install Chef Server',
     'dsl':  'install_chef_server.json',
     'criteria': 'install_chef_server.criteria'},
    {'name': 'Create Nova Cluster',
     'dsl': 'create_nova_cluster.json',
     'criteria': 'create_nova_cluster.criteria'},
    {'name': 'Enable HA Infrastructure',
     'dsl': 'enable_ha_infrastructure.json',
     'criteria': 'enable_ha_infrastructure.criteria'},
    {'name': 'Download Chef Cookbooks',
     'dsl': 'download_cookbooks.json',
     'criteria': 'download_cookbooks.criteria'},
    {'name': 'Subscribe Cookbook Channel',
     'dsl': 'subscribe_cookbook_channel.json',
     'criteria': 'subscribe_cookbook_channel.criteria'},
    {'name': 'Sleep',
     'dsl': 'sleep.json',
     'criteria': 'sleep.criteria'},
    {'name': 'Update Server',
     'dsl': 'update_server.json',
     'criteria': 'update_server.criteria'},
    {'name': 'Update Agent',
     'dsl': 'update_agent.json',
     'criteria': 'update_agent.criteria'},
    {'name': 'Create Availability Zone',
     'dsl': 'create_az.json',
     'criteria': 'create_az.criteria'},
    {'name': 'Disable Scheduling on this Host',
     'dsl': 'openstack_disable_host.json',
     'criteria': 'openstack_disable_host.criteria'},
    {'name': 'Enable Scheduling on this Host',
     'dsl': 'openstack_enable_host.json',
     'criteria': 'openstack_enable_host.criteria'},
    {'name': 'Evacuate Host',
     'dsl': 'openstack_evacuate_host.json',
     'criteria': 'openstack_evacuate_host.criteria'},
    {'name': 'Upload Initial Glance Images',
     'dsl': 'openstack_upload_images.json',
     'criteria': 'openstack_upload_images.criteria'},
    {'name': 'Install Chef Client',
     'dsl': 'install_chef.json',
     'criteria': 'install_chef.criteria'},
    {'name': 'Uninstall Chef Client',
     'dsl': 'uninstall_chef.json',
     'criteria': 'uninstall_chef.criteria'},
    {'name': 'Uninstall Chef Server',
     'dsl': 'uninstall_chef_server.json',
     'criteria': 'uninstall_chef_server.criteria'}]


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    api = api_from_models()
    for adventure in adventures:
        new_adventure = {'name': adventure['name']}

        json_path = os.path.join(
            os.path.dirname(__file__), adventure['dsl'])
        criteria_path = os.path.join(
            os.path.dirname(__file__), adventure['criteria'])

        new_adventure['dsl'] = json.loads(open(json_path).read())
        new_adventure['criteria'] = open(criteria_path).read()
        api.adventure_create(new_adventure)

    canned_filters = [{'name': 'unprovisioned nodes',
                       'filter_type': 'node',
                       'expr': 'backend=\'unprovisioned\''},
                      {'name': 'chef client nodes',
                       'filter_type': 'node',
                       'expr': 'backend=\'chef-client\''},
                      {'name': 'chef-server',
                       'filter_type': 'interface',
                       'expr': 'facts.chef_server_uri != None and '
                               'facts.chef_server_pem != None'}]

    for new_filter in canned_filters:
        api._model_create('filters', new_filter)

    workspace = api.node_create({'name': 'workspace'})
    api._model_create('attrs', {'node_id': workspace['id'],
                                'key': 'json_schema_version',
                                'value': 1})
    unprov = api.node_create({'name': 'unprovisioned'})
    api._model_create('facts', {'node_id': unprov['id'],
                                'key': 'parent_id',
                                'value': workspace['id']})
    support = api.node_create({'name': 'support'})
    api._model_create('facts', {'node_id': support['id'],
                                'key': 'parent_id',
                                'value': workspace['id']})

    # Add default fact to the default nodes
    node_list = [(workspace, "Workspace"),
                 (unprov, "Available Nodes"),
                 (support, "Service Nodes")]
    for node, display in node_list:
        api.fact_create({'node_id': node['id'],
                         'key': 'backends',
                         'value': ["container", "node"]})
        api.attr_create({'node_id': node['id'],
                         'key': 'display_name',
                         'value': display})
        api.attr_create({'node_id': node['id'],
                         'key': 'locked',
                         'value': True})


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    api = api_from_models()

    adventure_names = [x['name'] for x in adventures]

    for name in adventure_names:
        adventure_list = api._model_query('adventures', 'name="%s"' % name)
        for adv in adventure_list:
            api._model_delete_by_id('adventures', adv['id'])

    node_list = ['"support"', '"unprovisioned"', '"workspace"']
    for node in node_list:
        tmp = api.nodes_query('name = %s' % node)
        fact_list = api.facts_query('node_id = %s' % tmp[0]['id'])
        for fact in fact_list:
            api.fact_delete_by_id(fact['id'])
        api.node_delete_by_id(tmp[0]['id'])
