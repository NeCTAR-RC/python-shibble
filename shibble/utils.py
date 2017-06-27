import logging
import base64
import sha
import random
import smtplib
import dbus

from email.mime.text import MIMEText

import ldap
import ldap.modlist as modlist

from shibble import cfg
from shibble.models import User

LOG = logging.getLogger('shibble.utils')
CONF = cfg.CONF

CONST_STRING = \
    """When we speak of free software, we are referring to freedom, not
    price. Our General Public Licenses are designed to make sure that you
    have the freedom to distribute copies of free software (and charge for
    them if you wish), that you receive source code or can get it if you
    want it, that you can change the software or use pieces of it in new
    free programs, and that you know you can do these things."""


def create_password():
    return base64.encodestring(
        sha.sha(str(random.randint(1, 99999999)) +
                CONST_STRING).hexdigest())[:32]


def send_signup_email(name, mail, password):
    subject = "Account has been created"
    body = """
Hi {name},

Your account has been created:
Username: {mail}
Password: {password}

Thanks
""".format(name=name, mail=mail, password=password)

    LOG.info('Sending email to {}'.format(mail))
    do_email_send(subject, body, mail)


def do_email_send(subject, body, recipient):
    msg = MIMEText(body)
    msg['From'] = CONF.mail.from_address
    msg['To'] = recipient
    msg['Reply-to'] = CONF.mail.reply_to
    msg['Subject'] = subject

    s = smtplib.SMTP(CONF.mail.server)
    try:
        s.sendmail(msg['From'], [recipient], msg.as_string())
    except smtplib.SMTPRecipientsRefused as err:
        LOG.error('Error sending email: %s', str(err))
    finally:
        s.quit()


def get_ldap_connection():
    l = ldap.initialize(CONF.ldap.connection_string)
    l.simple_bind_s(CONF.ldap.bind_dn, CONF.ldap.bind_pw)
    return l


def get_next_uid():
    idlist = []
    nid = 2000

    search_filter = "(&(uidNumber=*)(objectClass=posixAccount))"
    l = get_ldap_connection()
    res = l.search_s(CONF.ldap.user_dn, ldap.SCOPE_SUBTREE, search_filter)
    for i in res:
        j = i[1]
        idlist.append(int(j['uidNumber'][0]))
    idlist.sort()
    testid = nid
    while True:
        if idlist.count(testid) == 0:
            nid = testid
            break
        testid = testid + 1
    return nid


def user_exists(user):
    l = get_ldap_connection()
    search_filter = "(&(uid={})(objectClass=posixAccount))".format(user)
    try:
        ldap_result_id = l.search(CONF.ldap.user_dn, ldap.SCOPE_SUBTREE,
                                  search_filter, None)
        exist = 0
        while 1:
            result_type, result_data = l.result(ldap_result_id, 0)
            if not result_data:
                break
            else:
                if result_type == ldap.RES_SEARCH_ENTRY:
                    exist = exist + 1
        if exist == 1:
            return True
        else:
            return False
    #except ldap.LDAPError as e:
    #    LOG.error('LDAP account search failed: {}'.format(e))
    finally:
        l.unbind_s()


def create_user(db, shib_attrs, password):
    """Add a new user"""
    mail = shib_attrs['mail']
    name = shib_attrs['fullname']

    if user_exists(mail):
        LOG.warning('User account already exists in LDAP')
    else:
        user_dn = "uid={},{}".format(mail, CONF.ldap.user_dn)

        # A dict to help build the "body" of the object
        attrs = {}
        attrs['objectclass'] = ['top', 'account', 'posixAccount',
                                'shadowAccount']
        attrs['cn'] = name
        attrs['uid'] = mail
        attrs['uidNumber'] = str(get_next_uid())
        attrs['gidNumber'] = CONF.ldap.group_id
        attrs['homeDirectory'] = '{}/{}'.format(CONF.ldap.home_dir_path, mail)
        attrs['loginShell'] = '/bin/bash'
        attrs['description'] = name
        attrs['gecos'] = name
        attrs['userPassword'] = password

        ldif = modlist.addModlist(attrs)

        try:
            l = get_ldap_connection()
            l.add_s(user_dn, ldif)

            LOG.info("Unix account created for {}".format(mail))

            create_home_dir(mail)
            create_nextcloud_mount(mail, password)

            update_user_state(db, shib_attrs, 'created')
        finally:
            l.unbind_s()


def create_home_dir(username):
    bus = dbus.SystemBus()
    obj = bus.get_object('com.redhat.oddjob_mkhomedir', '/')
    intf_proxy = dbus.proxies.Interface(obj, 'com.redhat.oddjob_mkhomedir')
    mkhomedirfor = intf_proxy.get_dbus_method('mkhomedirfor')
    ret, stdout, stderr = mkhomedirfor(username)

    if int(ret) > 0:
        raise Exception('Failed to create home dir: {0}'.format(str(stderr)))

    return True


def create_nextcloud_mount(username, password):
    bus = dbus.SystemBus()
    obj = bus.get_object('au.org.nectar.nextcloud_storage', '/')
    intf_proxy = dbus.proxies.Interface(obj, 'au.org.nectar.nextcloud_storage')
    mkmount = intf_proxy.get_dbus_method('mknextcloudstorage')
    ret, stdout, stderr = mkmount(username, password)

    if int(ret) > 0:
        raise Exception('Failed to create NextCloud mount: {0}'.format(str(stderr)))

    return True


def create_db_user(db, shib_attrs):
    """Create a new user in the DB from the Shibboleth attributes
    Required Shibboleth attributes are `id`, `fullname` and `mail`
    Return a newly created user.
    """
    # add shibboleth user
    shibuser = User(shib_attrs["id"])
    db.add(shibuser)
    db.commit()
    return shibuser


def update_db_user(db, shib_user, shib_attrs):
    """Update a Shibboleth User with new details passed from
    Shibboleth.
    """
    shib_user.displayname = shib_attrs["fullname"]
    shib_user.email = shib_attrs["mail"]
    shib_user.shibboleth_attributes = shib_attrs
    db.commit()


def update_user_state(db, shib_attrs, state):
    shib_user = db.query(User).filter_by(
        persistent_id=shib_attrs["id"]).first()
    shib_user.state = state
    db.commit()

