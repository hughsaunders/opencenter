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

import copy
import json
import logging
import time

from sqlalchemy import Column, Integer, String, ForeignKey, Enum, event
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm import relationship
import sqlalchemy.types as types
from sqlalchemy.exc import InvalidRequestError

from database import Base
import api as db_api
import inmemory
import opencenter.backends
from opencenter.db.database import session


# Special Fields
class JsonBlob(types.TypeDecorator):
    impl = types.Text

    def _is_valid_obj(self, value):
        if isinstance(value, dict) or isinstance(value, list):
            return True
        else:
            return False

    def process_bind_param(self, value, dialect):
        if self._is_valid_obj(value):
            return json.dumps(value)
        else:
            raise InvalidRequestError("%s is not an accepted type" %
                                      type(value))

    def process_result_value(self, value, dialect):
        if value is None:
            value = '{}'
        return json.loads(value)


class JsonEntry(types.TypeDecorator):
    impl = types.Text

    def process_bind_param(self, value, dialect):
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            value = ''
        return json.loads(value)


class JsonRenderer(object):
    def __new__(cls, *args, **kwargs):
        # README(shep): This line produces the following DeprecationWarning
        #     DeprecationWarning: object.__new__() takes no parameters
        # obj = super(JsonRenderer, cls).__new__(cls, *args, **kwargs)
        # README(shep): This seems to work and does not throw the warning
        obj = super(JsonRenderer, cls).__new__(cls)
        obj.__dict__['api'] = db_api.api_from_models()
        classname = obj.__class__.__name__.lower()

        obj.__dict__['logger'] = logging.getLogger(
            '%s.%s' % (__name__, classname))
        return obj

    def jsonify(self, api=None):
        if api is None:
            api = db_api.api_from_models()

        classname = self.__class__.__name__.lower()
        field_list = api._model_get_columns(classname)

        newself = self
        if api != self.api:
            newself = copy.copy(self)
            newself.api = api

        return dict([[c, getattr(newself, c)] for c in field_list])


class Tasks(JsonRenderer, Base):
    __tablename__ = 'tasks'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=False)
    action = Column(String(40), nullable=False)
    payload = Column(JsonBlob, default={}, nullable=False)
    state = Column(
        Enum('pending', 'delivered', 'running',
             'done', 'timeout', 'cancelled'),
        default='pending')
    parent_id = Column(Integer, ForeignKey('tasks.id'), default=None)
    result = Column(JsonBlob, default={})
    submitted = Column(Integer)
    completed = Column(Integer)
    expires = Column(Integer)

    _non_updatable_fields = ['id', 'submitted']

    def __init__(self, node_id, action, payload, state='pending',
                 parent_id=None, result=None, submitted=None, completed=None,
                 expires=None):
        self.node_id = node_id
        self.action = action
        self.payload = payload
        self.state = state
        self.parent_id = parent_id
        self.result = result
        self.submitted = int(time.time())
        self.completed = completed
        self.expires = expires

    def __repr__(self):
        return '<Task %r>' % (self.id)


# set up a listener to auto-populate values in Task struct
@event.listens_for(Tasks.state, 'set')
def task_state_mungery(target, value, oldvalue, initiator):
    non_t = ['pending', 'running', 'delivered']

    if value not in non_t and target.completed is None:
        target.completed = int(time.time())


class Facts(JsonRenderer, Base):
    __tablename__ = 'facts'
    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=False)
    key = Column(String(64), nullable=False)
    value = Column(JsonEntry, default="")
    __table_args__ = (UniqueConstraint('node_id', 'key', name='key_uc'),)

    _non_updatable_fields = ['id', 'node_id', 'key']

    def __init__(self, node_id, key, value=None):
        self.node_id = node_id
        self.key = key
        self.value = value


class Attrs(JsonRenderer, Base):
    __tablename__ = 'attrs'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey('nodes.id'), nullable=False)
    key = Column(String(64), nullable=False)
    value = Column(JsonEntry, default="")
    __table_args__ = (UniqueConstraint('node_id', 'key', name='key_uc'),)

    _non_updatable_fields = ['id', 'node_id', 'key']

    def __init__(self, node_id, key, value=None):
        self.node_id = node_id
        self.key = key
        self.value = value


