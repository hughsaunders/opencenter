#!/usr/bin/env python
import copy
import logging

import sqlalchemy

from roush.db.database import session
from roush.db import exceptions
from roush.db import inmemory

from roush.webapp.ast import FilterBuilder, FilterTokenizer


LOG = logging.getLogger(__name__)


class DbAbstraction(object):
    def __init__(self):
        classname = self.__class__.__name__.lower()
        self.logger = logging.getLogger('%s.%s' % (__name__, classname))

    def get_columns(self):
        raise NotImplementedError

    def get_all(self):
        raise NotImplementedError

    def get_schema(self):
        raise NotImplementedError

    def create(self, data):
        raise NotImplementedError

    def delete(self, id):
        raise NotImplementedError

    def get(self, id):
        raise NotImplementedError

    def filter(self, filters):
        """get data by sql alchemy filters"""
        raise NotImplementedError

    def query(self, query):
        """get data with filter language query"""
        query = '%s: %s' % (self.name, query)

        builder = FilterBuilder(FilterTokenizer(), query)
        result = builder.filter()
        return result

    def update(self, id, data):
        raise NotImplementedError

    def _sanitize_for_update(self, data):
        # should we sanitize, or raise?
        retval = copy.deepcopy(data)

        schema = self.get_schema()['schema']

        ro_fields = [x for x in schema if schema[x]['updatable'] is False]

        for field in ro_fields:
            if field in retval:
                retval.pop(field)

        for field in data:
            if not field in schema.keys():
                retval.pop(field)

        return retval

    def _sanitize_for_create(self, data):
        retval = copy.deepcopy(data)

        schema = self.get_schema()['schema']

        required_fields = [x for x in schema if schema[x]['required'] is True]
        ro_fields = [x for x in schema if schema[x]['read_only'] is True]

        # this should be generalized to pks, I think?
        if 'id' in required_fields:
            required_fields.remove('id')

        for field in required_fields:
            if not field in retval:
                raise KeyError('missing required field %s' % field)

        for field in ro_fields:
            if field in retval:
                retval.pop(field)

        for field in data:
            if not field in schema.keys():
                retval.pop(field)

        return retval


class SqlAlchemyAbstraction(DbAbstraction):
    def __init__(self, model, name):
        self.model = model
        self.name = name

        super(SqlAlchemyAbstraction, self).__init__()

    def get_columns(self):
        field_list = [c for c in self.model.__table__.columns.keys()]
        if hasattr(self.model, '_synthesized_fields'):
            field_list += self.model._synthesized_fields

        return field_list

    def get_all(self):
        field_list = self.get_columns()

        return [dict((c, getattr(r, c))
                     for c in field_list)
                for r in self.model.query.all()]

    def get_schema(self):
        obj = self.model
        cols = obj.__table__.columns

        fields = {}
        for k in cols.keys():
            fields[k] = {}
            fields[k]['type'] = str(cols[k].type)
            if repr(cols[k].type) == 'JsonBlob()':
                fields[k]['type'] = 'JSON'

            if repr(cols[k].type) == 'JsonEntry()':
                fields[k]['type'] = 'JSON_ENTRY'

            fields[k]['primary_key'] = cols[k].primary_key
            fields[k]['unique'] = cols[k].unique or cols[k].primary_key
            fields[k]['updatable'] = True
            fields[k]['required'] = not cols[k].nullable
            fields[k]['read_only'] = False

            if hasattr(obj, '_non_updatable_fields'):
                if k in obj._non_updatable_fields:
                    fields[k]['updatable'] = False

            if len(cols[k].foreign_keys) > 0:
                fields[k]['fk'] = list(cols[k].foreign_keys)[0].target_fullname

        if hasattr(obj, '_synthesized_fields'):
            for syn in obj._synthesized_fields:
                fields[syn] = {'type': 'TEXT',
                               'unique': False,
                               'required': False,
                               'updatable': False,
                               'read_only': True,
                               'primary_key': False}

        return {'schema': fields}

    def create(self, data):
        """Query helper for creating a row

        :param model: name of the table model
        :param fields: dict of columns:values to create
        """

        new_data = self._sanitize_for_create(data)
        r = self.model(**new_data)

        session.add(r)
        try:
            session.commit()
            ret = dict((c, getattr(r, c))
                       for c in self.get_columns())
            return ret
        except sqlalchemy.exc.StatementError as e:
            session.rollback()
            # msg = e.message
            msg = "JSON object must be either type(dict) or type(list) " \
                  "not %s" % (e.message)
            raise exceptions.CreateError(msg)
        except sqlalchemy.exc.IntegrityError as e:
            session.rollback()
            msg = "Unable to create %s, duplicate entry" % (self.name.title())
            raise exceptions.CreateError(message=msg)

    def delete(self, id):
        r = self.model.query.filter_by(id=id).first()
        # We need generate an object hash to pass to the backend notification

        try:
            session.delete(r)
            session.commit()
            return True
        except sqlalchemy.orm.exc.UnmappedInstanceError as e:
            session.rollback()
            msg = "%s id does not exist" % (self.name.title())
            raise exceptions.IdNotFound(message=msg)
        except sqlalchemy.exc.InvalidRequestError as e:
            session.rollback()
            msg = e.msg
            raise RuntimeError(msg)

    def get(self, id):
        result = self.filter({'id': id})

        if len(result) == 0:
            return None

        return result[0]

    def filter(self, filters):
        """get data by sql alchemy filters"""
        filter_options = sqlalchemy.sql.and_(
            * [self.model.__table__.columns[k] == v
               for k, v in filters.iteritems()])
        r = self.model.query.filter(filter_options)
        if not r:
            result = None
        else:
            result = [dict((c, getattr(res, c))
                           for c in self.get_columns()) for res in r]
        return result

    def update(self, id, data):
        new_data = self._sanitize_for_update(data)
        r = self.model.query.filter_by(id=id).first()

        for field in new_data:
            r.__setattr__(field, data[field])

        try:
            ret = dict((c, getattr(r, c))
                       for c in r.__table__.columns.keys())
            session.commit()
            return ret
        except sqlalchemy.exc.InvalidRequestError as e:
            print "invalid req"
            session.rollback()
            msg = e.msg
            raise RuntimeError(msg)
        except:
            session.rollback()
            raise


