# vim: tabstop=4 shiftwidth=4 softtabstop=4

from itertools import islice

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import UnmappedInstanceError
from sqlalchemy.sql import and_, or_

from db.database import db_session
from db import exceptions as exc
from db.models import Adventures, Clusters, Nodes, Roles, Tasks


def _model_get_all(model):
    tables = {'adventures': Adventures,
              'clusters': Clusters,
              'nodes': Nodes,
              'roles': Roles,
              'tasks': Tasks}
    result = [dict((c, getattr(r, c))
              for c in r.__table__.columns.keys())
              for r in tables[model].query.all()]
    return result


def _model_get_columns(model):
    tables = {'adventures': Adventures,
              'clusters': Clusters,
              'nodes': Nodes,
              'roles': Roles,
              'tasks': Tasks}
    result = [c for c in tables[model].__table__.columns.keys()]
    return result


def _model_get_schema(model):
    obj = globals()[model.capitalize()]
    cols = obj.__table__.columns

    fields = {}
    for k in cols.keys():
        fields[k] = {}
        fields[k]['type'] = str(cols[k].type)
        if repr(cols[k].type) == 'JsonBlob()':
            fields[k]['type'] = 'JSON'

        fields[k]['unique'] = cols[k].unique or cols[k].primary_key

        if len(cols[k].foreign_keys) > 0:
            fields[k]['fk'] = list(cols[k].foreign_keys)[0].target_fullname

    return {'schema': fields}


def _model_delete_by_id(model, pk_id):
    """Query helper for deleting a node

    :param model: name of the table model
    :param pk_id: id to delete
    """
    tables = {'adventures': Adventures,
              'clusters': Clusters,
              'nodes': Nodes,
              'roles': Roles,
              'tasks': Tasks}
    r = tables[model].query.filter_by(id=pk_id).first()
    try:
        db_session.delete(r)
        db_session.commit()
        return True
    except UnmappedInstanceError, e:
        db_session.rollback()
        msg = "%s id does not exist" % (model.title())
        raise exc.IdNotFound(message=msg)


def _model_get_by_id(model, pk_id):
    """Query helper for getting a node

    :param model: name of the table model
    :param pk_id: id to delete
    """
    tables = {'adventures': Adventures,
              'clusters': Clusters,
              'nodes': Nodes,
              'roles': Roles,
              'tasks': Tasks}
    r = tables[model].query.filter_by(id=pk_id).first()

    if not r:
        return None

    result = [dict((c, getattr(r, c))
                   for c in r.__table__.columns.keys())
              for r in tables[model].query.all()]

    return result[0]


def _model_get_by_filter(model, filters):
    """Query helper that returns a node dict.

    :param filters: dictionary of filters; that are combined with AND
                    to filter the result set.
    """
    tables = {'adventures': Adventures,
              'clusters': Clusters,
              'nodes': Nodes,
              'roles': Roles,
              'tasks': Tasks}
    filter_options = and_(
        * [tables[model].__table__.columns[k] == v
           for k, v in filters.iteritems()])
    r = tables[model].query.filter(filter_options).first()
    if not r:
        result = None
    else:
        result = dict((c, getattr(r, c))
                      for c in r.__table__.columns.keys())
    return result


def adventures_get_all():
    """Query helper that returns a dict of all adventures"""
    return _model_get_all('adventures')


def adventure_create(fields):
    field_list = [c for c in Adventures.__table__.columns.keys()]
    field_list.remove('id')
    a = Adventures(**dict((field, fields[field])
                          for field in field_list if field in fields))
    db_session.add(a)
    try:
        db_session.commit()
        return dict((c, getattr(a, c))
                    for c in a.__table__.columns.keys())
    except IntegrityError, e:
        db_session.rollback()
        msg = "Unable to create Adventure"
        raise exc.CreateError(message=msg)