class Nodes(JsonRenderer, Base):
    __tablename__ = 'nodes'
    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)
    adventure_id = Column(Integer, ForeignKey('adventures.id'))
    task_id = Column(Integer, ForeignKey('tasks.id',
                                         use_alter=True,
                                         name='fk_task_id'), default=None)

    _non_updatable_fields = ['id', 'name']
    _synthesized_fields = ['facts', 'attrs']

    def __init__(self, name,
                 backend=None, backend_state=None,
                 adventure_id=None, task_id=None):
        self.name = name
        self.adventure_id = adventure_id
        self.task_id = task_id

    def __repr__(self):
        return '<Nodes %r>' % (self.name)

    @property
    def facts(self):
        def fact_union(fact, value, parent_value):
            if value is FactDoesNotExist:
                value = []

            if not isinstance(parent_value, list):
                self.logger.error('Union inheritance called on non-list fact: '
                                  '%s' % fact)
                return parent_value

            for item in parent_value:
                if not item in value:
                    value.append(item)
            return value

        def fact_parent_clobber(fact, value, parent_value):
            if parent_value is not None:
                return parent_value
            return value

        def fact_child_clobber(fact, value, parent_value):
            if value is not FactDoesNotExist:
                return value
            return parent_value

        def fact_none(fact, value, parent_value):
            return value

        # walk up the parent tree, applying facts downward
        tree = []
        n = self.id
        ns = locals()
        while(n is not None and n not in tree):
            tree.append(n)
            parent = self.api.facts_query(
                'key="parent_id" and node_id=%s' % int(n))
            n = None if len(parent) != 1 else parent[0]['value']

        # okay, we have the tree... apply facts top down
        tree.reverse()

        n = tree.pop(0)
        my_facts = dict(
            [(fact['key'], fact['value'])
             for fact in self.api.facts_query('node_id=%d' % int(n))])

        for n in tree:
            parent_facts = my_facts

            my_facts = dict(
                [(fact['key'], fact['value'])
                 for fact in self.api.facts_query('node_id=%d' % int(n))])

            for parent_k, parent_v in parent_facts.iteritems():
                fact_def = opencenter.backends.fact_by_name(parent_k)
                f = fact_none
                if fact_def is None:
                    self.logger.error('UNKNOWN FACT: %s' % parent_k)
                else:
                    f = ns["fact_%s" % fact_def['inheritance']]

                my_facts[parent_k] = f(
                    parent_k, my_facts.get(parent_k, FactDoesNotExist),
                    parent_v)

                if my_facts[parent_k] is FactDoesNotExist:
                    del my_facts[parent_k]

        return my_facts

    @property
    def attrs(self):
        return dict([[x['key'], x['value']] for x in
                     self.api._model_query('attrs',
                                           'node_id=%d' % self.id)])


@event.listens_for(Nodes, 'after_delete')
def node_cascade_delete(mapper, connection, target):
    node_id = target.id
    for fact in Facts.query.filter_by(node_id=node_id):
        session.delete(fact)

    for attr in Attrs.query.filter_by(node_id=node_id):
        session.delete(attr)

    for task in Tasks.query.filter_by(node_id=node_id):
        task.delete(attr)


class Adventures(JsonRenderer, Base):
    __tablename__ = 'adventures'
    id = Column(Integer, primary_key=True)
    name = Column(String(30), nullable=False)
    dsl = Column(JsonBlob, default={}, nullable=False)
    criteria = Column(String(255))

    _non_updatable_fields = ['id']

    def __init__(self, name, dsl, criteria='true'):
        self.name = name
        self.dsl = dsl
        self.criteria = criteria

    def __repr__(self):
        return '<Adventures %r>' % (self.name)


class Filters(JsonRenderer, Base):
    __tablename__ = 'filters'
    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey('filters.id'), default=None)
    name = Column(String(30))
    parent = relationship('Filters', remote_side=[id])
    filter_type = Column(String(30))
    expr = Column(String(255))

    _non_updatable_fields = ['id']
    _synthesized_fields = ['full_expr']

    def __init__(self, name, filter_type, expr, parent_id=None):
        self.name = name
        self.parent_id = parent_id
        self.filter_type = filter_type
        self.expr = expr

    def __repr__(self):
        return '<Filter %r>' % (self.name)

    @property
    def full_expr(self):
        if self.parent_id:
            if self.api is None:
                return '(%s) and (%s)' % (self.expr, self.parent.full_expr)
            else:
                parent = self.api._model_get_by_id('filters',
                                                   self.parent_id)
                return '(%s) and (%s)' % (self.expr, parent.full_expr)
        else:
            return self.expr


class Primitives(JsonRenderer, inmemory.InMemoryBase):
    id = inmemory.Column(inmemory.Integer, primary_key=True, nullable=False,
                         required=True)
    name = inmemory.Column(inmemory.String(32), required=True)
    args = inmemory.Column(inmemory.JsonBlob, default={})
    constraints = inmemory.Column(inmemory.JsonBlob, default=[])
    consequences = inmemory.Column(inmemory.JsonBlob, default=[])
    weight = inmemory.Column(inmemory.Integer, default=50)
    timeout = inmemory.Column(inmemory.Integer, default=30)

    def __init__(self, name, args=None, constraints=None,
                 consequences=None, weight=50, timeout=30):
        self.name = name
        self.args = args
        self.constraints = constraints
        self.consequences = consequences
        self.weight = weight
        self.timeout = timeout


class CFactDoesNotExist(object):
    pass

FactDoesNotExist = CFactDoesNotExist()
