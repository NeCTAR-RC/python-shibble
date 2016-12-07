from setuptools import setup, find_packages
from pip.req import parse_requirements

requirements = parse_requirements("requirements.txt", session=False)
version = '6.0'

setup(name='shibble',
      version=version,
      description="shibble",
      long_description="""
      shibble""",
      classifiers=[],  # Get strings from
                       # http://pypi.python.org/pypi?%3Aaction=list_classifiers
      keywords='',
      author='Andy Botting',
      author_email='andy@andybotting.com',
      url='http://nectar.org.au/',
      license='GPL',
      packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
      include_package_data=True,
      zip_safe=False,
      install_requires=[str(r.req) for r in requirements],
      tests_require=['nose',
                     'mock'],
      test_suite='nose.collector',
      entry_points="""
      # -*- Entry points: -*-
      [paste.app_factory]
      main = shibble.wsgiapp:make_app
      """,
      )
