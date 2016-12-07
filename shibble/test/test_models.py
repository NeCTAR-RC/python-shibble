import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shibble.models import (Base, User, create_shibboleth_user,
                            update_shibboleth_user)


class TestModels(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        self.db_sessionmaker = sessionmaker(bind=engine)
        self.db = self.db_sessionmaker()
        self.shib_attrs = {
            'mail': 'test@example.com',
            'fullname': 'john smith',
            'id': '1324'
        }

    def make_shib_user(self, state='new', agreed_terms=True):
        # create registered user
        shibuser = User("1324")
        shibuser.id = "1324"
        shibuser.user_id = 1324
        shibuser.email = "test@example.com"
        shibuser.shibboleth_attributes = self.shib_attrs
        if agreed_terms and state != 'new':
            shibuser.terms = datetime.now()
        else:
            shibuser.terms = None
        shibuser.state = state
        return shibuser

    def test_create_shibboleth_user(self):
        create_shibboleth_user(self.db, self.shib_attrs)
        dbuser, = self.db.query(User).all()
        self.assertEqual(dbuser.persistent_id, self.shib_attrs['id'])

    def test_update_shibboleth_user(self):
        user = self.make_shib_user()
        user.displayname = ''
        user.email = ''
        user.shibboleth_attributes = {}
        self.db.add(user)
        self.db.commit()
        update_shibboleth_user(self.db, user, self.shib_attrs)
        dbuser, = self.db.query(User).all()
        self.assertEqual(dbuser.displayname, self.shib_attrs["fullname"])
        self.assertEqual(dbuser.email, self.shib_attrs["mail"])
        self.assertEqual(dbuser.shibboleth_attributes, self.shib_attrs)

    def test_keystone_authenticate(self):
        pass
