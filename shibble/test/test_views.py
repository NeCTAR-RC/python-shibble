import unittest
import shutil
import tempfile
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from mock import patch, call, MagicMock, Mock

from shibble.views import ShibbolethAttrMap, root
from shibble.models import Base, User


class MockIdentityService(object):
    def __init__(self, token):
        self.token = token

    def authenticate_shibboleth(self, id, tenant_id):
        return self.token


class TestShibbolethAttrMap(unittest.TestCase):
    def test_parse(self):
        environ = {"persistent-id": "1234",
                   "mail": "Test@example.com"}
        self.assertEqual(ShibbolethAttrMap.parse(environ),
                         {'id': '1234', 'mail': 'test@example.com'})

    def test_attr(self):
        self.assertEqual(ShibbolethAttrMap.get_attr("mail"),
                         "mail")
        self.assertEqual(ShibbolethAttrMap.get_attr("location"),
                         "l")


class MockCONFIG(Mock):
    """
    A Mock object that allows the specification of a .data dict
    which is accessible via the normal dict accessors.
    """
    def __setitem__(self, key, item):
        if not self.data:
            self.data = {}
        self.data[key] = item

    def __getitem__(self, key):
        if self.data:
            return self.data[key]
        raise KeyError

    def __contains__(self, key):
        if self.data:
            try:
                return key in self.data
            except IndexError:
                pass
        return False


