from os import path
from datetime import datetime
import logging
import json
import functools

from bottle import route
from bottle import request
from bottle import redirect
from bottle import static_file
from bottle import jinja2_template as template

from paste.deploy.config import CONFIG
from weberror import errormiddleware

from shibble import jwt
from shibble import utils
from shibble import models

LOG = logging.getLogger('shibble.views')

STATIC_FILES = path.join(path.dirname(__file__), 'static')

# include the request in each template
template = functools.partial(template, request=request)


class RapidConnectAttrMap(object):
    data = {'cn': 'cn',
            'displayname': 'fullname',
            'givenname': 'firstname',
            'surname': 'surname',
            'mail': 'mail',
            'edupersontargetedid': 'id'}

    @classmethod
    def parse(cls, environ):
        metadata = {}
        for k, v in cls.data.items():
            if environ.get(k):
                if k == "mail":
                    metadata[v] = str(environ.get(k).lower())
                else:
                    metadata[v] = str(environ.get(k))
        return metadata

    @classmethod
    def get_attr(cls, name):
        for k, v in cls.data.items():
            if name == v:
                return k


@route('/static/:filepath')
def static(filepath):
    return static_file(filepath, root=STATIC_FILES)


@route('/')
def root(db):
  redirect(CONFIG['rapid_connect_url'])

@route('/jwt', method='POST')
def auth_callback(db):
    session = request.environ['beaker.session']
    try:
        jwt_secret = CONFIG['rapid_connect_secret']

        # Assertion is passed in a POST initially, then found in the
        # session afterwards.
        assertion = request.forms.get('assertion')
        if not assertion:
            assertion = session.get('assertion')

        verified_jwt = jwt.decode(assertion, jwt_secret)
        attrs = verified_jwt['https://aaf.edu.au/attributes']
        shib_attrs = RapidConnectAttrMap.parse(attrs)
    except jwt.ExpiredSignature:
        data = {
            'title': 'Sign-in Error',
            'message': 'Security cookie has expired',
        }
        return template('error', **data)

    errors = {}
    for field in ['id', 'mail', 'fullname']:
        if field not in shib_attrs:
            errors[field] = ("Required field '%s' can't be found." %
                             RapidConnectAttrMap.get_attr(field))

    if errors:
        LOG.error('The AAF IdP is not returning the required '
                  'attributes. The following are missing: %s. '
                  'The following are present: %s.' % (', '.join(errors.keys()),
                                                      shib_attrs))
        error_values = errors.values()
        error_values.sort()
        data = {
            'title': 'Error',
            'subject': 'Not enough details have been received from your'
                       'institution',
            'message': 'We need your id, your e-mail and your full name.'
                       '<br />Please contact your institution and tell them '
                       'that their "AAF IdP" is broken!'
                       '<br />Copy and paste the details below into your '
                       'email to your institution\'s support desk.',
            'errors': error_values}
        return template('error', **data)

    if request.forms.get('csrfmiddlewaretoken', ''):
        session['csrfmiddlewaretoken'] = \
            request.forms.get('csrfmiddlewaretoken')
        session.save()


    shib_user = db.query(models.User).filter_by(
        persistent_id=shib_attrs["id"]).first()
    if not shib_user:
        shib_user = utils.create_db_user(db, shib_attrs)

    session['user_id'] = shib_attrs['id']
    session['assertion'] = assertion
    session.save()

    if request.forms.get('agree') and shib_user.state == 'new':
        password = utils.create_password()
        shib_user.terms = datetime.now()
        shib_user.state = 'registered'
        shib_user.password = password
        utils.update_db_user(db, shib_user, shib_attrs)
        db.commit()

        try:
            utils.create_user(db, shib_attrs, password)
        except Exception as e:
            LOG.exception(e)
            data = {
                'title': 'Error',
                'subject': 'There was an error creating your local account',
                'message': 'We encountered an unknown error while trying to'
                           'create your local account for this service'
                           '<br />Please contact <a href="' 
                           ''+ CONFIG['support_url'] + '">support</a> '
                           'to resolve this issue.',
                'errors': [str(e)],
            }
            return template('error', **data)

    if not shib_user.terms:
        data = {'title': 'Terms and Conditions.'}
        return template('terms_form', **data)

    if shib_user.state == 'registered':
        data = {'title': 'Creating Account...',
                'support_url': CONFIG['support_url']}
        return template('creating_account', **data)

    if shib_user.state == 'created':
        if not utils.user_exists(shib_user.email):
            LOG.exception('Incomplete user creation error')
            data = {
                'title': 'Error',
                'message': 'Your details could not be found on the '
                           'central authentication server. '
                           'Thus you will <b><i>not</i></b> be able to '
                           'access the cloud! <br />Please contact <a '
                           'href="' + CONFIG['support_url'] + '">support</a> '
                           'to resolve this issue.'
                           '<br />The error message is:',
                'errors': ['Incomplete user creation error']}

            return template('error', **data)

    utils.update_db_user(db, shib_user, shib_attrs)

    target = CONFIG['target']
    if 'return-path' in request.query:
        target = request.query['return-path']
        if not target:
            LOG.exception('Attempt to authenticate to URL')
            data = {
                'title': 'Error',
                'subject': 'No target given',
                'message': 'No redirect target was given',
            }
            return template('error', **data)

    data = {'username': shib_user.email,
            'password': shib_user.password,
            'target': target}
    return template('redirect', **data)


@route('/account_status', method='GET')
def account_status(db):
    session = request.environ['beaker.session']
    state = None
    shib_user = db.query(models.User).filter_by(
        persistent_id=session['user_id']).first()

    if shib_user:
        state = shib_user.state
    data = {'state': state}
    return json.dumps(data)


@route('/terms')
def terms(db):
    return template('terms_form')

@route('/creating')
def terms(db):
    data = {'title': 'Creating Account...',
            'support_url': CONFIG['support_url']}
    return template('creating_account', **data)


def error_template(head_html, exception, extra):
    from shibble.wsgiapp import support_url
    data = {
        'title': 'Error',
        'message': 'An internal error has occurred and has been logged by '
                   'our system. Our system administrators have been notified.'
                   'If you have been receiving this message often then '
                   'please contact <a href="' + CONFIG['support_url'] +
                   '">support</a> for assistance.'}
    return template('error', **data)


errormiddleware.error_template = error_template