class InMemoryAbstraction(DbAbstraction):
    # with the in-memory abstraction, we pass a dict that is
    # implemented in keys.  We'll still use the model table to
    # describe metadata, though.
    def __init__(self, model, name, dictionary):
        self.dictionary = dictionary
        self.model = model
        self.name = name

        super(InMemoryAbstraction, self).__init__()

    def get_columns(self):
        cols = []

        for attr in dir(self.model):
            if isinstance(getattr(self.model, attr), inmemory.Column):
                cols.append(attr)

        if hasattr(self.model, '_synthesized_fields'):
            cols += self.model._synthesized_fields

        return cols

    def get_all(self):
        return self.dictionary.values()

    def get_schema(self):
        fields = {}

        for attr in dir(self.model):
            col = getattr(self.model, attr)

            if isinstance(getattr(self.model, attr), inmemory.Column):
                fields[attr] = col.schema

        if hasattr(self.model, '_synthesized_fields'):
            for syn in self.model._synthesized_fields:
                fields[syn] = {'type': 'TEXT',
                               'unique': False,
                               'required': False,
                               'updatable': False,
                               'read_only': True,
                               'primary_key': False}

        # this should not be
        return {'schema': fields}

    def create(self, data):
        new_data = self._sanitize_for_create(data)

        # try:
        new_thing = self.model(**new_data)

        # except TypeError:
        #     raise exceptions.CreateError('bad type.')

        retval = dict((c, getattr(new_thing, c))
                      for c in self.get_columns())

        retval['id'] = self._get_new_id()
        self.dictionary[retval['id']] = retval
        return retval

    def delete(self, id):
        id = int(id)

        if not id in self.dictionary:
            raise exceptions.IdNotFound(message='id %d does not exist' % id)

        self.dictionary.pop(id)
        return True

    def get(self, id):
        # This sort of naively assumes that the id
        # is an integer.  That's probably mostly right though.
        id = int(id)

        if id in self.dictionary:
            return self.dictionary[id]
        return None

    def update(self, id, data):
        id = int(id)

        new_data = self._sanitize_for_update(data)
        self.dictionary[id].update(new_data)
        return self.dictionary[id]

    def _get_new_id(self):
        if len(self.dictionary) == 0:
            return 1
        return max(self.dictionary.keys()) + 1
