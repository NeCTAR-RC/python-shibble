from os import path
from logging.config import fileConfig

import bottle
from paste import deploy
import sqlalchemy

from bottle_sqlalchemy import SQLAlchemyPlugin
import models
from shibble import cfg
import views  # noqa: F401


CONF = cfg.CONF
OSLO_CONF = cfg.OSLO_CONF
bottle.TEMPLATE_PATH.append(path.join(path.dirname(__file__), "./templates/"))


# a dirty hack to pass the support url to the exception handler
support_url = ""


def make_app(global_conf, database_uri, **kw):
    # This is a WSGI application:
    app = bottle.default_app()

    if 'logging' in kw:
        if not path.isabs(kw['logging']):
            logging_conf = path.join(path.dirname(global_conf['__file__']),
                                     kw['logging'])
        else:
            logging_conf = kw['logging']
        fileConfig(logging_conf)

    # Here we merge all the keys into one configuration
    # dictionary; you don't have to do this, but this
    # can be convenient later to add ad hoc configuration:
    conf = global_conf.copy()
    conf.update(kw)
    global support_url
    support_url = conf['support_url']
    if "debug" in conf:
        bottle.debug(True)

    if "disable_error_handler" in conf:
        app.catchall = False

    # configure shibboleth database
    engine = sqlalchemy.create_engine(database_uri,
                                      pool_size=5,
                                      pool_recycle=60,
                                      poolclass=sqlalchemy.pool.QueuePool)
    plugin = SQLAlchemyPlugin(engine, models.Base.metadata)
    app.install(plugin)

    config_file = conf['__file__']
    # Required for OSLO RPC.
    OSLO_CONF([], default_config_files=[config_file])
    # Local config.
    CONF.read(config_file)

    models.Base.metadata.create_all(engine)

    # ConfigMiddleware means that paste.deploy.CONFIG will,
    # during this request (threadsafe) represent the
    # configuration dictionary we set up:
    app = deploy.config.ConfigMiddleware(app, conf)
    return app