def adventure_delete_by_id(adventure_id):
    """Query helper for deleting a adventure

    :param adventure_id: id of adventure to delete
    """
    try:
        return _model_delete_by_id('adventures', adventure_id)
    except exc.IdNotFound, e:
        raise exc.AdventureNotFound(e.message)


def clusters_get_all():
    """Query helper that returns a dict of all clusters"""
    return _model_get_all('clusters')


def cluster_get_by_filter(filters):
    """Query helper that returns a cluster dict.

    :param filters: dictionary of filters; that are combined with AND
                    to filter the result set.
    """
    #TODO(shep): this should accept an array.. and return the first result
    result = _model_get_by_filter('clusters', filters)
    return result


def cluster_get_by_id(cluster_id):
    """Query helper that returns a node by cluster_id

    :param cluster_id: id of the cluster to lookup
    """
    result = cluster_get_by_filter({'id': cluster_id})
    return result


def cluster_get_columns():
    """Query helper that returns a list of Clusters columns"""
    result = _model_get_columns('clusters')
    return result


def cluster_delete_by_id(cluster_id):
    """Query helper for deleting a cluster

    :param cluster_id: id of cluster to delete
    """
    try:
        return _model_delete_by_id('clusters', cluster_id)
    except exc.IdNotFound, e:
        raise exc.NodeNotFound()


def node_create(fields):
    field_list = [c for c in Nodes.__table__.columns.keys()]
    field_list.remove('id')
    a = Nodes(**dict((field, fields[field])
                     for field in field_list if field in fields))
    db_session.add(a)
    try:
        db_session.commit()
        return dict((c, getattr(a, c))
                    for c in a.__table__.columns.keys())
    except IntegrityError, e:
        db_session.rollback()
        msg = "Unable to create Node, duplicate entry"
        raise exc.CreateError(message=msg)


#def node_update_by_id(node_id, fields):
#    field_list = [c for c in Nodes.__table__.columns.keys()]
#    field_list.remove('id')
#    r = Nodes.query.filter_by(id=node_id).first()
#    r.__setattribute__((field, fields[field]) for field in field_list if field in fields)
#    try:
#        db_session.commit()


def nodes_get_all():
    """Query helper that returns a dict of all nodes"""
    return _model_get_all('nodes')


def node_get_columns():
    """Query helper that returns a list of Nodes columns"""
    result = _model_get_columns('nodes')
    return result


def node_get_by_filter(filters):
    """Query helper that returns a node dict.

    :param filters: dictionary of filters; that are combined with AND
                    to filter the result set.
    """
    #TODO(shep): this should accept an array.. and return the first result
    result = _model_get_by_filter('nodes', filters)
    return result


def node_get_by_id(node_id):
    """Query helper that returns a node by node_id

    :param node_id: id of the node to lookup
    """
    result = node_get_by_filter({'id': node_id})
    return result


def node_delete_by_id(node_id):
    """Query helper for deleting a node

    :param node_id: id of node to delete
    """
    try:
        return _model_delete_by_id('nodes', node_id)
    except exc.IdNotFound, e:
        raise exc.NodeNotFound()


def roles_get_all():
    """Query helper that returns a dict of all roles"""
    return _model_gett_all('roles')


def role_get_columns():
    """Query helper that returns a list of Roles columns"""
    result = _model_get_columns('roles')
    return result


def tasks_get_all():
    """Query helper that returns a dict of all tasks"""
    return _model_get_all('tasks')


def task_get_columns():
    """Query helper that returns a list of Tasks columns"""
    result = _model_get_columns('tasks')
    return result


def task_get_by_filter(filters):
    """Query helper that returns a node dict.

    :param filters: dictionary of filters; that are combined with AND
                    to filter the result set.
    """
    filter_options = and_(
        * [Tasks.__table__.columns[k] == v
           for k, v in filters.iteritems()])
    r = Tasks.query.filter(filter_options).first()
    if not r:
        result = None
    else:
        result = dict((c, getattr(r, c))
                      for c in r.__table__.columns.keys())
    return result