class TestRoot(unittest.TestCase):
    missing_attr_msg = "Not enough details have been received from " \
                       "your institution to allow you to " \
                       "log on to the cloud. We need your id, your " \
                       "e-mail and your full name.<br />" \
                       "Please contact your institution and tell " \
                       "them that their \"AAF IdP\" is broken!<br />" \
                       "Copy and paste the details below into your email to " \
                       "your institution's support desk.<br />" \
                       "<b>The following required fields are missing " \
                       "from the AAF service:</b>"

    def make_shib_user(self, state='new', agreed_terms=True):
        # create registered user
        shibuser = User("1324")
        shibuser.id = "1324"
        shibuser.user_id = 1324
        shibuser.email = "test@example.com"
        shibuser.shibboleth_attributes = {
            'mail': 'test@example.com',
            'fullname': 'john smith',
            'id': '1324'
        }
        if agreed_terms and state != 'new':
            shibuser.terms = datetime.now()
        else:
            shibuser.terms = None
        shibuser.state = state
        return shibuser

    def setUp(self):
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        self.db_sessionmaker = sessionmaker(bind=engine)
        self.db = self.db_sessionmaker()
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    @patch("shibble.views.request")
    @patch("shibble.views.template")
    def test_no_attrs(self, mock_template, mock_request):
        mock_request.environ = {"beaker.session": ""}
        response = root(self.db)
        self.assertEqual(
            mock_template.call_args,
            call('error',
                 message=self.missing_attr_msg,
                 errors=["Required field 'displayName' can't be found.",
                         "Required field 'mail' can't be found.",
                         "Required field 'persistent-id' can't be found."],
                 title='Error'))
        self.assertEqual(response, mock_template.return_value)

    @patch("shibble.views.request")
    @patch("shibble.views.template")
    def test_missing_attrs(self, mock_template, mock_request):
        mock_request.environ = {"beaker.session": "",
                                "mail": "test@example.com"}
        response = root(self.db)
        self.assertEqual(
            mock_template.call_args,
            call('error',
                 message=self.missing_attr_msg,
                 errors=["Required field 'displayName' can't be found.",
                         "Required field 'persistent-id' can't be found."],
                 title='Error'))
        self.assertEqual(response, mock_template.return_value)

    @patch("shibble.views.request")
    @patch("shibble.views.template")
    @patch("shibble.models.create_shibboleth_user")
    @patch("shibble.views.CONFIG")
    def test_new_user(self,
                      mock_config,
                      mock_create_shibboleth_user,
                      mock_template, mock_request):
        """
        Given a user who has registered
        And has accepted the terms of service
        When the user visits the site
        Then an ldap user will be created
        And the user will be redirected to the portal with
         a token encoded in the response.
        """
        session = MagicMock()
        mock_request.environ = {"beaker.session": session,
                                "mail": "test@example.com",
                                "displayName": "john smith",
                                "persistent-id": "1324"}
        mock_request.forms = {}

        # mock user
        user = self.make_shib_user(state='new', agreed_terms=False)
        mock_create_shibboleth_user.return_value = user

        response = root(self.db)

        # confirm that the redirect is passed correctly
        self.assertEqual(response,
                         mock_template.return_value)
        self.assertEqual(mock_template.call_args[0], ('terms_form',))

    @patch("shibble.views.request")
    @patch("shibble.views.template")
    @patch("shibble.views.create_shibboleth_user")
    @patch("shibble.views.update_shibboleth_user")
    @patch("shibble.views.CONFIG")
    def test_agreed_terms_user(self,
                               mock_config,
                               mock_update_shibboleth_user,
                               mock_create_shibboleth_user,
                               mock_template, mock_request):
        """
        Given a known user who has not registered
        And has just accepted the terms of service
        When the user visits the site
        Then an ldap user will be created
        And the user will be redirected to the portal with
         a token encoded in the response.
        """
        session = MagicMock()
        mock_request.environ = {"beaker.session": session,
                                "mail": "test@example.com",
                                "displayName": "john smith",
                                "persistent-id": "1324"}
        mock_request.forms = {'agree': True}

        # mock user
        user = self.make_shib_user(state='new')
        mock_create_shibboleth_user.return_value = user

        # mock token
        token_string = '{"access": {"serviceCatalog": ' \
            '[], "token": {"id": "aaaaaa"}}}'
        token = Mock()
        token.to_json.return_value = token_string
        # mock_identity_service.return_value = MockIdentityService(token)

        response = root(self.db)

        # confirm that the ldap user was created
        self.assertEqual(
            mock_update_shibboleth_user.call_args[0][2],
            {'mail': 'test@example.com',
             'fullname': 'john smith', 'id': '1324'}
        )

        self.assertEqual(user.state, "registered")

        # confirm that the redirect is passed correctly
        self.assertEqual(response,
                         mock_template.return_value)
        self.assertEqual(
            mock_template.call_args[0][0],
            'creating_account'
        )

    @patch("shibble.views.request")
    @patch("shibble.views.template")
    @patch("shibble.views.CONFIG")
    def test_registered_user(self,
                             mock_config,
                             mock_template, mock_request):
        """
        Given a user who has registered
        And has accepted the terms of service
        When the user visits the site
        Then an ldap user will be created
        And the user will be redirected to the portal with
         a token encoded in the response.
        """
        session = MagicMock()
        mock_request.environ = {"beaker.session": session,
                                "mail": "test@example.com",
                                "displayName": "john smith",
                                "persistent-id": "1324"}
        mock_request.forms = {}

        shibuser = self.make_shib_user(state='registered')
        db = self.db_sessionmaker()
        db.add(shibuser)
        db.commit()

        response = root(self.db)

        self.assertEqual(
            mock_template.call_args[0],
            ("creating_account",))

        # confirm that the redirect is passed correctly
        self.assertEqual(response,
                         mock_template.return_value)

    @patch("shibble.views.request")
    @patch("shibble.views.template")
    @patch("shibble.views.create_shibboleth_user")
    @patch("shibble.views.CONFIG")
    def test_created_user(self,
                          mock_config,
                          mock_create_shibboleth_user,
                          mock_template, mock_request):
        """
        Given a known user who has already has an ldap account
        When the user visits the site
        And the user will be redirected to the portal with
         a token encoded in the response.
        """
        session = MagicMock()
        mock_request.environ = {"beaker.session": session,
                                "mail": "test@example.com",
                                "displayName": "john smith",
                                "persistent-id": "1324"}
        mock_request.forms = {}

        db = self.db_sessionmaker()
        db.add(self.make_shib_user(state='created'))
        db.commit()

        # mock token
        token = "secret"
        tenant_id = 'abcdef'
        #mock_keystone_authenticate.return_value = token, tenant_id

        response = root(self.db)

        # confirm that the redirect is passed correctly
        self.assertEqual(response,
                         mock_template.return_value)
        self.assertEqual(
            mock_template.call_args,
            call('redirect',
                 tenant_id=tenant_id,
                 token=token,
                 # csrf_token=session.get('csrfmiddlewaretoken'),
                 target=mock_config['target']))

    @patch("shibble.views.request")
    @patch("shibble.views.template")
    @patch("shibble.views.create_shibboleth_user")
    @patch("shibble.views.CONFIG")
    def test_return_path(self,
                         mock_config,
                         mock_create_shibboleth_user,
                         mock_template, mock_request):
        """
        Redirect to a whitelisted return path specified in the query URL.
        """
        session = MagicMock()
        mock_request.environ = {"beaker.session": session,
                                "mail": "test@example.com",
                                "displayName": "john smith",
                                "persistent-id": "1324"}
        mock_request.forms = {}
        mock_request.query = {
            "return-path": "https://test.example.com/auth/token"
            }
        db = self.db_sessionmaker()
        db.add(self.make_shib_user(state='created'))
        db.commit()

        # mock token
        token = "secret"
        tenant_id = 'abcdef'
        #mock_keystone_authenticate.return_value = token, tenant_id

        response = root(self.db)

        # confirm that the redirect is passed correctly
        self.assertEqual(response,
                         mock_template.return_value)
        self.assertEqual(
            mock_template.call_args,
            call('redirect',
                 tenant_id=tenant_id,
                 token=token,
                 target=mock_request.query['return-path']))
